"""Build a trimmed, committable public-site audit snapshot.

Why
---
``scripts/audit_public_site.py`` captures a snapshot of the storefront.
The ``raw_catalogue`` section of the raw capture is the full Shopify
payload: ~1 MB, almost all of it fields nothing reads (images,
descriptions, SEO blocks, option names, inventory depth).

The audit tests need a snapshot so the parsing logic stays pinned
without hitting the network.  Without one they skip, which means a
delivery archive silently loses 8 checks.

This script writes a snapshot whose ``raw_catalogue`` is reduced to the
fields ``analyse_catalogue`` actually reads.  The audit's output is
identical before and after the trim -- that is asserted by
``tests/test_public_site_audit.py``.

Usage
-----
    python scripts/build_public_snapshot.py --out data/public
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
AUDIT_SCRIPT = SCRIPT_DIR / "audit_public_site.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_public_site", AUDIT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(source: Path) -> dict:
    """Return the snapshot with raw_catalogue trimmed."""
    audit = _load_audit_module()
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    raw = snapshot.get("raw_catalogue")
    if isinstance(raw, dict):
        snapshot["raw_catalogue"] = audit.trim_catalogue(raw)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default="data/public/public-site-audit-latest.json",
        help="the snapshot to read",
    )
    parser.add_argument(
        "--out",
        default="data/public",
        help="directory to write the trimmed snapshot into",
    )
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"no snapshot at {source} -- run scripts/audit_public_site.py first")
        return 1

    snapshot = build(source)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "public-site-audit-latest.json"

    before = source.stat().st_size
    target.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False), encoding="utf-8")
    after = target.stat().st_size

    print(f"wrote {target}")
    print(f"bytes: {before} -> {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
