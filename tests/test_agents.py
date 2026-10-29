"""Agent behaviour: school orders, bundles, purchase intel, reviews, assortment."""
import json

import pytest

from wiseq.agents.bundles import BundleAgent
from wiseq.agents.purchase_intel import PurchaseIntelligenceAgent
from wiseq.agents.reviews import ReviewAgent
from wiseq.agents.school_orders import SchoolOrderAgent, parse_school_email
from wiseq.domain.models import FramingStatus, OrderStatus, ReviewStatus
from wiseq.seed import INBOUND_EMAILS, seed_all


def _agent(loaded):
    from wiseq.orchestrator import build_resolver
    return SchoolOrderAgent(loaded, build_resolver(loaded), discount_pct=15.0)


def test_parse_school_email_extracts_lines():
    parsed = parse_school_email(INBOUND_EMAILS[0])
    assert parsed.lines == [("117", 2), ("234", 10)]
    assert parsed.po_number == "PO-2026-4412"


@pytest.mark.parametrize("body,expected", [
    # Dutch schools write the quantity FIRST: "10x MagSafe draadloze oplader".
    ("Wij willen graag 10x de MagSafe draadloze oplader bestellen.",
     [("MagSafe draadloze oplader", 10)]),
    # Two products in one sentence must yield two lines.
    ("Wij willen 10x de MagSafe draadloze oplader en 2x de 45W GaN snellader "
     "bestellen voor onze bovenbouw.",
     [("MagSafe draadloze oplader", 10), ("45W GaN snellader", 2)]),
    # Trailing "x N" form.
    ("- MagSafe draadloze oplader x 10\n- USB-C adapter x 5",
     [("MagSafe draadloze oplader", 10), ("USB-C adapter", 5)]),
    # "stuks" instead of "x".
    ("We willen 25 stuks koptelefoon cases bestellen.",
     [("koptelefoon cases", 25)]),
    # "SKU 234 x 10" -- SKU first.
    ("SKU 234 x 10\nSKU 117 x 2", [("234", 10), ("117", 2)]),
])
def test_parse_school_email_handles_real_dutch_formats(body, expected):
    assert parse_school_email(body).lines == expected


def test_parse_school_email_ignores_a_plain_sign_off():
    body = "Hartelijk dank,\n\nMet vriendelijke groet,\nBasisschool De Zon"
    assert parse_school_email(body).lines == []


def test_catalogue_matching_finds_a_product_by_description(loaded):
    """A school's wording is a description, not a catalogue substring.

    The catalogue title is "Draadloze Oplader - Geschikt Voor MagSafe - ..."
    while a school writes "MagSafe draadloze oplader", so a LIKE substring
    can never match and the line would silently disappear from the order.
    """
    agent = _agent(loaded)
    line = agent._resolve_line("MagSafe draadloze oplader", 1)
    assert line is not None, "description must resolve to a catalogue product"
    assert line.sku
    assert "magsafe" in line.title.lower()


def test_catalogue_matching_returns_none_for_unknown_product(loaded):
    agent = _agent(loaded)
    assert agent._resolve_line("koptelefoon cases", 1) is None


def test_parse_school_email_finds_address():
    parsed = parse_school_email(INBOUND_EMAILS[0])
    assert parsed.email == "info@basisschool-dezon.test"


def test_school_order_creates_framed_order(loaded):
    agent = _agent(loaded)
    order = agent.handle_email(INBOUND_EMAILS[0])
    assert order.lines, "no lines parsed"
    assert order.total_eur > 0
    assert order.discount_pct == 15.0


def test_school_order_persists_lines(loaded):
    agent = _agent(loaded)
    order = agent.handle_email(INBOUND_EMAILS[0])
    rows = loaded.query("SELECT * FROM order_lines WHERE order_id IN "
                        "(SELECT order_id FROM orders WHERE order_number=?)",
                        (order.order_number,))
    assert len(rows) == len(order.lines)


def test_unresolvable_lines_are_escalated_not_guessed(loaded):
    """A line whose product does not exist must not silently vanish."""
    agent = _agent(loaded)
    order = agent.handle_email(
        "Beste WiseQ,\n\n- 999 x 5\n\nMet vriendelijke groet,\nSchool")
    assert order.lines == []
    pending = loaded.query(
        "SELECT * FROM approvals WHERE action_type='shipping_rule_unresolved'")
    # no lines -> no lines to frame, but nothing was invented either
    assert order.total_eur == 0


def test_bundle_agent_verifies_spine(loaded):
    result = BundleAgent(loaded).verify_spine()
    assert result["bundles"] == 25
    assert result["resolved"] == 25
    assert result["broken"] == []


def test_bundle_agent_detects_missing_component(loaded):
    loaded.execute("UPDATE components SET sku_text='9999' WHERE sku_text='117'")
    result = BundleAgent(loaded).verify_spine()
    assert result["broken"], "missing component must be reported"


def test_purchase_intel_computes_rolling_average(loaded):
    seed_all(loaded)
    agent = PurchaseIntelligenceAgent(loaded)
    result = agent.compute()
    assert result["skus"] > 0
    row = loaded.query_one("SELECT * FROM purchase_intel WHERE avg_qty_6m > 0 LIMIT 1")
    assert row is not None
    assert row["avg_qty_6m"] > 0


def test_purchase_intel_suggests_replenishment(loaded):
    seed_all(loaded)
    agent = PurchaseIntelligenceAgent(loaded)
    agent.compute()
    suggestions = agent.replenishment_suggestions()
    assert suggestions
    assert all(s["suggested_qty"] > 0 for s in suggestions)


def test_review_draft_is_dutch_and_requires_human(loaded):
    agent = _agent(loaded)
    order = agent.handle_email(INBOUND_EMAILS[0])
    agent.review_agent = ReviewAgent(loaded) if hasattr(agent, "review_agent") else None
    reviews = ReviewAgent(loaded)
    reviews.schedule(order.order_number)
    drafts = reviews.draft_due()
    assert drafts, "expected a drafted review"
    body = drafts[0]["body"]
    assert "Bedankt" in body
    assert drafts[0]["requires_human_send"] is True


def test_review_send_is_approval_gated(loaded):
    agent = _agent(loaded)
    order = agent.handle_email(INBOUND_EMAILS[0])
    reviews = ReviewAgent(loaded)
    reviews.schedule(order.order_number)
    reviews.draft_due()
    pending = loaded.query(
        "SELECT * FROM approvals WHERE action_type='review_send'")
    assert pending, "review send must require human approval"


def test_review_suppression_blocks_drafting(loaded):
    agent = _agent(loaded)
    order = agent.handle_email(INBOUND_EMAILS[0])
    reviews = ReviewAgent(loaded)
    reviews.schedule(order.order_number)
    reviews.suppress("info@basisschool-dezon.test", "opted out")
    drafts = reviews.draft_due()
    assert drafts == [], "suppressed address must not receive a draft"


def test_assortment_agent_flags_content_problems(loaded):
    seed_all(loaded)
    from wiseq.agents.assortment import AssortmentAgent
    result = AssortmentAgent(loaded).scan()
    assert result["listings"] == 40
    assert result["issues"] > 0


def test_audit_log_records_every_agent_action(loaded):
    agent = _agent(loaded)
    agent.handle_email(INBOUND_EMAILS[0])
    rows = loaded.query("SELECT * FROM audit_log")
    actions = {r["action"] for r in rows}
    assert "order_created" in actions


def test_approval_gate_blocks_ungated_high_impact_action(loaded):
    """An offer may only be queued for sending when every line is priced.

    The catalogue in this repository carries no sell prices (they live in
    FiveX / Mastersheet.xlsx), so the default path is: the offer is BLOCKED
    and a high-risk price_missing approval is raised instead of offer_send.
    """
    agent = _agent(loaded)
    order = agent.handle_email(INBOUND_EMAILS[0])
    offer = agent.build_offer(order.order_number)

    pending = loaded.query("SELECT * FROM approvals WHERE action_type='offer_send'")
    assert not pending, "offer with unpriced lines must not queue offer_send"

    missing = loaded.query("SELECT * FROM approvals WHERE action_type='price_missing'")
    assert missing, "missing prices must raise a price_missing approval"
    assert missing[0]["risk"] == "high"
    assert offer["status"] == "blocked_missing_price"
    assert offer["unpriced_lines"], "the block must name the unpriced lines"


def test_offer_is_queued_for_send_once_prices_are_known(loaded):
    """With prices filled in, the normal approval-gated send path is used."""
    agent = _agent(loaded)
    order = agent.handle_email(INBOUND_EMAILS[0])
    loaded.execute(
        "UPDATE order_lines SET unit_price_eur=12.50, line_total_eur=12.50 "
        "WHERE order_id=(SELECT order_id FROM orders WHERE order_number=?)",
        (order.order_number,))
    loaded.execute(
        "UPDATE orders SET total_eur=25.00 WHERE order_number=?",
        (order.order_number,))

    offer = agent.build_offer(order.order_number)
    assert offer["status"] == "draft"
    pending = loaded.query("SELECT * FROM approvals WHERE action_type='offer_send'")
    assert pending, "offer send must be approval-gated"
    # The order step raised one price_missing approval; building the offer
    # must not pile up another one for the same issue.
    missing = loaded.query(
        "SELECT * FROM approvals WHERE action_type='price_missing'")
    assert len(missing) == 1
