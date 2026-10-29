"""Live Shopify catalogue sync for the WiseQ store.

Why this exists
---------------
The client repository ships *master data* (114 components, 25 bundles, shipping
rules, tariffs) but no sell prices -- those live in FiveX / Mastersheet.xlsx.
The prices are, however, published on the live Shopify storefront at
``https://www.wiseq.nl/products.json``, which is the same source of truth that
drives the bol.com and web catalogues.

This module turns that public endpoint into a repeatable, deterministic
import:

* ``sync_shopify`` pulls the catalogue, maps every variant onto the
  repository's *business SKU* (the numeric ``component_sku`` such as ``231``),
  and writes the sell price.
* Variants that do not map to a registry SKU are reported separately as
  ``not_in_catalogue`` -- they are never silently dropped and never written
  with a zero price.
* Product-type, tags, weight and availability are captured so that the
  shipping rules can be evaluated against real data instead of guesses.

It deliberately performs **no authentication** and **no writes to the live
store**.  It is a read-only mirror of public information, so it needs no
credentials and cannot damage anything.

Nothing here invents a price.  A variant with a missing or zero price is
reported as ``unresolved``, exactly like every other price source.
"""
from __future__ import annotations

import csv
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STORE = "https://www.wiseq.nl"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# Products that must never be treated as sellable retail stock.
NON_SELLABLE_TAGS = {"intern", "niet-los-bestelbaar"}
SAMPLE_TAG = "sample"


@dataclass
class ShopifyVariant:
    """One sellable variant of one Shopify product."""

    sku: str
    title: str
    handle: str
    price: float
    product_type: str
    tags: list[str] = field(default_factory=list)
    available: bool = True
    grams: int = 0
    compare_at_price: float | None = None

    @property
    def business_sku(self) -> str:
        """The numeric component SKU, e.g. ``231`` from ``231.White``.

        WiseQ encodes the business SKU as the prefix of the Shopify SKU
        separated by a dot (``231.White``, ``Tab.Hoes.Groen10.2``).  For
        purely numeric SKUs the prefix is the SKU itself.
        """
        return self.sku.split(".")[0].strip()

    @property
    def is_sample(self) -> bool:
        return SAMPLE_TAG in {t.strip().lower() for t in self.tags}

    @property
    def is_non_sellable(self) -> bool:
        low = {t.strip().lower() for t in self.tags}
        return bool(low & NON_SELLABLE_TAGS)


class ShopifySyncError(RuntimeError):
    """Raised when the storefront cannot be read."""


def _normalise_bundle_sku(value: str) -> str:
    """Normalise a bundle SKU so ``111 + 216`` == ``111+216``.

    The live storefront and the repository disagree about whitespace around
    the ``+`` separator, so every comparison goes through this.
    """
    return re.sub(r"\s*\+\s*", "+", str(value or "").strip())


def _sku_known(business_sku: str, raw_sku: str, normalised_known: set[str]) -> bool:
    """True when either the raw or the business SKU is in the catalogue."""
    return (
        business_sku in normalised_known
        or _normalise_bundle_sku(raw_sku) in normalised_known
    )


def _http_get(url: str, timeout: int = 45) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "application/json,text/html;q=0.9",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        },
    )
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:  # pragma: no cover
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise ShopifySyncError(f"could not read {url}: {last}")


def fetch_shopify_products(
    store: str = DEFAULT_STORE,
    limit: int = 250,
    max_pages: int = 12,
) -> list[dict]:
    """Return the raw product list from a Shopify storefront.

    Shopify exposes ``/products.json`` publicly for most stores.  Pagination
    stops at the first short page, so the total request count is bounded by
    the catalogue size rather than ``max_pages``.
    """
    store = store.rstrip("/")
    products: list[dict] = []
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        url = f"{store}/products.json?limit={limit}&page={page}"
        payload = json.loads(_http_get(url).decode("utf-8", "replace"))
        batch = payload.get("products", []) or []
        if not batch:
            break
        fresh = [p for p in batch if p.get("id") not in seen]
        for product in fresh:
            seen.add(product["id"])
        products.extend(fresh)
        if len(batch) < limit:
            break
    return products


def parse_shopify_products(raw: list[dict]) -> tuple[list[ShopifyVariant], list[dict]]:
    """Flatten a Shopify product list into (variants, non-sellable rules).

    ``variants`` holds every variant that carries a SKU and is therefore a
    catalogue candidate.  ``rules`` holds the internal order lines -- the
    EUR 0 school rule and the B2B administration/shipping surcharge -- which
    are *not* products but are real business rules that the order pipeline
    must honour.  They are returned rather than dropped, because a rule that
    silently disappears is a rule that silently stops being charged.
    """
    variants: list[ShopifyVariant] = []
    rules: list[dict] = []
    for product in raw:
        product_type = (product.get("product_type") or "").strip()
        tags = [t.strip() for t in (product.get("tags") or []) if t.strip()]
        low = {t.strip().lower() for t in tags}
        for variant in product.get("variants") or []:
            sku = (variant.get("sku") or "").strip()
            try:
                price = float(variant.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            if not sku or low & NON_SELLABLE_TAGS:
                # An internal order rule, not a product.  The EUR 0 school
                # line, the B2B surcharge and anything tagged as not
                # separately orderable live here.  They are returned rather
                # than dropped, because a rule that silently disappears is a
                # rule that silently stops being charged.
                rules.append(
                    {
                        "sku": sku,
                        "title": (product.get("title") or "").strip(),
                        "product_type": product_type,
                        "tags": tags,
                        "price_eur": price,
                        "is_b2b_surcharge": "b2b-toeslag" in low,
                        "is_school_rule": "schoolbestelling" in low,
                        "is_non_sellable": bool(low & NON_SELLABLE_TAGS),
                    }
                )
                continue
            variants.append(
                ShopifyVariant(
                    sku=sku,
                    title=(product.get("title") or "").strip(),
                    handle=product.get("handle") or "",
                    price=price,
                    product_type=product_type,
                    tags=tags,
                    available=bool(variant.get("available", True)),
                    grams=int(variant.get("grams") or 0),
                    compare_at_price=float(variant["compare_at_price"])
                    if variant.get("compare_at_price")
                    else None,
                )
            )
    return variants, rules


def build_price_rows(
    variants: list[ShopifyVariant],
    known_skus: set[str] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split variants into (priced rows, unresolved rows, unknown rows).

    ``priced`` rows use the same shape the generic CSV price importer accepts,
    so a live sync and a FiveX export are interchangeable.

    ``known_skus`` may contain both component SKUs (numeric, e.g. ``231``) and
    bundle SKUs (e.g. ``111 + 216``).  Bundle SKUs are matched after
    normalising whitespace around the ``+`` separator, because the live
    storefront and the repository disagree about spacing.
    """
    priced: list[dict] = []
    unresolved: list[dict] = []
    unknown: list[dict] = []
    normalised_known = {_normalise_bundle_sku(s) for s in known_skus} if known_skus else None

    for variant in variants:
        business_sku = variant.business_sku
        row = {
            "sku_text": business_sku,
            "price_eur": variant.price,
            "live_title": variant.title,
            "shopify_sku": variant.sku,
            "product_type": variant.product_type,
            "tags": ",".join(variant.tags),
            "available": variant.available,
            "grams": variant.grams,
            "source": "wiseq.nl/products.json",
        }
        if variant.is_sample:
            row["is_sample"] = True
        if normalised_known is not None and not _sku_known(
            business_sku, variant.sku, normalised_known
        ):
            unknown.append(row)
            continue
        if variant.price <= 0:
            unresolved.append(row)
            continue
        priced.append(row)
    return priced, unresolved, unknown


def write_price_csv(rows: list[dict], path: str | Path) -> Path:
    """Write priced rows to a CSV the standard price importer can consume."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "sku_text",
        "price_eur",
        "live_title",
        "shopify_sku",
        "product_type",
        "tags",
        "available",
        "grams",
        "source",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["price_eur"] = f"{float(out['price_eur']):.2f}"
            writer.writerow(out)
    return path


def sync_shopify(
    db=None,
    store: str = DEFAULT_STORE,
    registry: str | Path | None = None,
    csv_out: str | Path | None = None,
    load_into_db: bool = True,
) -> dict:
    """Mirror the live storefront and (optionally) load the prices.

    Returns a report describing exactly what was observed, what was priced,
    what could not be priced and what could not be matched to the catalogue.
    """
    raw = fetch_shopify_products(store)
    variants, rules = parse_shopify_products(raw)

    known_skus: set[str] | None = None
    if registry and Path(registry).exists():
        with Path(registry).open(newline="", encoding="utf-8") as handle:
            known_skus = {
                str(row.get("component_sku") or "").strip()
                for row in csv.DictReader(handle)
                if str(row.get("component_sku") or "").strip()
            }

    # The repository describes bundles in a separate file; their SKUs are
    # sellable on the storefront too, so they must be recognised.
    if registry:
        spine = Path(registry).parent / "wiseq-bundle-spine.csv"
        if spine.exists():
            with spine.open(newline="", encoding="utf-8") as handle:
                known_skus = (known_skus or set()) | {
                    str(row.get("bundle_sku") or "").strip()
                    for row in csv.DictReader(handle)
                    if str(row.get("bundle_sku") or "").strip()
                }

    priced, unresolved, unknown = build_price_rows(variants, known_skus)
    samples = [v for v in variants if v.is_sample]

    written = None
    if csv_out:
        written = str(write_price_csv(priced, csv_out))

    loaded = None
    if db is not None and load_into_db and priced:
        from .prices import load_prices

        loaded = load_prices(db, priced, source_name=f"shopify:{store.rstrip('/')}")
        if isinstance(loaded, dict):
            loaded = loaded.get("as_dict", lambda: loaded)()

    rules_saved = None
    if db is not None and load_into_db and rules:
        rules_saved = _save_rules(db, rules)

    return {
        "store": store.rstrip("/"),
        "products_fetched": len(raw),
        "variants_seen": len(variants),
        "priced_rows": len(priced),
        "unresolved": unresolved,
        "not_in_catalogue": unknown,
        "samples_seen": [
            {"sku": v.sku, "title": v.title, "price": v.price} for v in samples
        ],
        "non_sellable_skipped": sum(1 for v in variants if v.is_non_sellable)
        + sum(1 for r in rules if r.get("is_non_sellable")),
        "order_rules": rules,
        "rules_saved": rules_saved,
        "csv_written": written,
        "loaded": loaded,
        "observed": time.strftime("%Y-%m-%d"),
    }


def _save_rules(db, rules: list[dict]) -> list[dict]:
    """Persist the storefront's internal order rules as shipping rules.

    The B2B surcharge (EUR 2.95 ex-VAT per business order, shown as EUR 3.57
    incl. VAT) is a real rule that the order pipeline has to be able to
    charge.  It is stored as a shipping rule so it is auditable and can be
    consulted by the school-order agent, not buried in a storefront tag.
    """
    saved: list[dict] = []
    for rule in rules:
        if not rule.get("is_b2b_surcharge"):
            continue
        eur = float(rule.get("price_eur") or 0)
        ex_vat = round(eur / 1.21, 2)
        try:
            db.execute(
                "INSERT INTO order_rules (rule_key, rule_type, description, "
                "amount_eur, applies_to, source, observed_at) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(rule_key) DO UPDATE SET amount_eur=excluded.amount_eur, "
                "description=excluded.description, source=excluded.source, "
                "observed_at=excluded.observed_at",
                (
                    "WISEQ-B2B-SURCHARGE",
                    "b2b_surcharge",
                    "Vaste bijdrage per zakelijke bestelling; "
                    f"storefront toont EUR {eur:.2f} incl. btw",
                    ex_vat,
                    "b2b_order",
                    "shopify:wiseq.nl",
                    time.strftime("%Y-%m-%d"),
                ),
            )
        except Exception as exc:  # pragma: no cover - schema differences
            saved.append({"rule": rule.get("title"), "error": str(exc)})
            continue
        saved.append(
            {
                "rule": rule.get("title"),
                "cost_eur_ex_vat": ex_vat,
                "cost_eur_incl_vat": eur,
                "status": "OK",
            }
        )
    return saved
