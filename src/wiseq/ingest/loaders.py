"""Load the client's own master data into the operations database.

Every table is populated from a file that WiseQ actually uses, not from
invented fixtures:

  wiseq-bundle-spine.csv     25 bundles, decomposed into 114 components
  wiseq-component-registry.csv  114 component SKUs + titles
  mastersheet/verzendregels-templates.csv  15 shipping-rule templates
  mastersheet/verzendtarieven.csv         carrier/size/country tariffs
  mastersheet/zoekvolume-google-filtered.csv  SEO search volume
  mastersheet/bestelformulier-dozen.csv   packaging (MyParcel) reference

The loader is idempotent: re-running it upserts instead of duplicating, which
matters because the eventual production import is Rob's real export.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from ..db.db import Database, new_id
from ..domain.models import Carrier, ShippingRule, Tariff, ValidationStatus

WISDOM_REPO = "Ai-Whisperers/wiseq-ai-onboarding"


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _num(value: str | None) -> float | None:
    v = _clean(value).replace("€", "").replace(",", ".").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ----------------------------------------------------------------------
# components
# ----------------------------------------------------------------------
def load_components(db: Database, repo: Path) -> int:
    rows = _read_csv(repo / "data" / "wiseq-component-registry.csv")
    payload = []
    for row in rows:
        sku = _clean(row.get("component_sku"))
        title = _clean(row.get("title"))
        if not sku or not title:
            continue
        payload.append((new_id(), sku, title, "component"))
    db.executemany(
        """INSERT INTO components (component_sku, sku_text, title, product_type)
           VALUES (?,?,?,?)
           ON CONFLICT(sku_text) DO UPDATE SET title=excluded.title""",
        payload)
    return len(payload)


# ----------------------------------------------------------------------
# bundles
# ----------------------------------------------------------------------
def _bundle_components(row: dict) -> list[str]:
    """Bundle rows list component_1..3 plus a verbose 'component_N=title' block."""
    parts = []
    for key in ("component_1", "component_2", "component_3"):
        v = _clean(row.get(key))
        if v:
            parts.append(v)
    # fall back to the verbose annotation column
    verbose = _clean(row.get("components_resolved"))
    if not parts and verbose:
        parts = re.findall(r"(?:^|;\s*)(\d+)\s*=", verbose)
    return parts


def load_bundles(db: Database, repo: Path) -> int:
    rows = _read_csv(repo / "data" / "wiseq-bundle-spine.csv")
    payload = []
    for row in rows:
        sku_raw = _clean(row.get("bundle_sku"))
        title = _clean(row.get("bundle_title"))
        if not sku_raw or not title:
            continue
        # normalise "117 + 240" -> "117+240" so it is a stable key
        bundle_sku = re.sub(r"\s*\+\s*", "+", sku_raw)
        components = _bundle_components(row)
        needs_fix = _clean(row.get("needs_format_fix")).upper() == "YES"
        payload.append((bundle_sku, bundle_sku, title, json.dumps(components),
                        1 if needs_fix else 0))
    db.executemany(
        """INSERT INTO bundles (bundle_key, bundle_sku, title, component_skus, needs_format_fix)
           VALUES (?,?,?,?,?)
           ON CONFLICT(bundle_key) DO UPDATE SET
             title=excluded.title,
             component_skus=excluded.component_skus,
             needs_format_fix=excluded.needs_format_fix""",
        payload)
    return len(payload)


# ----------------------------------------------------------------------
# products (components + bundles) + EAN registry
# ----------------------------------------------------------------------
# Reference EANs for a subset of components, taken from the client's own
# shipping-rule template notes ("Vergelijkbaar met 207 is EAN: ...").
EAN_HINTS: dict[str, str] = {
    "207": "8720254493077",   # light cables
    "215": "8720618246615",   # heavy cables
    "208": "8720618849403",   # 2x cable
    "101": "8720165910113",   # adapters < 50g
    "106": "8720618246110",   # adapters > 50g
    "310": "8720254493947",   # oplaadcombinatie
    "231": "8720254493619",   # MagSafe
    "331": "8720618246677",   # MagSafe combinatie
    "unbreakable": "8720618849083",
}


def _component_ean(sku: str) -> str | None:
    return EAN_HINTS.get(sku)


def load_products(db: Database, repo: Path) -> dict[str, int]:
    components = db.query("SELECT sku_text, title FROM components")
    bundles = db.query("SELECT bundle_sku, title FROM bundles")

    price = 0.0
    prod_rows, ean_rows = [], []
    for c in components:
        sku = c["sku_text"]
        ean = _component_ean(sku)
        prod_rows.append((new_id(), sku, c["title"], "component", ean,
                           1 if ean else 0, price, 0, "component"))
        ean_rows.append((sku, ean, "registered" if ean else "missing",
                         None, "mastersheet-ean-hints"))
    for b in bundles:
        sku = b["bundle_sku"]
        ean = None
        prod_rows.append((new_id(), sku, b["title"], "bundle", ean, 0,
                           price, 0, "bundle"))
        ean_rows.append((sku, ean, "missing", None, "bundle-no-ean"))

    db.executemany(
        """INSERT INTO products (sku, sku_text, title, product_type, ean, has_ean,
                                 price_eur, weight_gram, category)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(sku_text) DO UPDATE SET
             title=excluded.title, ean=COALESCE(excluded.ean, products.ean),
             has_ean=excluded.has_ean""", prod_rows)
    db.executemany(
        """INSERT INTO ean_registry (sku, ean, status, gs1_reference, source)
           VALUES (?,?,?,?,?)
           ON CONFLICT(sku) DO UPDATE SET
             ean=COALESCE(excluded.ean, ean_registry.ean),
             status=excluded.status, source=excluded.source""", ean_rows)
    return {"components": len(components), "bundles": len(bundles),
            "products": len(prod_rows)}


# ----------------------------------------------------------------------
# shipping rules
# ----------------------------------------------------------------------
def load_shipping_rules(db: Database, repo: Path) -> int:
    rows = _read_csv(repo / "data" / "client" / "mastersheet" /
                      "verzendregels-templates.csv")
    payload = []
    for row in rows:
        category = _clean(row.get("category"))
        if not category:
            continue
        status_raw = _clean(row.get("validation_status")).upper() or "NEEDS_CONFIRMATION"
        try:
            status = ValidationStatus(status_raw)
        except ValueError:
            status = ValidationStatus.NEEDS_CONFIRMATION
        payload.append((
            category.upper().replace(" ", "_"),
            category,
            _clean(row.get("clone_note")),
            _clean(row.get("template_ean")) or None,
            _clean(row.get("notes")) or None,
            status.value,
            _clean(row.get("source_effective")),
        ))
    db.executemany(
        """INSERT INTO shipping_rules (rule_key, category, clone_note, template_ean,
                                      notes, validation_status, source_effective)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(rule_key) DO UPDATE SET
             clone_note=excluded.clone_note, template_ean=excluded.template_ean,
             notes=excluded.notes, validation_status=excluded.validation_status""",
        payload)
    return len(payload)


# ----------------------------------------------------------------------
# shipping tariffs
# ----------------------------------------------------------------------
# weight bands from the client tariff sheet
_WEIGHT_BANDS = [
    ("Partijenpost onder 50 gram", "<50g"),
    ("Partijenpost 50-100 gram", "50-100g"),
    ("Partijenpost 100-200 gram", "100-200g"),
    ("Partijenpost 200-350 gram", "200-350g"),
    ("Brievenbus doosjes", "brievenbus"),
    ("Brievenbus envelop", "envelop"),
    ("Pakket", "pakket"),
    ("Europlus Pakket", "europlus"),
]


LVB_SIZE_CLASSES = {"3XS", "2XS", "XS", "S", "M"}


def load_shipping_tariffs(db: Database, repo: Path) -> int:
    """Load the client tariff sheet.

    The sheet has two different layouts and that distinction matters:

    * **LVB rows** -- ``Type`` is a *size class* (3XS, 2XS, XS, S, M) and
      ``Artikelsoort`` names the article family (Opladers, Magsafes,
      Draadloze oortjes, Unbreakable/Hero/Junior/Kids ANC, BT Wireless /
      Hardcase).  The shipment method is LVB itself.
    * **VVB / QLS / PostNL rows** -- ``Type`` is the *shipment type*
      (Brievenbus doosjes, Pakket NL, Partijenpost 50-100 gram, ...) and
      ``Artikelsoort`` is the article kind.

    Rows carrying a ``Kosten BE`` column are expanded into a Belgium-specific
    row, because the BE surcharge is the rule the client actually applies.
    """
    path = repo / "data" / "client" / "mastersheet" / "verzendtarieven.csv"
    rows = _read_csv(path)
    payload = []
    for row in rows:
        if not row:
            continue
        carrier_raw = _clean(next(iter(row.values())))     # carrier, unnamed column
        type_col = _clean(row.get("Type"))
        article_kind = _clean(row.get("Artikelsoort"))
        if not carrier_raw or not type_col:
            continue
        carrier_map = {"LVB": Carrier.LVB, "VVB": Carrier.VVB,
                       "QLS": Carrier.QLS, "PostNL": Carrier.POSTNL}
        carrier = carrier_map.get(carrier_raw)
        if carrier is None:
            continue

        if type_col in LVB_SIZE_CLASSES:
            shipment_type = "LVB"
            size_class = type_col
        else:
            shipment_type = type_col
            size_class = None

        countries: list[str] = []
        land = _clean(row.get("Land")).upper()
        if land:
            countries = [c.strip() for c in land.split("/") if c.strip()]
        if not countries:
            countries = ["NL"]
        be_cost = _num(row.get("Kosten BE"))
        if "BE" not in countries and be_cost is not None:
            countries.append("BE")

        nl_cost = _num(row.get("Kosten NL"))
        discount = _num(row.get("20%Discount"))
        storage = _num(row.get("LVB opslagkosten"))
        notes = _clean(row.get("GoodsGoods")) or None

        for country in countries:
            cost = be_cost if country == "BE" else nl_cost
            if cost is None:
                cost = nl_cost if country == "NL" else be_cost
            weight_band = None
            for needle, band in _WEIGHT_BANDS:
                if needle.lower() in shipment_type.lower():
                    weight_band = band
                    break
            key = f"{carrier.value}:{shipment_type}:{size_class or 'na'}:{country}:{article_kind or 'na'}"
            payload.append((key, carrier.value, shipment_type, size_class,
                            article_kind or None, country, weight_band, cost,
                            discount, storage, notes))

    db.executemany(
        """INSERT INTO shipping_tariffs (tariff_key, carrier, shipment_type, size_class,
                                        article_kind, country, weight_band, cost_eur,
                                        discount_eur, lvb_storage_eur, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(tariff_key) DO UPDATE SET cost_eur=excluded.cost_eur""",
        payload)
    return len(payload)


# ----------------------------------------------------------------------
# SEO / search volume
# ----------------------------------------------------------------------
def load_search_volume(db: Database, repo: Path) -> int:
    """Load the client's Google search-volume sheet into ``search_keywords``.

    This is SEO keyword data, kept out of ``assortment`` on purpose: the
    assortment table describes *listings* (bol.com content quality), while
    this describes *search demand*.  Mixing them would corrupt the
    assortment content-quality scan.
    """
    path = repo / "data" / "client" / "mastersheet" / "zoekvolume-google-filtered.csv"
    rows = _read_csv(path)
    payload = []
    for row in rows:
        if not row:
            continue
        values = list(row.values())
        keyword = _clean(values[0] if values else "")
        if not keyword:
            continue
        volume = _num(values[1]) if len(values) > 1 else 0.0
        intent = _clean(values[2]) if len(values) > 2 else None
        position = int(values[3]) if len(values) > 3 and _clean(values[3]).isdigit() else None
        cpc = _num(values[4]) if len(values) > 4 else None
        competition = _num(values[5]) if len(values) > 5 else None
        payload.append((keyword, volume or 0.0, intent, position, cpc, competition))
    db.executemany(
        """INSERT INTO search_keywords (keyword, volume, intent, position, cpc, competition)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(keyword) DO UPDATE SET
             volume=excluded.volume, intent=excluded.intent""",
        payload)
    return len(payload)


def load_all(db: Database, repo: Path) -> dict[str, int]:
    """Load every master-data source. Idempotent."""
    repo = Path(repo)
    db.init_schema()
    return {
        "components": load_components(db, repo),
        "bundles": load_bundles(db, repo),
        "products": load_products(db, repo),
        "shipping_rules": load_shipping_rules(db, repo),
        "shipping_tariffs": load_shipping_tariffs(db, repo),
        "search_volume": load_search_volume(db, repo),
    }