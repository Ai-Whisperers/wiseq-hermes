"""Run a resumable UCP catalogue scan against the live storefront.

The storefront's UCP/MCP endpoint rate-limits a full 139-SKU scan.  This
runner keeps a progress file, so a throttled run can be continued later
without re-fetching the SKUs it already resolved.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiseq.connectors.ucp import UCPClient, sync_ucp_catalog  # noqa: E402
from wiseq.db.db import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="Database URL (default: local sqlite)")
    parser.add_argument("--progress", default=None, help="Progress file path")
    parser.add_argument("--no-resume", action="store_true", help="Ignore any saved progress")
    parser.add_argument("--load", action="store_true", help="Write the prices into the database")
    parser.add_argument("--limit", type=int, default=0, help="Only scan the first N SKUs")
    args = parser.parse_args()

    db = Database(args.db or "sqlite:///./wiseq.db")
    client = UCPClient()

    # The UCP endpoint resolves BUSINESS SKUs (sku_text), not the internal
    # GUID in the ``sku`` column.  Passing the GUID resolves to nothing and
    # is indistinguishable from "product does not exist".
    skus = [str(p["sku_text"]) for p in db.query(
        "SELECT sku_text FROM products "
        "WHERE sku_text IS NOT NULL AND sku_text != '' ORDER BY sku_text"
    ) if p.get("sku_text")]

    if args.limit:
        skus = skus[: args.limit]

    print(f"scanning {len(skus)} SKUs (resume={not args.no_resume})", flush=True)

    report = sync_ucp_catalog(
        db=db,
        client=client,
        skus=skus,
        load_into_db=args.load,
        resume=not args.no_resume,
        progress_path=args.progress,
    )

    print(json.dumps(report, indent=2, default=str))
    if report.get("rate_limited"):
        print("\nRATE LIMITED -- rerun the same command later to continue where it stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
