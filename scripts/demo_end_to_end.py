#!/usr/bin/env python3
"""End-to-end demonstration of the WiseQ Hermes operations replica.

Runs the full operating model against the client's real master data and
prints a report.  Nothing is sent anywhere except the test mailbox.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiseq.config import get_settings                            # noqa: E402
from wiseq.db.db import Database                                  # noqa: E402
from wiseq.orchestrator import WiseQOrchestrator                 # noqa: E402
from wiseq.seed import INBOUND_EMAILS, seed_all                  # noqa: E402

REPO = Path(sys.argv[1] if len(sys.argv) > 1
            else ROOT.parent / "wiseq-repo")

# Honour WISEQ_DATABASE_URL so the same demo runs against SQLite and against
# PostgreSQL/Supabase.  Without this the demo would silently prove nothing
# about the production backend.
DSN = os.getenv("WISEQ_DATABASE_URL") or os.getenv("WISEQ_DB_URL") or "sqlite:///./wiseq.db"
DB_PATH = None if DSN.startswith("postgres") else Path(DSN.replace("sqlite:///", ""))


def rule(title=""):
    print()
    print("=" * 74)
    if title:
        print(title)
        print("=" * 74)


def main() -> int:
    if not REPO.exists():
        print(f"ERROR: client repo data not found at {REPO}")
        return 1

    if DB_PATH is not None and DB_PATH.exists():
        DB_PATH.unlink()
    db = Database(DSN)
    orch = WiseQOrchestrator(db, repo=REPO,
                             discount_pct=get_settings().school_discount_pct)

    rule("STEP 1 - INGEST the client's real master data")
    loaded = orch.ingest()
    for key, value in loaded.items():
        print(f"  {key:<18} {value}")

    rule("STEP 2 - SEED synthetic operational history")
    seeded = seed_all(db)
    for key, value in seeded.items():
        print(f"  {key:<18} {value}")

    rule("STEP 3 - BUNDLE SPINE INTEGRITY (114 components -> 25 bundles)")
    spine = orch.bundle_agent().verify_spine()
    print(f"  bundles checked : {spine['bundles']}")
    print(f"  fully resolved  : {spine['resolved']}")
    print(f"  broken          : {len(spine['broken'])}")
    for b in spine["broken"]:
        print(f"     ! {b['bundle']} missing {b['missing']}")

    rule("STEP 4 - INBOUND SCHOOL EMAIL -> ORDER")
    agent = orch.school_order_agent()
    order = agent.handle_email(INBOUND_EMAILS[0])
    print(f"  order number    : {order.order_number}")
    print(f"  status          : {order.status.value}")
    print(f"  subtotal        : EUR {order.subtotal_eur:.2f}")
    _settings = get_settings()
    if order.discount_pct:
        _dlabel = f"{order.discount_pct}%  (- EUR {order.discount_eur:.2f})"
    elif _settings.school_discount_is_placeholder:
        _dlabel = "0%  -- PLACEHOLDER, NOT A WISEQ RULE"
    else:
        _dlabel = "0%  (no discount configured)"
    print(f"  school discount : {_dlabel}")
    print(f"  shipping        : EUR {order.shipping_eur:.2f}")
    print(f"  total           : EUR {order.total_eur:.2f}")
    print(f"  fully framed    : {order.is_framed}")
    print("  lines:")
    for line in order.lines:
        print(f"    - {line.sku:<6} x{line.quantity:<3} {line.title[:46]:<46} "
              f"{line.framing_status.value:<20} {line.carrier or '-':<7} "
              f"EUR {line.shipping_eur:.2f}")
        if line.framing_reason:
            print(f"      reason: {line.framing_reason}")

    rule("STEP 5 - OFFER DRAFT (approval-gated)")
    offer = agent.build_offer(order.order_number)
    print(f"  offer number    : {offer['offer_number']}")
    print(f"  total           : EUR {offer['total_eur']:.2f}")
    print(f"  warranty        : {offer['warranty_years']} years")
    print(f"  human send      : {offer['requires_human_send']}")
    for line in offer["lines"]:
        print(f"    - {line['sku']:<6} x{line['quantity']:<3} "
              f"EUR {line['line_total_eur']:.2f}  [{line['framing_status']}]")

    rule("STEP 6 - BUNDLE ASSEMBLY CHECK ('bijmaken' failure mode)")
    assembly = orch.bundle_agent().detect_assembly(order.order_number)
    print(f"  assembly required: {len(assembly['assembly_required'])}")
    for finding in assembly["assembly_required"]:
        print(f"    ! {finding['line']}: {finding['shortages']}")

    rule("STEP 7 - PURCHASE INTELLIGENCE (6-month rolling average)")
    intel = orch.purchase_agent().compute()
    print(f"  SKUs analysed   : {intel['skus']} over {intel['window_days']} days")
    print("  replenishment suggestions:")
    for row in orch.purchase_agent().replenishment_suggestions(limit=8):
        print(f"    - {row['sku']:<6} avg6m={row['avg_qty_6m']:<7} "
              f"stock={row['stock_qty']:<5} suggest={row['suggested_qty']:<5} "
              f"bracket={row['price_bracket']}")

    rule("STEP 8 - REVIEW DRAFTS (Dutch, human sends)")
    reviews = orch.review_agent()
    reviews.schedule(order.order_number)
    drafts = reviews.draft_due()
    for d in drafts:
        print(f"  channel    : {d['channel']}")
        print(f"  reference  : {d['order_number']}  ->  {d['to']}")
        print(f"  human send : {d['requires_human_send']}")
        print("  body:")
        for line in d["body"].splitlines():
            print(f"    | {line}")

    rule("STEP 9 - ASSORTMENT CONTENT MONITOR (bol.com listings)")
    scan = orch.assortment_agent().scan()
    print(f"  listings online : {scan['listings']}")
    print(f"  with issues     : {scan['issues']}")
    print("  worst offenders:")
    for issue in scan["worst"][:6]:
        print(f"    - {issue['listing_id']} ({issue['account']})")
        for problem in issue["problems"]:
            print(f"        * {problem}")
    print("  segment scores:")
    for seg in orch.assortment_agent().segment_scores():
        print(f"    - {seg['account']:<22} keyword={seg['keyword']:<6} "
              f"content={seg['content']:<6} n={seg['n']}")

    rule("STEP 10 - APPROVAL QUEUE (human gate)")
    pending = db.query(
        "SELECT agent_name, action_type, risk, status FROM approvals "
        "WHERE status='pending' ORDER BY requested_at")
    print(f"  pending approvals: {len(pending)}")
    for row in pending:
        print(f"    - [{row['risk']:<6}] {row['agent_name']:<22} {row['action_type']}")

    rule("STEP 11 - AUDIT TRAIL")
    total = db.scalar("SELECT COUNT(*) FROM audit_log")
    print(f"  audit entries: {total}")
    for row in db.query("SELECT actor, action, requires_human FROM audit_log "
                        "ORDER BY created_at LIMIT 12"):
        flag = "  [needs human]" if row["requires_human"] else ""
        print(f"    - {row['actor']:<22} {row['action']}{flag}")

    rule("FINAL METRICS")
    for key, value in orch.metrics().items():
        print(f"  {key:<38} {value}")

    db.close()
    print()
    print("Database backend:", DSN.split("@")[-1] if "@" in DSN else DSN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())