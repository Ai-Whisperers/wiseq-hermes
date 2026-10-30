"""Exhaustive per-page audit of the live WiseQ storefront.

Why this exists
---------------
``scripts/audit_public_site.py`` captures the catalogue, the collections
and the reputation signals.  It does NOT look at individual pages.  That
leaves three questions unanswered:

  * Is every page actually crawlable and indexable, or do some of them
    redirect, 404, or carry a ``noindex`` that nobody noticed?
  * Do the pages still agree with each other about the business rules?
    The warranty is published as one year in the general terms and as
    two years on the school-facing pages -- a contradiction that is
    invisible unless each page is read separately.
  * Is the structured data (JSON-LD) present and well formed, so a
    shopping agent can read the pages the way a browser does?

This script reads every URL the storefront publishes in its sitemaps,
classifies what it finds, extracts the claims it can, and cross-checks
the claims against each other.  Every finding is labelled with the URL it
came from, so a reader can verify it rather than trust it.

Read-only, public, no credentials.

Run it::

    python scripts/audit_pages.py --out data/public
    python scripts/audit_pages.py --out data/public --no-network
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
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

STORE = "https://www.wiseq.nl"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# Pages whose business rules we cross-check.  The warranty and the
# return window are the two that the storefront states in several places,
# and both have been observed to disagree with themselves.
POLICY_PAGES = {
    "general terms": "/pages/algemene-voorwaarden",
    "returns": "/pages/retourneren",
    "returns and conditions": "/pages/retourneren-1",
    "shipping": "/pages/bezorging",
    "business customer": "/pages/zakelijke-klant",
    "sample requests": "/pages/sample-aanvragen",
    "class sets for schools": "/pages/klassenset-koptelefoons-kopen-school",
    "headphones for education": "/pages/koptelefoon-voor-het-onderwijs",
    "faq": "/pages/veelgestelde-vragen",
}

# A claim is only reported when the page states it.  Patterns are matched
# against the page's VISIBLE text, not its markup, so a rule that only
# appears in a script or a hidden element is not counted as published.
CLAIM_PATTERNS = {
    "warranty_years": re.compile(r"(\d+)\s*(?:jaar|jaren)\s*garantie", re.I),
    "warranty_years_alt": re.compile(r"garantie[^.]{0,40}?(\d+)\s*(?:jaar|jaren)", re.I),
    "return_days": re.compile(r"(\d+)\s*dagen\s*bedenktijd", re.I),
    "return_days_alt": re.compile(r"bedenktijd[^.]{0,60}?(\d+)\s*dagen", re.I),
    "free_shipping_from": re.compile(r"gratis\s*(?:verzending|bezorging)[^.]{0,40}?€\s*(\d+)", re.I),
    "stock_turnaround": re.compile(r"(\d+)\s*dagen?[^.]{0,40}(?:werkdag|verzonden|geleverd)", re.I),
    "staffel": re.compile(r"staffel", re.I),
    "sample": re.compile(r"proefexemplaar|proefexemplaren|sample", re.I),
    "on_time_target": re.compile(r"(\d{2})\s*%", re.I),
}

# Structured-data types that matter for a shopping agent.
EXPECTED_SCHEMA = ("Product", "Organization", "WebSite", "BreadcrumbList")


def fetch(url: str, timeout: int = 45) -> tuple[int, str, str]:
    """Return (status, body, final_url)."""
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.read().decode("utf-8", "replace"),
                response.geturl(),
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body, url
    except Exception:
        return 0, "", url


def visible_text(page: str) -> str:
    """Strip scripts/styles/markup and return readable text."""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\xa0]+", " ", text)


def meta_content(page: str, name: str) -> str:
    """Read a meta tag's content value.

    Open Graph tags use ``property="og:title"`` while ordinary meta tags
    use ``name="description"``.  Both spellings are looked up here, and
    the attribute order is not assumed -- Shopify emits them in both
    orders on different pages.
    """
    escaped = re.escape(name)
    patterns = [
        rf'<meta[^>]+name=["\']{escaped}["\'][^>]*content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]*name=["\']{escaped}["\']',
        rf'<meta[^>]+property=["\']{escaped}["\'][^>]*content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]*property=["\']{escaped}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page, re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def canonical_of(page: str) -> str:
    match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']', page, re.I)
    if not match:
        match = re.search(
            r'<link[^>]+href=["\'](.*?)["\'][^>]+rel=["\']canonical["\']', page, re.I
        )
    return html.unescape(match.group(1)).strip() if match else ""


def json_ld_blocks(page: str) -> list[dict]:
    """Every JSON-LD block on the page, parsed."""
    out: list[dict] = []
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    ):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            out.append({"__parse_error__": True})
            continue
        if isinstance(payload, list):
            out.extend(x for x in payload if isinstance(x, dict))
        elif isinstance(payload, dict):
            out.append(payload)
    return out


def schema_types(blocks: list[dict]) -> list[str]:
    """Every @type in the JSON-LD blocks."""
    types: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(str(x) for x in t)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for block in blocks:
        walk(block)
    return types


def claims_from(text: str) -> dict:
    """The business rules this page states, in its own words."""
    found: dict = {}
    for name, pattern in CLAIM_PATTERNS.items():
        match = pattern.search(text)
        if match:
            try:
                found[name] = int(match.group(1))
            except (IndexError, ValueError):
                found[name] = True
    return found


def discover_urls() -> dict:
    """Every URL the storefront publishes, from its sitemaps."""
    status, sitemap, _ = fetch(f"{STORE}/sitemap.xml")
    if status != 200 or not sitemap:
        return {"status": status, "sitemaps": [], "pages": [], "products": [],
                "collections": [], "blogs": [], "articles": []}

    children = re.findall(r"<loc>([^<]*sitemap[^<]*)</loc>", sitemap)
    child_urls = [html.unescape(c).replace("&amp;", "&") for c in children]

    result = {
        "status": status,
        "sitemaps": child_urls,
        "pages": [],
        "products": [],
        "collections": [],
        "blogs": [],
        "articles": [],
    }

    for child in child_urls:
        cstatus, body, _ = fetch(child)
        if cstatus != 200 or not body:
            continue
        locs = [html.unescape(x) for x in re.findall(r"<loc>([^<]+)</loc>", body)]
        path = urlparse_path(child)
        if "sitemap_pages" in path:
            result["pages"] = locs
        elif "sitemap_products" in path:
            result["products"] = locs
        elif "sitemap_collections" in path:
            result["collections"] = locs
        elif "sitemap_blogs" in path:
            result["blogs"] = locs
        elif "sitemap_articles" in path:
            result["articles"] = locs

    # The agentic-discovery sitemap is small but load-bearing.
    status, body, _ = fetch(f"{STORE}/sitemap_agentic_discovery.xml")
    if status == 200:
        result["agentic"] = [html.unescape(x) for x in re.findall(r"<loc>([^<]+)</loc>", body)]

    return result


def urlparse_path(url: str) -> str:
    """The path part of a URL, without a full parse (stdlib-only, no query)."""
    return url.split("?")[0]


def is_html_resource(url: str) -> bool:
    """Is this URL an HTML document?

    The storefront also publishes plain-text resources -- ``/agents.md``
    is a Markdown brief for shopping agents, not a page.  Applying HTML
    checks to it (does it have an h1? a canonical? a viewport?) produces
    findings that look alarming and mean nothing, and they bury the real
    ones.  Those resources are still fetched and read; they just do not
    get judged by HTML rules.
    """
    path = urlparse_path(url).lower()
    return not path.endswith((".md", ".txt", ".xml", ".json", ".csv"))


def audit_page(url: str) -> dict:
    """Fetch one page and describe it."""
    status, body, final_url = fetch(url)
    text = visible_text(body)
    html_page = is_html_resource(url)

    blocks = json_ld_blocks(body)
    types = schema_types(blocks)
    parse_errors = sum(1 for b in blocks if b.get("__parse_error__"))

    robots = meta_content(body, "robots")
    description = meta_content(body, "description")
    viewport = meta_content(body, "viewport")

    return {
        "url": url,
        "status": status,
        "final_url": final_url,
        "redirected": final_url.rstrip("/") != url.rstrip("/"),
        "bytes": len(body),
        "is_html": html_page,
        "title": (re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S).group(1).strip()
                  if re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S) else ""),
        "canonical": canonical_of(body) if html_page else "",
        "description": description,
        "has_description": bool(description) if html_page else True,
        "meta_robots": robots,
        "noindex": "noindex" in robots.lower(),
        "has_viewport": bool(viewport) if html_page else True,
        "og_title": meta_content(body, "og:title"),
        "og_description": meta_content(body, "og:description"),
        "og_image": meta_content(body, "og:image"),
        "has_og": bool(meta_content(body, "og:title")) if html_page else True,
        "schema_types": sorted(set(types)),
        "schema_present": sorted(set(types)),
        "schema_parse_errors": parse_errors,
        "schema_missing_expected": [
            t for t in EXPECTED_SCHEMA
            if t in ("Product", "BreadcrumbList") and t not in types
        ] if "products/" in url else [],
        "claims": claims_from(text),
        "word_count": len(text.split()),
        "has_h1": bool(re.search(r"(?is)<h1[^>]*>", body)) if html_page else True,
        "h1_count": len(re.findall(r"(?is)<h1[^>]*>", body)) if html_page else 0,
    }


def cross_check(pages: list[dict]) -> list[dict]:
    """Find the rules the storefront states inconsistently across pages."""
    findings: list[dict] = []

    warranty: dict[str, list[str]] = defaultdict(list)
    returns: dict[str, list[str]] = defaultdict(list)
    free_ship: dict[str, list[str]] = defaultdict(list)

    for page in pages:
        claims = page.get("claims", {})
        label = page["url"].replace(STORE, "")
        if "warranty_years" in claims:
            warranty[str(claims["warranty_years"])].append(label)
        if "warranty_years_alt" in claims and "warranty_years" not in claims:
            warranty[str(claims["warranty_years_alt"])].append(label)
        if "return_days" in claims:
            returns[str(claims["return_days"])].append(label)
        if "return_days_alt" in claims and "return_days" not in claims:
            returns[str(claims["return_days_alt"])].append(label)
        if "free_shipping_from" in claims:
            free_ship[str(claims["free_shipping_from"])].append(label)

    for rule, values in (("warranty years", warranty),
                         ("return window days", returns),
                         ("free shipping threshold EUR", free_ship)):
        if len(values) > 1:
            findings.append({
                "rule": rule,
                "severity": "contradiction",
                "values": {k: sorted(v) for k, v in sorted(values.items())},
                "pages": sorted({u for v in values.values() for u in v}),
                "explanation": (
                    f"The storefront publishes {rule} as "
                    + " and ".join(sorted(values))
                    + ". Pages disagree, so an agent reading one page will "
                      "state a different rule than an agent reading another."
                ),
            })

    return findings


def audit_all(max_pages: int = 0) -> dict:
    """Discover, fetch and cross-check every published page."""
    discovered = discover_urls()
    urls: list[str] = []
    for key in ("pages", "collections", "blogs", "articles"):
        urls.extend(discovered.get(key) or [])
    urls.extend(discovered.get("agentic") or [])
    urls = sorted(set(urls))

    if max_pages:
        urls = urls[:max_pages]

    pages = []
    for index, url in enumerate(urls, 1):
        pages.append(audit_page(url))
        if index % 10 == 0:
            print(f"  ... {index}/{len(urls)} pages", file=sys.stderr, flush=True)
        time.sleep(0.3)

    # A sample of product pages, because there are far too many to fetch.
    product_urls = (discovered.get("products") or [])[:8]
    products = [audit_page(u) for u in product_urls]

    findings = cross_check(pages)

    # Only HTML documents are judged by HTML rules.  The storefront also
    # publishes a plain-text agent brief, and holding a Markdown file to
    # "does it have a canonical URL" produces noise, not signal.
    html_pages = [p for p in pages if p.get("is_html", True)]

    unreachable = [p for p in pages if p["status"] in (0, 404, 410)]
    noindex = [p for p in html_pages if p["noindex"]]
    missing_desc = [p for p in html_pages if not p["has_description"]]
    missing_canonical = [p for p in html_pages if not p["canonical"]]
    no_schema = [p for p in html_pages if not p["schema_types"]]
    bad_schema = [p for p in html_pages if p["schema_parse_errors"]]
    no_h1 = [p for p in html_pages if not p["has_h1"]]
    multiple_h1 = [p for p in html_pages if p["h1_count"] > 1]
    no_viewport = [p for p in html_pages if not p["has_viewport"]]
    no_og = [p for p in html_pages if not p["has_og"]]

    def urls_of(items: list[dict]) -> list[str]:
        return [p["url"].replace(STORE, "") for p in items]

    return {
        "observed": date.today().isoformat(),
        "store": STORE,
        "discovered": {
            "pages": len(discovered.get("pages") or []),
            "collections": len(discovered.get("collections") or []),
            "blogs": len(discovered.get("blogs") or []),
            "articles": len(discovered.get("articles") or []),
            "products": len(discovered.get("products") or []),
            "agentic": len(discovered.get("agentic") or []),
            "sitemaps": discovered.get("sitemaps") or [],
        },
        "audited": {
            "pages": len(pages),
            "products_sampled": len(products),
        },
        "pages": pages,
        "product_sample": products,
        "findings": findings,
        "issues": {
            "unreachable": urls_of(unreachable),
            "noindex": urls_of(noindex),
            "missing_meta_description": urls_of(missing_desc),
            "missing_canonical": urls_of(missing_canonical),
            "missing_structured_data": urls_of(no_schema),
            "malformed_structured_data": urls_of(bad_schema),
            "missing_h1": urls_of(no_h1),
            "multiple_h1": urls_of(multiple_h1),
            "missing_viewport": urls_of(no_viewport),
            "missing_open_graph": urls_of(no_og),
        },
    }


def render_report(result: dict) -> str:
    """A Markdown report a human can read and check."""
    lines: list[str] = []
    lines.append("# WiseQ storefront page audit")
    lines.append("")
    lines.append(f"Observed: **{result['observed']}**")
    lines.append("")
    lines.append("Every URL below was fetched live and read. Findings name the page "
                 "they came from so each one can be verified rather than trusted.")
    lines.append("")

    disc = result["discovered"]
    lines.append("## What the storefront publishes")
    lines.append("")
    lines.append("| Kind | Count |")
    lines.append("| --- | --- |")
    for key in ("pages", "collections", "blogs", "articles", "products", "agentic"):
        lines.append(f"| {key} | {disc.get(key, 0)} |")
    lines.append("")
    lines.append(f"Pages audited: **{result['audited']['pages']}**, "
                 f"product pages sampled: **{result['audited']['products_sampled']}**.")
    lines.append("")

    lines.append("## Contradictions between pages")
    lines.append("")
    if not result["findings"]:
        lines.append("No rule was found stated differently on two pages.")
    for finding in result["findings"]:
        lines.append(f"### {finding['rule']} — CONTRADICTION")
        lines.append("")
        for value, urls in finding["values"].items():
            lines.append(f"- **{value}** on {len(urls)} page(s):")
            for url in urls:
                lines.append(f"  - `{url}`")
        lines.append("")
        lines.append(finding["explanation"])
        lines.append("")

    lines.append("## Technical findings per page")
    lines.append("")
    issues = result["issues"]
    if any(issues.values()):
        lines.append("| Check | Pages affected |")
        lines.append("| --- | --- |")
        for name, urls in issues.items():
            if urls:
                lines.append(f"| {name.replace('_', ' ')} | {len(urls)} |")
        lines.append("")
        for name, urls in issues.items():
            if urls:
                lines.append(f"**{name.replace('_', ' ')}**")
                lines.append("")
                for url in urls[:20]:
                    lines.append(f"- `{url}`")
                if len(urls) > 20:
                    lines.append(f"- ... and {len(urls) - 20} more")
                lines.append("")
    else:
        lines.append("No technical issue was found on any audited page.")
        lines.append("")

    lines.append("## Per-page detail")
    lines.append("")
    lines.append("| Page | Status | Words | H1 | Schema | Claims |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for page in result["pages"]:
        claims = ", ".join(f"{k}={v}" for k, v in sorted(page.get("claims", {}).items()))
        schema = ", ".join(page.get("schema_types", [])) or "-"
        lines.append(
            f"| `{page['url'].replace(STORE, '')}` | {page['status']} | "
            f"{page['word_count']} | {page['h1_count']} | {schema} | {claims or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/public", help="Output directory")
    parser.add_argument("--max-pages", type=int, default=0, help="Only audit N pages")
    parser.add_argument("--no-network", action="store_true",
                        help="Refuse to touch the network (always exits non-zero)")
    args = parser.parse_args()

    if args.no_network:
        print("--no-network: this audit needs the live storefront.", file=sys.stderr)
        return 2

    result = audit_all(max_pages=args.max_pages)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = result["observed"]
    json_path = out_dir / f"public-page-audit-{stamp}.json"
    md_path = out_dir / f"public-page-audit-{stamp}.md"

    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_report(result), encoding="utf-8")

    # A stable "latest" pointer, so a reader does not have to know the date.
    (out_dir / "public-page-audit-latest.md").write_text(render_report(result), encoding="utf-8")
    (out_dir / "public-page-audit-latest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"audited {result['audited']['pages']} pages")
    print(f"contradictions: {len(result['findings'])}")
    for name, urls in result["issues"].items():
        if urls:
            print(f"  {name}: {len(urls)}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
