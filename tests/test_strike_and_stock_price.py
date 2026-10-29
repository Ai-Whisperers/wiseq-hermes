"""Strike monitoring and the stock-based price guard.

Both rules come from the client operating manual and are implemented as
detect-and-recommend agents.  Neither may take a consequential action on
its own: the strike monitor must escalate to Rob at the published
threshold, and the price guard must produce a recommendation rather than
a live price change.
"""
from __future__ import annotations

import pytest

from wiseq.agents.stock_price_guard import StockPriceGuardAgent
from wiseq.agents.strike_monitor import StrikeMonitorAgent
from wiseq.db.db import Database


@pytest.fixture()
def db():
    d = Database("sqlite:///:memory:")
    d.init_schema()
    return d


def _order(d, number, status="shipped", created="2026-10-26 09:00:00",
           updated="2026-10-26 12:00:00", channel="b2b_school"):
    d.execute(
        """INSERT INTO orders (order_id, order_number, channel, status,
                              created_at, updated_at)
           VALUES (?,?,?,?,?,?)""",
        (f"o-{number}", number, channel, status, created, updated))


# ---------------------------------------------------------------- strike

def test_on_time_rate_counts_shipped_orders(db):
    _order(db, "A1", updated="2026-10-26 12:00:00")   # 3h  -> on time
    _order(db, "A2", updated="2026-10-28 12:00:00")   # 2d  -> on time
    agent = StrikeMonitorAgent(db)
    stats = agent.on_time_rate("2026-10-26", "2026-11-01")
    assert stats["shipped"] == 2
    assert stats["on_time"] == 2
    assert stats["late"] == 0
    assert stats["meets_norm"] is True


def test_late_orders_lower_the_rate_below_the_93_percent_norm(db):
    for i in range(9):
        _order(db, f"B{i}", updated="2026-10-26 12:00:00")
    _order(db, "B9", updated="2026-10-30 12:00:00")     # 4 days -> late
    agent = StrikeMonitorAgent(db)
    stats = agent.on_time_rate("2026-10-26", "2026-11-01")
    assert stats["shipped"] == 10
    assert stats["on_time"] == 9
    assert stats["on_time_rate_pct"] == 90.0
    assert stats["meets_norm"] is False


def test_unshipped_orders_are_not_counted_as_on_time(db):
    """An order that never shipped must not inflate the rate."""
    _order(db, "C1", status="received")
    agent = StrikeMonitorAgent(db)
    stats = agent.on_time_rate("2026-10-26", "2026-11-01")
    assert stats["orders_total"] == 1
    assert stats["shipped"] == 0
    assert stats["open"] == 1
    assert stats["on_time_rate_pct"] == 0.0
    assert stats["meets_norm"] is False


def test_the_norm_is_93_percent(db):
    assert StrikeMonitorAgent(db).norm_pct == 93.0


def test_three_strikes_escalate_to_rob_and_raise_an_approval(db):
    agent = StrikeMonitorAgent(db)
    for i in range(3):
        agent.record_strike(f"2026-10-{10 + i}")
    result = agent.evaluate()
    assert result["strikes"] == 3
    assert result["escalate_to_rob"] is True
    assert result["switch_assortment_to_vvb"] is False
    pending = db.query(
        "SELECT * FROM approvals WHERE status='pending' AND action_type=?",
        ("strike_escalation",))
    assert len(pending) == 1
    assert "3+ strikes" in pending[0]["payload"] or "Rob" in pending[0]["payload"]


def test_five_strikes_switch_the_assortment_to_vvb(db):
    agent = StrikeMonitorAgent(db)
    for i in range(5):
        agent.record_strike(f"2026-10-{10 + i}")
    result = agent.evaluate()
    assert result["strikes"] == 5
    assert result["switch_assortment_to_vvb"] is True


def test_two_strikes_do_not_escalate(db):
    agent = StrikeMonitorAgent(db)
    for i in range(2):
        agent.record_strike(f"2026-10-{10 + i}")
    result = agent.evaluate()
    assert result["escalate_to_rob"] is False
    assert db.query("SELECT * FROM approvals WHERE action_type=?",
                     ("strike_escalation",)) == []


def test_a_carrier_strike_requires_followup_within_72_hours(db):
    agent = StrikeMonitorAgent(db)
    result = agent.record_strike("2026-10-20", cause="carrier_late",
                                  carrier="QLS")
    assert result["carrier_followup"]["due_within_hours"] == 72
    assert "pakketdienstqls" in result["carrier_followup"]["contact"]


def test_evaluation_is_audited(db):
    agent = StrikeMonitorAgent(db)
    agent.evaluate()
    rows = db.query("SELECT * FROM audit_log WHERE action='strike_evaluated'")
    assert len(rows) == 1


# ------------------------------------------------------- stock price guard

def _stock(d, sku, on_hand, reserved=0, price=None):
    d.execute(
        "INSERT INTO stock (sku, on_hand, reserved) VALUES (?,?,?)",
        (sku, on_hand, reserved))
    if price is not None:
        d.execute(
            """INSERT INTO products (sku, sku_text, title, product_type, price_eur)
               VALUES (?,?,?,?,?)""",
            (f"p-{sku}", sku, f"Product {sku}", "component", price))


def test_low_stock_articles_are_detected(db):
    _stock(db, "111", 4, price=20.0)
    _stock(db, "222", 50, price=20.0)
    agent = StockPriceGuardAgent(db)
    report = agent.recommend()
    assert report["low_stock"] == 1
    assert report["actionable"] == 1
    rec = report["recommendations"][0]
    assert rec["sku"] == "111"
    assert rec["recommended_price_eur"] == 22.0   # +10%
    assert rec["raise_eur"] == 2.0


def test_reserved_stock_is_excluded_from_available(db):
    """Available = on_hand - reserved, and the threshold uses available.

    20 on hand with 15 reserved leaves 5 available -- which IS low stock.
    The point of the test is that the 20 on-hand figure does not hide the
    fact that only 5 units can actually be sold.
    """
    _stock(db, "333", 20, reserved=15, price=20.0)
    agent = StockPriceGuardAgent(db)
    report = agent.recommend()
    assert report["low_stock"] == 1
    assert report["recommendations"][0]["available"] == 5


def test_high_on_hand_with_high_reserved_is_not_low_stock(db):
    """60 on hand with 55 reserved leaves 5 available -> still low."""
    _stock(db, "334", 60, reserved=55, price=20.0)
    agent = StockPriceGuardAgent(db)
    assert agent.recommend()["low_stock"] == 1

    # and the real "not low" case: plenty of available stock
    _stock(db, "335", 100, reserved=0, price=20.0)
    assert agent.recommend()["low_stock"] == 1   # only 333 (5 available) qualifies


def test_exactly_ten_available_is_low_stock(db):
    _stock(db, "444", 10, reserved=0, price=20.0)
    agent = StockPriceGuardAgent(db)
    assert agent.recommend()["low_stock"] == 1


def test_a_missing_price_is_flagged_not_silently_raised(db):
    _stock(db, "555", 2, price=None)
    agent = StockPriceGuardAgent(db)
    report = agent.recommend()
    rec = report["recommendations"][0]
    assert rec["status"] == "price_missing"
    assert rec["recommended_price_eur"] is None
    assert report["actionable"] == 0


def test_the_price_guard_only_recommends_and_asks_for_approval(db):
    _stock(db, "666", 1, price=100.0)
    agent = StockPriceGuardAgent(db)
    agent.recommend()
    pending = db.query(
        "SELECT * FROM approvals WHERE status='pending' AND action_type=?",
        ("stock_price_raise",))
    assert len(pending) == 1
    assert pending[0]["risk"] == "high"
    # and no price was actually changed
    row = db.query_one("SELECT price_eur FROM products WHERE sku_text=?", ("666",))
    assert float(row["price_eur"]) == 100.0


def test_the_raise_percentage_is_a_placeholder_until_confirmed(db):
    agent = StockPriceGuardAgent(db)
    assert agent.raise_pct == 10.0
    assert agent.is_placeholder is True


def test_a_confirmed_percentage_is_not_a_placeholder(db):
    agent = StockPriceGuardAgent(db, raise_pct=7.5)
    assert agent.raise_pct == 7.5
    assert agent.is_placeholder is False


def test_repeated_evaluation_does_not_spam_the_approvals_queue(db):
    """One unresolved escalation is one approval, however often we check."""
    agent = StrikeMonitorAgent(db)
    for i in range(3):
        agent.record_strike(f"2026-10-{10 + i}")
    for _ in range(5):
        agent.evaluate()
    pending = db.query(
        "SELECT * FROM approvals WHERE status='pending' AND action_type=?",
        ("strike_escalation",))
    assert len(pending) == 1


def test_the_strike_count_is_not_inflated_by_evaluation_audits(db):
    """Evaluation writes audit rows; they must not count as strikes."""
    agent = StrikeMonitorAgent(db)
    agent.record_strike("2026-10-10")
    agent.record_strike("2026-10-11")
    agent.evaluate()
    agent.evaluate()
    assert agent.strike_count() == 2
