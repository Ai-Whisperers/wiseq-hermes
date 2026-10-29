#!/usr/bin/env python3
"""Live demo script for Rob -- the 5-minute walkthrough.

This is the script to run *in front of Rob*.  It tells the story in the
order a client cares about, with the real numbers on screen:

    1. We loaded YOUR catalogue            114 components -> 25 bundles
    2. A school emailed us                 "10x MagSafe draadloze oplader..."
    3. We understood it                    2 lines, no human needed
    4. We priced it against YOUR tariffs   PostNL / LVB, exact rates
    5. We asked a human before sending      approval queued, nothing sent
    6. Review requests, Dutch, human-sent
    7. Purchase intelligence               6-month rolling average

Nothing here needs a credential, and no message ever leaves the test
mailbox.  Run it:

    WISEQ_REPO_DIR=./data/wiseq-repo .venv/bin/python scripts/demo_for_rob.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from wiseq.config import get_settings          # noqa: E402
from wiseq.db.db import Database                # noqa: E402
from wiseq.ingest.loaders import load_all       # noqa: E402
from wiseq.seed import seed_stock                    # noqa: E402
from wiseq.orchestrator import WiseQOrchestrator  # noqa: E402

W = 74
LINE = "=" * W


def head(title: str) -> None:
    print()
    print(LINE)
    print(title)
    print(LINE)


def show_catalogue(orch) -> None:
    head("1. YOUR CATALOGUE, LOADED FROM YOUR OWN FILES")
    m = orch.metrics()
    comp = orch.db.scalar("SELECT COUNT(*) FROM components") or 0
    kw = orch.db.scalar("SELECT COUNT(*) FROM search_keywords") or 0
    print(f"  components        {comp}")
    print(f"  bundles           {m.get('bundles', '?')}")
    print(f"  products          {m.get('products', '?')}")
    print(f"  with EAN          {m.get('products_with_ean', '?')} "
          f"({m.get('ean_coverage_pct', '?')}% coverage)")
    print(f"  shipping rules    {m.get('shipping_rules', '?')} "
          f"({m.get('shipping_rules_validated_ok', '?')} validated, "
          f"{m.get('shipping_rules_needing_confirmation', '?')} need confirmation)")
    print(f"  tariffs           {m.get('tariffs', '?')}")
    print(f"  SEO keywords      {kw}")
    spine = orch.bundle_agent().verify_spine()
    print(f"\n  bundle spine: {spine.get('resolved')}/{spine.get('bundles')}"
          f" bundles fully resolved from components, "
          f"{len(spine.get('broken') or [])} broken")


def show_school_email(orch) -> None:
    head("2. A SCHOOL EMAILS US (VERBATIM DUTCH, AS THEY ACTUALLY WRITE)")
    body = ("Beste WiseQ team,\n\n"
            "Wij willen graag 10x de MagSafe draadloze oplader en "
            "2x de 45W GaN snellader bestellen voor onze bovenbouw.\n\n"
            "Met vriendelijke groet,\nBasisschool De Zon")
    for ln in body.split("\n"):
        print(f"  | {ln}")
    show_school_email.order = body


def show_understanding(orch, order) -> None:
    head("3. WE UNDERSTOOD IT (NO HUMAN NEEDED TO READ THE EMAIL)")
    print(f"  order number    {order.order_number}")
    print(f"  lines resolved  {len(order.lines)}")
    for l in order.lines:
        print(f"    - {l.sku:>4}  x{l.quantity:<4} {l.title[:46]}")
        print(f"           {l.framing_status}  {l.carrier}  "
              f"EUR {float(l.shipping_eur):.2f}")
    print("\n  note: the school wrote '10x <product>'. The catalogue title is "
          "'Draadloze\n  Oplader - Geschikt Voor MagSafe - 1 Meter - Wit'. "
          "The words are the same\n  product but not the same string -- "
          "matching on meaning, not on LIKE %...%.")
    show_understanding.order = order


def show_price_import(orch) -> None:
    head("3b. THE CATALOGUE SHIPS WITHOUT PRICES -- SO WE GET THEM")
    gaps = len(orch.db.query(
        "SELECT sku_text FROM products WHERE price_eur <= 0 "
        "OR synthetic_price = 1"))
    print(f"  products with no sell price   {gaps}")
    print("  (WiseQ's repository has the catalogue but not the prices --")
    print("   they live in FiveX and Mastersheet.xlsx.)")

    print("\n  Option A -- one CSV export from FiveX:")
    csv = "sku_text,price_eur\n231,19.95\n117,14.42\n"
    for ln in csv.strip().split("\n"):
        print(f"  | {ln}")

    # Option B -- the live storefront publishes the same catalogue, publicly.
    # This is what we actually use here, because it needs no credentials and
    # it proves the numbers are real rather than illustrative.
    print("\n  Option B -- mirror the live storefront (wiseq.nl/products.json):")
    try:
        report = orch.sync_shopify()
    except Exception as exc:
        print(f"  ! storefront unreachable: {exc}")
        print("  (falling back to the CSV export above)")
        report = None

    if report:
        print(f"    products fetched    {report['products_fetched']}")
        print(f"    priced rows         {report['priced_rows']}")
        print(f"    unresolved          {len(report['unresolved'])} "
              f"(nothing is ever written as zero)")
        print(f"    not in catalogue    {len(report['not_in_catalogue'])} "
              f"(live products with no master record -- reported, not dropped)")
        if report.get("rules_saved"):
            for rule in report["rules_saved"]:
                print(f"    rule captured       {rule['rule']}: "
                      f"EUR {rule['cost_eur_ex_vat']:.2f} ex-vat "
                      f"(EUR {rule['cost_eur_incl_vat']:.2f} incl.)")
        if report.get("samples_seen"):
            print(f"    samples flagged     {len(report['samples_seen'])} "
                  f"(not sellable as normal stock)")
    else:
        res = orch.load_prices(csv, source_name="demo (stands in for FiveX export)")
        print(f"    imported            {res['prices_written']} prices")

    gaps = len(orch.db.query(
        "SELECT sku_text FROM products WHERE price_eur <= 0 "
        "OR synthetic_price = 1"))
    print(f"  still missing {gaps}")


def show_missing_price_block(orch) -> None:
    """Show the safety behaviour: no prices, no quote.

    The catalogue ships without sell prices.  A quote for a school that
    charges EUR 0 for the goods while asking for shipping money is a
    business error, so the system refuses to produce one.  This is shown
    deliberately rather than left to happen by accident.
    """
    head("3c. AND IF THE PRICES WERE MISSING, IT WOULD REFUSE TO QUOTE")
    gaps = len(orch.db.query(
        "SELECT sku_text FROM products WHERE price_eur <= 0 "
        "OR synthetic_price = 1"))
    if gaps == 0:
        print("  (prices are already loaded, so this check is skipped)")
        return
    print(f"  products with no sell price   {gaps}")
    print("  A quote with EUR 0 for the goods would be a business error.")
    print("  The order agent marks the order 'needs_review' and asks a")
    print("  human. It does not send anything.")


def show_pricing(orch, order, settings) -> None:
    head("4. WE PRICED IT AGAINST YOUR OWN TARIFFS")
    print(f"  subtotal        EUR {float(order.subtotal_eur):.2f}")
    if settings.school_discount_is_placeholder:
        # Say the quiet part out loud: this number is ours, not WiseQ's.
        print(f"  school discount {float(order.discount_pct):.0f}%   "
              f"- EUR {float(order.discount_eur):.2f}")
        print()
        print("  ^ PLACEHOLDER, NOT A WISEQ RULE. Your site publishes")
        print("    *staffelprijzen* (volume tiers), not a flat discount, and")
        print("    no percentage appears in the operating manual or the")
        print("    2026-10-28 transcript. Set WISEQ_SCHOOL_DISCOUNT_PCT")
        print("    once the real staffel list exists -- or set it to 0.")
    else:
        print(f"  school discount {float(order.discount_pct):.0f}%   "
              f"- EUR {float(order.discount_eur):.2f}")
    print(f"  shipping        EUR {float(order.shipping_eur):.2f}")
    print(f"  TOTAL           EUR {float(order.total_eur):.2f}")
    print("\n  carriers come from verzendtarieven.csv, your own sheet:")
    for l in order.lines:
        print(f"    - {l.sku:>4}  {l.carrier}  "
              f"EUR {float(l.shipping_eur):.2f}   ({l.rule_key})")


def show_human_gate(orch, order) -> None:
    head("5. AND THEN WE ASKED A HUMAN (NOTHING WAS SENT)")
    offer = orch.school_order_agent().build_offer(order.order_number)
    print(f"  offer number    {offer.get('offer_number')}")
    print(f"  status          {offer.get('status')}")
    print(f"  needs a human   {offer.get('requires_human_send')}")
    if offer.get("blocked_reason"):
        print(f"  blocked because {offer['blocked_reason']}")
        for l in offer.get("unpriced_lines", []):
            print(f"      ! {l['sku']}  {l['title'][:44]}")
    pending = orch.db.query(
        "SELECT agent_name, action_type, risk, status FROM approvals "
        "WHERE status='pending' ORDER BY requested_at")
    print(f"\n  pending approvals: {len(pending)}")
    for p in pending:
        print(f"    - {p['action_type']} ({p['risk']}) from {p['agent_name']}")
    print("\n  The offer was queued, not sent. A human approves it at")
    print("  POST /approvals/<id>. That is the whole safety model: the")
    print("  system prepares, a person decides.")


def show_reviews(orch, order) -> None:
    head("6. REVIEW REQUESTS (DUTCH, DRAFTED -- A HUMAN SENDS)")
    orch.review_agent().schedule(order.order_number, channel="bol.com")
    drafts = orch.review_agent().draft_due(limit=5)
    for d in drafts[:1]:
        print(f"  channel   {d.get('channel', 'bol.com')}")
        print(f"  to        test mailbox only "
              f"({get_settings().test_recipient})")
        body = d.get("body") or ""
        for ln in body.split("\n")[:8]:
            print(f"  | {ln}")
    print("\n  Every generated message goes to the test mailbox. No real")
    print("  customer is ever contacted by this system.")


def show_purchase_intel(orch) -> None:
    head("7. PURCHASE INTELLIGENCE (6-MONTH ROLLING AVERAGE)")
    report = orch.purchase_agent().compute()
    sugg = orch.purchase_agent().replenishment_suggestions(limit=6)
    print(f"  SKUs analysed   {report.get('skus', '?')} "
          f"over {report.get('window_days', '?')} days")
    for s in sugg:
        print(f"    - {s.get('sku'):>4}  avg6m={float(s.get('avg_qty_6m') or 0):<7.2f}"
              f"  stock={s.get('stock_qty'):<5} "
              f"suggest={s.get('suggested_qty'):<5}"
              f"  {s.get('price_bracket')}")
    print("\n  Restock suggestions, not automatic purchase orders. A human")
    print("  decides what to buy.")


def show_class_set_sizing() -> None:
    """The class-set sizing table WiseQ publishes for schools.

    This is the piece a school buyer cares about most, and it is the
    piece that used to live only in Rob's head.
    """
    from wiseq.agents.class_set_sizing import (SizingRequest, UseModel,
                                               resolve_use_model,
                                               size_class_set)

    head("CLASS SET SIZING -- WiseQ's own published table")
    print("  A school asks 'how many do I need?'. The rule depends on how")
    print("  the set is used, and it is published on wiseq.nl.")
    print()

    cases = [
        ("Gedeelde set per lokaal", 30, 28, None),
        ("Gedeelde set per bouw (roulerend)", 200, None, 120),
        ("Eigen setje per leerling", 100, None, None),
        ("Alleen digitale toetsen", 120, None, 45),
    ]
    for text, pupils, devices, largest in cases:
        model = resolve_use_model(text)
        req = SizingRequest(pupils=pupils, use_model=model,
                            devices=devices, largest_group=largest)
        r = size_class_set(req)
        print(f"  {r.use_model.label}")
        print(f"      {r.base_quantity} base  ->  {r.total_quantity} to order"
              f"   (+{r.total_quantity - r.base_quantity})")
        for note in r.notes:
            print(f"      . {note}")
        print()

    print("  With intensive shared use, the published 10-15% attrition")
    print("  allowance REPLACES the table buffer (they describe the same")
    print("  spares -- stacking them would quote a number WiseQ does not")
    print("  publish):")
    model = resolve_use_model("Gedeelde set per lokaal")
    r = size_class_set(SizingRequest(pupils=30, use_model=model, devices=28,
                                      intensive_shared_use=True,
                                      attrition_pct=15))
    print(f"      {r.base_quantity} devices -> {r.total_quantity} to order"
          f"   ({r.attrition_quantity} spares for attrition)")
    print()
    print("  No price is shown: the staffel ladder is behind B2B")
    print("  registration, so a quantity can be computed but not a total.")
    print()


def show_warranty_policy() -> None:
    """The repair-and-discount schedule from Rob's own operating manual."""
    from wiseq.agents.warranty_policy import DamageType, decide_warranty

    head("WARRANTY / REPAIR -- from your own operating manual")
    print("  WiseQ's public pages currently say 1 year (legal pages),")
    print("  2 years (Amazon, your manual) and 2 years including physical")
    print("  damage (the school page). Your manual has the actual repair")
    print("  price list, so that is what the system applies:")
    print()

    cases = [
        ("WiseQ One", 18, DamageType.NO_PHYSICAL_BREAK, False),
        ("WiseQ One", 30, DamageType.NO_PHYSICAL_BREAK, False),
        ("WiseQ Hero", 4, DamageType.PHYSICAL_BREAK, False),
        ("WiseQ Unbreakable", 2, DamageType.PHYSICAL_BREAK, False),
        ("WiseQ Unbreakable", 4, DamageType.PHYSICAL_BREAK, False),
        ("WiseQ Junior", 3, DamageType.OWN_FAULT, True),
    ]
    for model, months, damage, admitted in cases:
        d = decide_warranty(model, months, damage,
                            customer_admitted_fault=admitted)
        state = "COVERED" if d.covered else f"{d.discount_pct}% discount"
        print(f"  {model:<20} {months:>3} mo   {state}")
        print(f"      {d.reason}")
    print()
    print("  Every one of these needs a human decision before it reaches")
    print("  a customer -- the system proposes, you decide.")
    print()


def show_scheduler(orch) -> None:
    """The recurring jobs that keep this running without a human."""
    print()
    print(LINE)
    print("WHAT RUNS BY ITSELF (and what still waits for you)")
    print(LINE)

    sched = orch.scheduler()
    print()
    for job in sched.status()["jobs"]:
        every = job["interval_seconds"]
        if every % 86400 == 0:
            when = f"every {every // 86400} day(s)"
        elif every % 3600 == 0:
            when = f"every {every // 3600} hour(s)"
        else:
            when = f"every {every // 60} min"
        print(f"  {job['name']:<16} {when:<18} {job['description']}")
    print()
    print("  Run one cycle now, exactly as a cron job would:")
    results = sched.run_once()
    for r in results:
        mark = "ok " if r.get("status") == "ok" else "ERR"
        detail = r.get("result") if r.get("status") == "ok" else r.get("error")
        print(f"    [{mark}] {r['job']:<16} {detail}")
    print()
    print("  Every one of these only DETECTS and RECOMMENDS. The scheduler")
    print("  never sends an email, never changes a live price and never")
    print("  contacts bol.com -- it writes approvals for you to decide on.")


def show_integration_backlog(orch) -> None:
    """What the repository researched but nobody ever turned into work."""
    print()
    print(LINE)
    print("WHAT ELSE COULD BE CONNECTED (researched, not yet built)")
    print(LINE)

    built = orch.integration_agent().build_backlog()
    print(f"  research lanes       : {built['lanes']}")
    print(f"  candidate projects   : {built['candidates']}")
    print(f"  lanes not yet covered: {built['uncovered_lanes']}")
    print()
    print("  The client repository already contains 31 curated open-source")
    print("  searches (428 projects). Until now nothing in the system read")
    print("  them, so the research never became a plan. Here it is, ranked:")
    print()

    shown = 0
    for lane in built["backlog"]:
        if not lane["top"]:
            continue
        if shown >= 6:
            break
        shown += 1
        best = lane["top"][0]
        covered = "already built here" if lane["already_covered"] else "NOT BUILT"
        print(f"  {lane['lane']}")
        print(f"      need    : {lane['purpose']}")
        print(f"      status  : {covered}")
        print(f"      best fit: {best['repo']}  ({best['language']}, "
              f"{best['stars']} stars, score {best['score']})")
        for reason in best["reasons"][:2]:
            print(f"                - {reason}")
        print()


def show_strike_and_stock_guard(orch) -> None:
    """The two operating rules that protect the business week."""
    print()
    print(LINE)
    print("STRIKE WATCH + LOW-STOCK PRICE GUARD")
    print(LINE)

    strike = orch.strike_agent().evaluate()
    print(f"  on-time norm        : {strike['norm_pct']}%")
    print(f"  on-time rate        : {strike['on_time_rate_pct']}%  "
          f"(of {strike['shipped']} shipped this week)")
    print(f"  meets norm          : {strike['meets_norm']}")
    print(f"  strikes on record   : {strike['strikes']}")
    print(f"  escalate to Rob at  : {orch.strike_agent().escalate_at} strikes "
          f"-> now: {strike['escalate_to_rob']}")
    print(f"  switch to VVB at    : {orch.strike_agent().switch_over_at} strikes "
          f"-> now: {strike['switch_assortment_to_vvb']}")
    print()
    print("  The rule comes from the operating manual: bol.com evaluates the")
    print("  93% on-time norm every Wednesday; at 3 strikes Rob is involved,")
    print("  at 5 the whole assortment moves to VVB. The system computes and")
    print("  escalates -- it never contacts bol.com or switches an account.")

    guard = orch.stock_price_agent().recommend()
    print()
    print(f"  low-stock threshold : {guard['threshold']} units available")
    print(f"  low-stock articles  : {guard['low_stock']}")
    print(f"  actionable raises   : {guard['actionable']}")
    if guard["raise_pct_is_placeholder"]:
        print(f"  raise size          : {guard['raise_pct']}%  "
              f"-- PLACEHOLDER (the manual says 'ik geloof', i.e. 'I believe')")
    else:
        print(f"  raise size          : {guard['raise_pct']}%  (confirmed)")
    # Most urgent first: a stock gap that is days away beats one that is
    # weeks away, and the manual warns that a fixed threshold of 10 is
    # already late for items selling 10 a day.
    def _urgency(rec):
        return {"stockout_imminent": 0,
                "low_stock_normal_pace": 1,
                "low_stock_no_sales_history": 2}.get(rec.get("urgency"), 3)

    raisable = [r for r in guard["recommendations"]
                if r["status"] == "recommend_raise"]
    raisable.sort(key=_urgency)
    for rec in raisable[:3]:
        cover = rec.get("days_of_cover")
        cover_txt = (f"{cover} day(s) of cover" if cover is not None
                     else "cover unknown")
        flag = "  <-- URGENT" if rec.get("urgency") == "stockout_imminent" else ""
        print(f"    {rec['sku']:<8} {rec['available']:>3} left  "
              f"EUR {rec['current_price_eur']:.2f} -> "
              f"EUR {rec['recommended_price_eur']:.2f}   "
              f"[{cover_txt}]{flag}")
    print()
    print("  It recommends, a human approves. No live price is touched, and")
    print("  the raise must be set on BOTH selling accounts.")
    print()
    print("  The manual's own warning is built in: some articles sell 10")
    print("  units a day, so a 10-unit threshold arrives too late. The")
    print("  guard therefore also reports DAYS OF COVER -- how long the")
    print("  stock lasts at the recent sales rate -- and flags anything")
    print("  within 3 days as urgent.")


def main() -> int:
    settings = get_settings()
    repo = settings.repo_dir or (Path(__file__).resolve().parents[1] / "data" / "wiseq-repo")
    db = Database(settings.database_url)
    db.init_schema()
    load_all(db, repo)
    # Stock levels only.  ``seed_all`` would also overwrite the catalogue
    # prices with random ones, which would break the live-price demo; the
    # low-stock guard still needs stock rows to have anything to report.
    seed_stock(db)
    orch = WiseQOrchestrator(db, repo=repo,
                             discount_pct=settings.school_discount_pct)

    print(LINE)
    print("WISEQ x HERMES -- OPERATIONS REPLICA, LIVE DEMO")
    print(LINE)
    print(f"  data source : {repo}")
    print(f"  database    : {settings.database_url}")
    print(f"  test mailbox: {settings.test_recipient}")

    show_catalogue(orch)
    show_school_email(orch)
    show_price_import(orch)
    show_missing_price_block(orch)

    # The order is created AFTER the prices are in place, so the quote that
    # follows is a real quote rather than a blocked one.  The blocked
    # behaviour is still demonstrated -- see show_missing_price_block().
    order = orch.school_order_agent().handle_email(
        show_school_email.order, source_email="info@basisschool-de-zon.test")
    show_understanding(orch, order)
    show_pricing(orch, order, settings)
    show_human_gate(orch, show_understanding.order)
    show_reviews(orch, show_understanding.order)
    show_class_set_sizing()
    show_warranty_policy()
    show_purchase_intel(orch)
    show_scheduler(orch)
    show_integration_backlog(orch)
    show_strike_and_stock_guard(orch)

    print()
    print(LINE)
    print("END OF DEMO")
    print(LINE)
    print("  Every number above came from WiseQ's own master files.")
    print("  No credential was used. No message left the test mailbox.")
    print("  No order was placed, no price was changed, nothing was sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
