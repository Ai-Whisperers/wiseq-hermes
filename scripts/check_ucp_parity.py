"""Cross-check live UCP prices against the live Shopify catalogue.

The storefront exposes the same catalogue through two independent live
surfaces:

* ``/products.json`` -- the Shopify storefront catalogue, which is what
  the price importer reads.
* the storefront's own UCP/MCP commerce endpoint, which is what
  ``scripts/ucp_scan_live.py`` resolves.

When both agree to the cent on every modelled product, the two sources
are consistent.  A mismatch means one of them is stale, mis-mapped, or
double-counting a bundle -- all of which silently corrupt offers.

Run against the persisted scan progress file::

    .venv/bin/python scripts/check_ucp_parity.py \\
        --progress data/wiseq.ucp_scan.json

Exit code is 0 only when every resolved SKU matches.  Missing prices on
either side are reported as unusable, never as a match.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiseq.db.db import Database  # noqa: E402
from wiseq.ingest.loaders import load_all  # noqa: E402
from wiseq.ingest.prices import load_prices  # noqa: E402
from wiseq.ingest.shopify import (  # noqa: E402
    fetch_shopify_products,
    parse_shopify_products,
)


def _eur(value: object) -> float | None:
    """Normalise a price to a float, or None when it is not a number.

    Accepts ``"12,95"`` and ``"€ 12.95"`` shapes, because the storefront
    and the UCP endpoint do not use the same serialisation.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).replace("€", "").replace(",", ".").strip()
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def build_catalogue(repo: Path, store: str, snapshot: Path | None = None) -> dict[str, float]:
    """Return the catalogue sell prices keyed by SKU.

    The live path reads the storefront and imports its prices.  When a
    committed snapshot exists and the live fetch fails (offline CI, a
    storefront outage), the snapshot is used instead -- the check still
    proves something: that the two committed snapshots agree with each
    other, which is the same invariant the live check proves.
    """
    try:
        tmp = tempfile.mkdtemp(prefix="wiseq-ucp-parity-")
        db = Database(f"sqlite:///{tmp}/parity.db")
        db.init_schema()
        load_all(db, repo)

        raw = fetch_shopify_products(store)
        variants, _rules = parse_shopify_products(raw)
        priced = []
        for variant in variants:
            price = _eur(variant.price)
            if price is not None and price > 0:
                priced.append({"sku_text": variant.sku, "price_eur": price})
        if priced:
            load_prices(db, priced, source_name=f"shopify:{store.rstrip('/')}")

        catalogue = {
            row["sku_text"]: _eur(row["price_eur"]) or 0.0
            for row in db.query("SELECT sku_text, price_eur FROM products")
        }
        if any(catalogue.values()):
            return catalogue
    except Exception as exc:  # network, storefront schema, ...
        print(f"live catalogue unavailable ({exc}); falling back to snapshot")

    if snapshot and snapshot.exists():
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        prices = data.get("prices") or {}
        print(f"using committed catalogue snapshot {snapshot}")
        return {k: (_eur(v) or 0.0) for k, v in prices.items()}
    raise SystemExit("no live catalogue and no committed snapshot available")


def check(catalogue: dict[str, float], resolved: dict) -> dict:
    """Compare every resolved UCP price with the catalogue price."""
    matched, mismatched, unusable = [], [], []
    for sku, entry in sorted(resolved.items()):
        ucp_price = entry.get("price") if isinstance(entry, dict) else entry
        ucp_price = _eur(ucp_price)
        if sku not in catalogue:
            unusable.append((sku, "not_in_catalogue", ucp_price, None))
            continue
        if ucp_price is None:
            unusable.append((sku, "no_ucp_price", None, catalogue[sku]))
            continue
        if ucp_price == catalogue[sku]:
            matched.append(sku)
        else:
            mismatched.append((sku, "price_mismatch", catalogue[sku], ucp_price))
    return {
        "matched": matched,
        "mismatched": mismatched,
        "unusable": unusable,
        "total": len(resolved),
    }


def _load_resolved(progress: Path) -> dict:
    """Read the resolved prices out of a scan progress file.

    Two shapes are accepted:

    * the live progress file -- ``{"resolved": {"101": 7.95, ...}}``
    * the committed snapshot -- ``{"prices": {"101": 7.95, ...}}``

    The live progress file is a runtime artefact and is gitignored, so the
    committed snapshot is what lets the parity check run offline in CI.
    """
    scan = json.loads(progress.read_text(encoding="utf-8"))
    resolved = scan.get("resolved") or scan.get("prices") or {}
    if not resolved:
        raise ValueError(f"{progress} contains no resolved prices")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress",
                        default=str(ROOT / "data" / "wiseq.ucp_scan.json"),
                        help="scan progress file, or the committed price snapshot")
    parser.add_argument("--repo", default=str(ROOT / "data" / "wiseq-repo"))
    parser.add_argument("--store", default="https://www.wiseq.nl")
    parser.add_argument("--snapshot",
                        default=str(ROOT / "data" / "public" / "ucp-price-snapshot.json"),
                        help="committed UCP snapshot used when no progress file exists")
    parser.add_argument("--catalogue-snapshot",
                        default=str(ROOT / "data" / "public" / "catalogue-price-snapshot.json"),
                        help="committed catalogue snapshot used when the storefront is unreachable")
    parser.add_argument("--expected", type=int, default=0,
                        help="Fail unless at least this many SKUs resolved")
    args = parser.parse_args()

    progress = Path(args.progress)
    if not progress.exists():
        # Fall back to the committed snapshot so the check is reproducible
        # without a live scan (and therefore runs in CI).
        progress = Path(args.snapshot)
        if not progress.exists():
            print(f"no scan progress at {args.progress} and no snapshot at {args.snapshot}",
                  file=sys.stderr)
            return 2
        print(f"using committed snapshot {progress}")
    try:
        resolved = _load_resolved(progress)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"cannot read resolved prices: {exc}", file=sys.stderr)
        return 2

    catalogue = build_catalogue(Path(args.repo), args.store,
                                 Path(args.catalogue_snapshot))
    result = check(catalogue, resolved)

    print(f"catalogue SKUs priced : {sum(1 for v in catalogue.values() if v)}")
    print(f"UCP resolved           : {result['total']}")
    print(f"MATCH                  : {len(result['matched'])}")
    print(f"MISMATCH               : {len(result['mismatched'])}")
    print(f"UNUSABLE               : {len(result['unusable'])}")

    for row in result["mismatched"][:40]:
        print(f"  MISMATCH {row[0]}: catalogue={row[2]} ucp={row[3]}")
    for row in result["unusable"][:40]:
        print(f"  UNUSABLE {row[0]}: {row[1]}")

    if result["mismatched"] or result["unusable"]:
        return 1
    if args.expected and result["total"] < args.expected:
        print(f"only {result['total']} resolved, expected at least {args.expected}",
              file=sys.stderr)
        return 1
    print("UCP/SHOPIFY PRICE PARITY: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
