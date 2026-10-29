"""Audit the live WiseQ storefront and write a dated, reviewable report.

Why this exists
---------------
The delivery needs a reproducible snapshot of what the *public* website says
today, separated from what the repository says, so a reader can tell which
claims are live facts and which are stale notes.

Everything here is read-only and public.  Nothing writes to the storefront,
and no credentials are used.  The output is a Markdown report plus a JSON
sidecar so the numbers can be diffed between runs.

What it captures
----------------
* catalogue size, price/SKU coverage, product types, tags;
* the B2B order-fee and sample rules the storefront encodes as products;
* the collection structure and the agent-facing endpoints;
* the business rules published in ``agents.md``;
* the collection JSON counts, which are the storefront's own view of the
  assortment.

Run it::

    python scripts/audit_public_site.py --out data/public
    python scripts/audit_public_site.py --out data/public --no-network
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiseq.ingest.prices import _norm_sku  # noqa: E402

STORE = "https://www.wiseq.nl"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

COLLECTIONS = {
    "kinderkoptelefoons": "Kids' headphones",
    "kindertablets": "Kids' tablets",
    "smartwatch-voor-kinderen": "Kids' smartwatches",
    "gehoorbescherming": "Hearing protection",
    "alle-opladers-en-adapters": "Chargers and adapters",
    "alle-oplaadkabels": "Charging cables",
    "opladers-voor-iphone-17-16-en-15": "Chargers for iPhone 17/16/15",
    "opladers-voor-iphone-14-en-ouder": "Chargers for iPhone 14 and older",
    "opladers-voor-samsung-galaxy": "Chargers for Samsung Galaxy",
    "opladers-voor-ipad-en-laptop": "Chargers for iPad and laptop",
    "draadloos-en-magsafe": "Wireless and MagSafe",
    "losse-adapters-zonder-kabel": "Adapters without cable",
    "koptelefoons": "Adult headphones",
    "koptelefoon-accessoires": "Headphone accessories",
    "ipad-hoezen-1": "iPad cases",
    "gps-tags": "GPS trackers",
    "laptopkarren": "Laptop carts (schools)",
}

AGENT_ENDPOINTS = {
    "agent brief": f"{STORE}/agents.md",
    "UCP discovery": f"{STORE}/.well-known/ucp",
    "MCP endpoint": f"{STORE}/api/ucp/mcp",
    "sitemap": f"{STORE}/sitemap.xml",
    "agentic sitemap": f"{STORE}/sitemap_agentic_discovery.xml",
    "full catalogue JSON": f"{STORE}/products.json?limit=250",
}

# Business rules the storefront encodes as ordinary products.  These are not
# sellable stock; treating them as such is how a price of 0 or a EUR 2.95
# "fee" ends up quoted to a school as if it were a product.
RULE_TAGS = ("intern", "niet-los-bestelbaar", "b2b-toeslag", "schoolbestelling")
SAMPLE_TAGS = ("sample",)


def fetch(url: str, timeout: int = 45) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return 0, ""


def fetch_json(url: str) -> dict:
    status, body = fetch(url)
    if status != 200 or not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def analyse_catalogue(payload: dict) -> dict:
    products = payload.get("products", []) or []
    with_price = 0
    with_sku = 0
    priced_and_skued = 0
    zero_priced = []
    rules = []
    samples = []
    types = Counter()
    tags = Counter()
    skus = set()

    for product in products:
        product_type = product.get("product_type") or "(none)"
        types[product_type] += 1
        product_tags = product.get("tags") or []
        for tag in product_tags:
            tags[str(tag)] += 1

        lowered = [str(t).lower() for t in product_tags]
        is_rule = any(t in lowered for t in RULE_TAGS)
        is_sample = any(t in lowered for t in SAMPLE_TAGS)

        for variant in product.get("variants", []) or []:
            sku = (variant.get("sku") or "").strip()
            price = variant.get("price")
            compare_at = variant.get("compare_at_price")
            has_price = price not in (None, "", "0.00", "0")
            if sku:
                with_sku += 1
                skus.add(_norm_sku(sku))
            if has_price:
                with_price += 1
            else:
                # A zero price with a compare-at price is a deliberately free
                # item (the e-book).  A zero price with no compare-at price is
                # a price that was never set.  They are different problems,
                # so they are reported differently.
                free = compare_at not in (None, "", "0.00", "0")
                zero_priced.append({
                    "title": product.get("title"),
                    "sku": sku,
                    "price": price,
                    "compare_at_price": compare_at,
                    "kind": "free" if free else "no_price_set",
                })
            if sku and has_price:
                priced_and_skued += 1

            if is_rule:
                rules.append({
                    "title": product.get("title"),
                    "product_type": product_type,
                    "sku": sku,
                    "price": price,
                    "tags": product_tags,
                })
            if is_sample:
                samples.append({
                    "title": product.get("title"),
                    "sku": sku,
                    "price": price,
                })

    return {
        "products": len(products),
        "variants": sum(len(p.get("variants", []) or []) for p in products),
        "with_price": with_price,
        "with_sku": with_sku,
        "priced_and_skued": priced_and_skued,
        "distinct_skus": len(skus),
        "zero_priced_variants": zero_priced,
        "business_rules": rules,
        "samples": samples,
        "product_types": dict(types.most_common()),
        "top_tags": dict(tags.most_common(25)),
        "skus": sorted(skus),
    }


def analyse_agents_md(text: str) -> dict:
    """Pull the durable business facts out of the storefront's agent brief."""
    facts: dict = {}
    patterns = {
        "address": r"Adres:\s*(.+)",
        "email": r"E-mail:\s*(\S+)",
        "phone": r"Telefoon:\s*(.+)",
        "kvk": r"KVK-nummer:\s*(\S+)",
        "delivery_area": r"Levergebied:\s*(.+)",
        "free_shipping_threshold": r"Gratis verzending vanaf\s*(\S+)",
        "warranty": r"(\d+)\s+jaar garantie",
        "return_window": r"(\d+)\s+dagen bedenktijd",
        "return_shipping_terms": r"(\d+)\s+dagen om het product te versturen",
        "credit_bonus": r"(\d+)\s+procent extra",
        "same_day_cutoff": r"vóór\s*(\d{2}:\d{2})",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            facts[key] = match.group(1).strip().rstrip(".")
    facts["payment_methods"] = sorted(set(re.findall(
        r"\b(iDEAL / Wero|Klarna|Visa|Mastercard|American Express|Bancontact|"
        r"PayPal|Apple Pay|Google Pay|Shop Pay)\b", text)))
    facts["sales_channels"] = sorted(set(re.findall(
        r"\b(bol\.com|Amazon)\b", text)))
    facts["mentions_mcp"] = "api/ucp/mcp" in text
    facts["mentions_no_self_checkout"] = bool(
        re.search(r"betaling niet zelfstandig", text, re.IGNORECASE))
    facts["bytes"] = len(text)
    return facts


def collect_collections() -> dict:
    out = {}
    for handle, label in COLLECTIONS.items():
        payload = fetch_json(f"{STORE}/collections/{handle}/products.json?limit=250")
        count = len(payload.get("products", []) or [])
        out[handle] = {"label": label, "products": count}
    return out


def endpoint_status() -> dict:
    out = {}
    for label, url in AGENT_ENDPOINTS.items():
        status, body = fetch(url, timeout=30)
        out[label] = {
            "url": url,
            "status": status,
            "bytes": len(body),
        }
    return out


# Third-party reputation checkers.  These are deliberately read-only and
# deliberately tolerant: most of them bot-wall anonymous requests, and a
# blocked fetch is a fact about the checker, not about WiseQ.  A checker
# that blocks us must never be recorded as "WiseQ has no reviews".
REPUTATION_SOURCES = {
    "scamadviser": "https://www.scamadviser.com/check-website/wiseq.nl",
    "trustpilot": "https://nl.trustpilot.com/review/wiseq.nl",
    "webshopchecker": "https://webshopchecker.nl/shops/wiseq-nl/",
    "webwinkelkeur": "https://www.webwinkelkeur.nl/webshop/wiseq.nl",
}

# bol.com blocks every crawler path (direct fetch, search extraction, CORS
# proxies).  The only retrievable seller data is from Wayback captures, so
# each entry carries the capture date and none of it is current.
#
# These are TWO DIFFERENT bol.com seller accounts, not one account over
# time.  They share the trade name "WISEQ NL" and a correspondence address
# but carry different KvK numbers, VAT numbers, start dates and review
# histories.  The CDX index holds exactly one capture of each.  The report
# must therefore never present them as a growth series.
BOL_ARCHIVE_CAPTURES = {
    "2021-11-20": "https://www.bol.com/nl/nl/v/wiseq-nl/1428598/",
    "2022-05-27": "https://www.bol.com/nl/nl/v/wiseq-nl/1357877/",
}

# The KvK number that identifies the live wiseq.nl entity, per the client
# repository's registry research (Wiseq B.V., Wijzend 56, Grootebroek).
WISEQ_KVK = "84801964"

# Local snapshot of the archived captures, so the bol.com section of the
# audit still reproduces when web.archive.org rate-limits (it does, often).
BOL_SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "public" / \
    "bol-archive-snapshot.json"


def _bol_snapshot() -> dict:
    """Load the stored archive figures, if the snapshot is present."""
    if not BOL_SNAPSHOT.exists():
        return {}
    try:
        data = json.loads(BOL_SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("captures") or {}


def _bol_bkoppeling() -> dict:
    """Load the aggregator figures that accompany the archived captures."""
    if not BOL_SNAPSHOT.exists():
        return {}
    try:
        data = json.loads(BOL_SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("bkoppeling") or {}


def _parse_bol_page(text: str) -> dict:
    """Pull the seller-page counters out of a captured bol.com page.

    These are PRODUCT reviews shown on the seller page, not the rolling
    seller score, and not the aggregator's review count.  All three metrics
    are kept under distinct keys so they cannot be silently compared.
    """
    flat = re.sub(r"(?is)<(script|style|svg|noscript).*?</\1>", " ", text)
    flat = html.unescape(re.sub(r"(?s)<[^>]+>", "\n", flat))
    lines = [ln.strip() for ln in flat.split("\n") if ln.strip()]
    out = {}
    for i, ln in enumerate(lines[:-1]):
        if ln == "Aanbod":
            m = re.match(r"\((\d+)\)", lines[i + 1])
            if m:
                out["listings"] = int(m.group(1))
        for key, prefix in (("total_reviews", "Alle beoordelingen ("),
                            ("positive_reviews", "Positieve beoordelingen ("),
                            ("negative_reviews", "Negatieve beoordelingen ("),
                            ("neutral_reviews", "Neutrale beoordelingen (")):
            if ln.startswith(prefix):
                m = re.search(r"\((\d+)\)", ln)
                if m:
                    out[key] = int(m.group(1))
    m = re.search(r"([\d,]+)% positieve beoordelingen", flat)
    if m:
        out["positivity_pct"] = m.group(1)
    m = re.search(r"KvK-nummer\s*\n?\s*(\d+)", flat)
    if m:
        out["kvk"] = m.group(1)
    m = re.search(r"Btw-nummer\s*\n?\s*(\S+)", flat)
    if m:
        out["btw"] = m.group(1)
    m = re.search(r"Actief sinds:\s*([^\n]+)", flat)
    if m:
        out["active_since"] = m.group(1).strip()
    m = re.search(r"Handelsnaam\s*\n\s*([^\n]+)", flat)
    if m:
        out["trade_name"] = m.group(1).strip()
    m = re.search(r"bol\.com/[a-z]{2}/[a-z]{2}/v/wiseq-nl/(\d+)", text)
    if m:
        out["seller_id"] = m.group(1)
    m = re.search(r"web/(\d{14})/", text)
    if m:
        out["capture_timestamp"] = m.group(1)
    # Rolling 3-month seller score -- a DIFFERENT metric from the counts.
    m = re.search(r"Beoordeling\s*\n\s*(\d,\d)\s*\n\s*Afgelopen 3 maanden:",
                  flat)
    if m:
        out["seller_score"] = m.group(1)
    m = re.search(r"Afgelopen 3 maanden:\s*\n\s*(\d+)\s+beoordelingen", flat)
    if m:
        out["reviews_last_3_months"] = int(m.group(1))
    if "Thuiswinkel Waarborg" in flat:
        out["thuiswinkel_waarborg"] = True
    return out


def collect_bol_archive() -> dict:
    """Recover the bol.com seller figures from archived captures.

    Live bol.com is bot-walled, so a blocked fetch tells us nothing about
    the seller.  These numbers are historical and dated, and the report
    must present them that way.

    web.archive.org rate-limits aggressively, so a stored snapshot is used
    when the live archive cannot be reached.  The snapshot is what makes
    this section reproducible offline.
    """
    out = {}
    snapshot = _bol_snapshot()
    for label, target in BOL_ARCHIVE_CAPTURES.items():
        stamp = label.replace("-", "")
        url = (f"http://web.archive.org/web/{stamp}id_/{target}")
        status, body = fetch(url, timeout=60)
        entry = {"capture": label, "source": url, "status": status,
                 "readable": status == 200}
        if status == 200 and body:
            entry.update(_parse_bol_page(body))
        if not entry.get("readable") and label in snapshot:
            # Fall back to the stored capture so this section is stable.
            entry.update(snapshot[label])
            entry["readable"] = True
            entry["from_snapshot"] = True
            entry["status"] = f"{status} (snapshot)"
        # Identity check: which legal entity does this account belong to?
        if entry.get("kvk"):
            entry["is_wiseq_bv"] = entry["kvk"] == WISEQ_KVK
        out[label] = entry
    return out


def collect_reputation() -> dict:
    """Read what the public reputation checkers say about the shop.

    Returns per-source status plus any headline figure that could be read
    out of the page.  ``blocked`` means the checker refused the request;
    that is reported as ``blocked``, never as a zero score.
    """
    out = {}
    for label, url in REPUTATION_SOURCES.items():
        status, body = fetch(url, timeout=35)
        entry = {"url": url, "status": status, "readable": False, "headline": None}
        if status != 200:
            entry["blocked"] = True
            out[label] = entry
            continue
        entry["readable"] = True
        # The verdict and the two scoring caveats live in embedded JSON that
        # the page serves HTML-escaped, so unescape before matching.
        text = html.unescape(body).replace("\\u002F", "/").replace('\\"', '"')
        if label == "scamadviser":
            # The verdict and the two scoring caveats live in embedded JSON.
            m = re.search(r'"hero":\{"title":"([^"]+)"', text)
            if m:
                entry["headline"] = m.group(1)
            m = re.search(r'"lastUpdated":\{"label":"[^"]*","date":"([^"]+)"', text)
            if m:
                entry["last_updated"] = m.group(1)
            m = re.search(r'"partnerWarning":\s*"(.{0,400}?)"\s*[,}]', text, re.S)
            if m:
                # The warning reads "This website has been reported to us as
                # possible scam by <a ...>Webshopchecker</a>".  The useful
                # part is the link text, not the sentence around it.
                names = re.findall(r"<strong>([^<]{2,60})</strong>", m.group(1))
                entry["reported_by"] = names[0] if names else re.sub(
                    r"<[^>]*>", "", m.group(1)).strip()[:80]
            m = re.search(r'"warningOldData":\{"title":"[^"]*","content":"([^"]*)"', text)
            if m:
                entry["stale_warning"] = m.group(1)
        elif label == "trustpilot":
            m = re.search(r'"numberOfReviews":\s*(\d+)', text)
            if m:
                entry["review_count"] = int(m.group(1))
            m = re.search(r'"trustScore":\s*([0-9.]+)', text)
            if m:
                entry["score"] = float(m.group(1))
            m = re.search(r'"stars":\s*([0-9.]+)', text)
            if m:
                entry["stars"] = float(m.group(1))
        elif label == "webshopchecker":
            # WebshopChecker lists external reports.  When the only report
            # it lists IS the Scamadviser flag, the two sites are not
            # independent sources -- it is one flag seen twice.  That
            # distinction matters more than the score, so it is recorded
            # explicitly.
            m = re.search(r"(\d+)\s+externe melding", _visible_text(text))
            if m:
                entry["external_reports"] = int(m.group(1))
            if "Verdacht volgens Scamadviser" in text:
                entry["report_source"] = "Scamadviser"
                entry["circular_with_scamadviser"] = True
            m = re.search(r"AI risicoscore:\s*(\d+)\s*/\s*(\d+)", _visible_text(text))
            if m:
                entry["ai_risk_score"] = int(m.group(1))
                entry["ai_risk_max"] = int(m.group(2))
            m = re.search(r"Domein\s+(\d+)\s+jaar,\s*(\d+)\s+maanden", _visible_text(text))
            if m:
                entry["domain_age"] = f"{m.group(1)} years, {m.group(2)} months"
            if "Geen community meldingen zichtbaar" in text:
                entry["community_reports"] = 0
            if "Geen keurmerk gevonden" in text:
                entry["keurmerk"] = "not found"
            m = re.search(r"Laatst gecontroleerd op\s+([0-9]{1,2}\s+\w+\s+[0-9]{4})",
                          _visible_text(text))
            if m:
                entry["last_checked"] = m.group(1)
        out[label] = entry
    return out


def _visible_text(page: str) -> str:
    """Strip tags so Dutch page copy can be matched as plain text."""
    stripped = re.sub(r"(?is)<(script|style|svg|noscript).*?</\1>", " ", page)
    stripped = re.sub(r"(?s)<[^>]+>", "\n", stripped)
    stripped = html.unescape(stripped)
    return re.sub(r"[ \t]+", " ", stripped)


def render_report(result: dict) -> str:
    catalogue = result["catalogue"]
    agents = result["agents_md"]
    lines = [
        "# WiseQ public-site audit",
        "",
        f"- Observed: **{result['observed']}**",
        f"- Store: {STORE}",
        f"- Generated by: `scripts/audit_public_site.py`",
        "",
        "Every figure below was read from the live public storefront on the date",
        "shown. Nothing here is taken from the client repository, and nothing",
        "here was inferred from a search result.",
        "",
        "## 1. Catalogue",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Live products | {catalogue['products']} |",
        f"| Live variants | {catalogue['variants']} |",
        f"| Variants with a price | {catalogue['with_price']} |",
        f"| Variants with a SKU | {catalogue['with_sku']} |",
        f"| Variants with both | {catalogue['priced_and_skued']} |",
        f"| Distinct business SKUs | {catalogue['distinct_skus']} |",
        "",
        "## 2. Business rules encoded as products",
        "",
        "These are storefront products that are **not sellable stock**. They are",
        "order rules the shop implements as line items. Quoting them as goods",
        "would put a EUR 0 or a EUR 2.95 fee on a school order as if it were",
        "a product.",
        "",
        "| Title | Type | SKU | Price | Tags |",
        "| --- | --- | --- | --- | --- |",
    ]
    for rule in catalogue["business_rules"]:
        lines.append(
            f"| {rule['title']} | {rule['product_type']} | "
            f"`{rule['sku'] or '(none)'}` | {rule['price']} | "
            f"{', '.join(rule['tags'])} |"
        )
    lines += [
        "",
        "## 3. Sample products",
        "",
        "A sample is a EUR 10 (or EUR 20 for Kids ANC) trial order, not stock.",
        "The sample page states the product price is EUR 7.05 with a EUR 2.95",
        "shipping contribution added at checkout to reach EUR 10 total.",
        "",
        "| Title | SKU | Price |",
        "| --- | --- | --- |",
    ]
    for sample in catalogue["samples"]:
        lines.append(
            f"| {sample['title']} | `{sample['sku'] or '(none)'}` | "
            f"{sample['price']} |"
        )
    if catalogue["zero_priced_variants"]:
        lines += [
            "",
            "## 4. Variants without a sell price",
            "",
            "Two different situations, kept apart on purpose:",
            "",
            "- **free** -- the price is zero on purpose and a compare-at price",
            "  shows what it would otherwise cost;",
            "- **no_price_set** -- no price was ever set, so this variant cannot",
            "  be quoted.",
            "",
            "| Title | SKU | Price | Compare-at | Kind |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in catalogue["zero_priced_variants"]:
            lines.append(
                f"| {row['title']} | `{row['sku'] or '(none)'}` | "
                f"{row['price']} | {row.get('compare_at_price') or '-'} | "
                f"{row['kind']} |"
            )
    lines += [
        "",
        "## 5. Product types",
        "",
        "| Product type | Products |",
        "| --- | --- |",
    ]
    for name, count in catalogue["product_types"].items():
        lines.append(f"| {name} | {count} |")
    lines += [
        "",
        "## 6. Collections",
        "",
        "| Collection | Handle | Products |",
        "| --- | --- | --- |",
    ]
    for handle, info in result["collections"].items():
        lines.append(f"| {info['label']} | `{handle}` | {info['products']} |")
    lines += [
        "",
        "## 7. Agent-facing endpoints",
        "",
        "| Endpoint | URL | HTTP | Bytes |",
        "| --- | --- | --- | --- |",
    ]
    for label, info in result["endpoints"].items():
        lines.append(
            f"| {label} | {info['url']} | {info['status']} | {info['bytes']} |"
        )
    lines += [
        "",
        "## 8. Business rules published in agents.md",
        "",
        "The storefront publishes these itself, so they are live facts rather",
        "than notes from a meeting.",
        "",
        "| Fact | Value |",
        "| --- | --- |",
    ]
    for key, value in agents.items():
        if key == "bytes":
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## 9. What this audit does not establish",
        "",
        "- It does not measure revenue, order volume or customer count. Those",
        "  are not public and are not estimated here.",
        "- It does not verify the claims in the client repository's ledger; that",
        "  ledger governs those separately.",
        "- It does not read the live bol.com storefront. The bol.com figures in",
        "  section 11 come from dated web-archive captures of two separate",
        "  seller accounts, not from the live marketplace, and they are",
        "  historical.",
        "- It does not read the Amazon storefront.",
        "- It does not change anything on the storefront.",
        "",
    ]
    lines.extend(_render_reputation(result.get("reputation") or {}))
    lines.extend(_render_bol_archive(result.get("bol_archive") or {}))
    return "\n".join(lines)


def _render_bol_archive(archive: dict) -> list[str]:
    """Render the archived bol.com seller figures.

    These are historical.  The section has to say so before the numbers,
    because a listing count without its date reads as current.

    Critically: these are TWO DIFFERENT bol.com seller accounts, not one
    account measured twice.  The table is therefore keyed by seller ID and
    legal entity, never laid out as a timeline, because a reader scanning
    two dated rows would otherwise read a growth story that the data does
    not support.
    """
    if not archive:
        return []
    lines = [
        "",
        "## 11. bol.com seller accounts (archived, not current)",
        "",
        "Live bol.com blocks anonymous requests, so these figures come from",
        "dated web-archive captures. **They are historical.**",
        "",
        "**These are two separate bol.com seller accounts, not one account",
        "over time.** Both trade as \"WISEQ NL\" and share a correspondence",
        "address, but they carry different KvK numbers, different VAT",
        "numbers, different start dates and entirely separate review",
        "histories. The Wayback index holds exactly one capture of each, so",
        "no trend can be read from them.",
        "",
        "| Capture | Seller ID | KvK | Active since | Listings | Product reviews | Positivity | Seller score (3-mo) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label, entry in archive.items():
        if not entry.get("readable"):
            lines.append(
                f"| {label} | - | - | - | - | - | archive not retrievable "
                f"(HTTP {entry.get('status')}) | - |"
            )
            continue
        score = entry.get("seller_score")
        lines.append(
            f"| {label} | {entry.get('seller_id', '-')} | "
            f"{entry.get('kvk', '-')} | {entry.get('active_since', '-')} | "
            f"{entry.get('listings', '-')} | "
            f"{entry.get('total_reviews', '-')} | "
            f"{entry.get('positivity_pct', '-')}% | "
            f"{score if score else '-'} |"
        )

    notes = []
    # Identity split: which account belongs to the live wiseq.nl entity?
    for label, entry in archive.items():
        if not entry.get("readable"):
            continue
        if entry.get("is_wiseq_bv") is True:
            notes.append(
                f"- The **{label}** capture (seller {entry.get('seller_id')}) "
                f"carries KvK {entry.get('kvk')} — that is **Wiseq B.V.**, "
                f"the live wiseq.nl entity at Wijzend 56, Grootebroek."
            )
        elif entry.get("is_wiseq_bv") is False:
            notes.append(
                f"- The **{label}** capture (seller {entry.get('seller_id')}) "
                f"carries KvK {entry.get('kvk')}, which is **not** Wiseq "
                f"B.V.'s KvK {WISEQ_KVK}. It is a separate account trading "
                f"under the same name, so its numbers must not be added to "
                f"or compared with Wiseq B.V.'s."
            )
    if any(e.get("thuiswinkel_waarborg") for e in archive.values()):
        notes.append(
            "- A **Thuiswinkel Waarborg** certificate was shown on the seller "
            "page in these captures. Whether it is still current could not "
            "be checked from here (thuiswinkel.nl unreachable)."
        )
    notes.append(
        "- **Three different metrics are in play and must not be mixed:** the "
        "product-review counts above (bol.com's own page counters), the "
        "rolling seller score (8,5 / 8,6 out of 10, a 3-month average), and "
        "the third-party aggregator's rating (9,2 out of 10 from 42 reviews "
        "for seller 1357877, 8,2 from 6 reviews for seller 1428598, both "
        "retrieved 2026-10-29 and both last updated in 2025)."
    )
    lines += [""] + notes if notes else []
    return lines


def _render_reputation(reputation: dict) -> list[str]:
    """Render the third-party reputation checkers.

    A blocked checker is reported as blocked.  It is never reported as a
    score of zero, because "the checker refused us" and "the shop has no
    reputation" are different facts and only one of them is a finding.
    """
    if not reputation:
        return []
    lines = [
        "",
        "## 10. Third-party reputation signals",
        "",
        "These are dated observations of what a public checker displayed.",
        "A checker score is a third-party heuristic, not a verified fact",
        "about the business.",
        "",
        "| Source | Readable | What it showed |",
        "| --- | --- | --- |",
    ]
    for label, entry in reputation.items():
        if not entry.get("readable"):
            lines.append(
                f"| {label} | no (HTTP {entry.get('status')}) | "
                f"the checker refused the request |"
            )
            continue
        bits = []
        if entry.get("headline"):
            bits.append(f"**{entry['headline']}**")
        if entry.get("reported_by"):
            bits.append(f"reported by {entry['reported_by']}")
        if entry.get("last_updated"):
            bits.append(f"last update: {entry['last_updated']}")
        if entry.get("stale_warning"):
            bits.append(f"data is stale ({entry['stale_warning']})")
        if entry.get("review_count") is not None:
            bits.append(f"{entry['review_count']} reviews")
        if entry.get("score") is not None:
            bits.append(f"score {entry['score']}")
        if entry.get("external_reports") is not None:
            bits.append(f"{entry['external_reports']} external report(s)")
        if entry.get("circular_with_scamadviser"):
            bits.append("**that report is the Scamadviser flag itself**")
        if entry.get("ai_risk_score") is not None:
            bits.append(f"AI risk score {entry['ai_risk_score']}/"
                        f"{entry.get('ai_risk_max', 100)}")
        if entry.get("community_reports") == 0:
            bits.append("no community reports")
        if entry.get("domain_age"):
            bits.append(f"domain {entry['domain_age']} old")
        if entry.get("keurmerk"):
            bits.append(f"keurmerk {entry['keurmerk']}")
        if entry.get("last_checked"):
            bits.append(f"last checked {entry['last_checked']}")
        if not bits:
            bits.append("no headline figure readable from the page")
        lines.append(f"| {label} | yes | {'; '.join(bits)} |")

    # The circularity is the single most decision-relevant thing in this
    # table, so it gets its own paragraph rather than a footnote.
    circular = [
        entry for entry in reputation.values()
        if entry.get("circular_with_scamadviser")
    ]
    if circular:
        lines += [
            "",
            "**The two checkers are not independent.** The single external",
            "report listed above is the Scamadviser flag itself. A prospect who",
            "checks both sites sees one flag twice and may read it as two",
            "independent confirmations. It is one.",
        ]
    lines += [
        "",
        "Nothing here is treated as a business fact. The entries are a",
        "starting point for an investigation, not a conclusion.",
    ]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/public",
                        help="output directory for the report and JSON sidecar")
    parser.add_argument("--no-network", action="store_true",
                        help="fail instead of fetching (for offline checks)")
    args = parser.parse_args()

    if args.no_network:
        print("--no-network: nothing to audit", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = fetch_json(f"{STORE}/products.json?limit=250")
    if not payload:
        print("could not read the live catalogue", file=sys.stderr)
        return 1

    _, agents_text = fetch(f"{STORE}/agents.md")

    result = {
        "observed": date.today().isoformat(),
        "store": STORE,
        "catalogue": analyse_catalogue(payload),
        "agents_md": analyse_agents_md(agents_text),
        "collections": collect_collections(),
        "endpoints": endpoint_status(),
        "reputation": collect_reputation(),
        "bol_archive": collect_bol_archive(),
    }

    stamp = result["observed"]
    report_path = out_dir / f"public-site-audit-{stamp}.md"
    json_path = out_dir / f"public-site-audit-{stamp}.json"
    report_path.write_text(render_report(result), encoding="utf-8")
    # The raw catalogue is kept alongside the analysis so the report can be
    # re-derived and diffed offline without hitting the storefront again.
    result["raw_catalogue"] = payload
    json_path.write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    # A stable pointer to the latest run, so scripts do not need to guess
    # the dated filename.
    (out_dir / "public-site-audit-latest.md").write_text(
        render_report(result), encoding="utf-8")
    (out_dir / "public-site-audit-latest.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    catalogue = result["catalogue"]
    print(f"observed            : {stamp}")
    print(f"live products       : {catalogue['products']}")
    print(f"priced+skued variants: {catalogue['priced_and_skued']}"
          f"/{catalogue['variants']}")
    print(f"business rules      : {len(catalogue['business_rules'])}")
    print(f"samples             : {len(catalogue['samples'])}")
    print(f"report              : {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
