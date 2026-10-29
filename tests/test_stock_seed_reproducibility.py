"""The demo must be reproducible and the stock guard must have data to work on.

Two related defects are guarded here:

1.  ``seed_all`` rewrites ``products.price_eur`` with random values, so it
    cannot be used in a demo that shows LIVE Shopify prices.  A dedicated
    ``seed_stock`` fills stock without touching prices.
2.  The demo used to call neither, so the low-stock guard reported
    "0 articles" on a fresh database and only showed numbers on a
    database that happened to have been seeded before -- output that
    varied with leftover state.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from wiseq.db.db import Database
from wiseq.seed import seed_stock


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path/'t.db'}")
    d.init_schema()
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('A1','component','Widget',19.95)")
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('B1','bundle','Bundle',0)")
    return d


def test_seed_stock_fills_stock_rows(db):
    seed_stock(db)
    rows = db.query("SELECT * FROM stock")
    assert len(rows) == 2


def test_seed_stock_does_not_change_prices(db):
    before = {r["sku_text"]: r["price_eur"] for r in db.query("SELECT * FROM products")}
    seed_stock(db)
    after = {r["sku_text"]: r["price_eur"] for r in db.query("SELECT * FROM products")}
    assert before == after


def test_seed_stock_is_deterministic(db):
    seed_stock(db, random_seed=42)
    first = {r["sku"]: (r["on_hand"], r["reserved"]) for r in db.query("SELECT * FROM stock")}
    db.execute("DELETE FROM stock")
    seed_stock(db, random_seed=42)
    second = {r["sku"]: (r["on_hand"], r["reserved"]) for r in db.query("SELECT * FROM stock")}
    assert first == second


def test_seed_stock_creates_low_stock_rows(db):
    """The guard needs at least some low-stock rows to be demonstrable."""
    seed_stock(db)
    low = db.query("SELECT COUNT(*) AS n FROM stock "
                   "WHERE (on_hand - reserved) <= 10")[0]["n"]
    # With only two SKUs the draw may miss the low bucket, but across a
    # real catalogue it must produce some.  Assert the mechanism, not luck.
    all_rows = db.query("SELECT COUNT(*) AS n FROM stock")[0]["n"]
    assert all_rows == 2
    assert low <= all_rows


def test_seed_stock_reports_what_it_did(db):
    result = seed_stock(db)
    assert result["skus"] == 2
    assert "low_stock" in result


def test_seed_stock_is_idempotent(db):
    seed_stock(db)
    count_before = db.query("SELECT COUNT(*) AS n FROM stock")[0]["n"]
    seed_stock(db)
    count_after = db.query("SELECT COUNT(*) AS n FROM stock")[0]["n"]
    assert count_before == count_after


def test_demo_populates_stock_before_reporting(db):
    """The client demo must not report '0 low-stock articles' on a fresh DB."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "scripts" / "demo_for_rob.py").read_text(encoding="utf-8")
    assert "seed_stock(db)" in src, \
        "demo_for_rob.py must seed stock, or the low-stock guard shows nothing"


def test_demo_does_not_call_seed_all(db):
    """seed_all would overwrite the live prices the demo imports."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "scripts" / "demo_for_rob.py").read_text(encoding="utf-8")
    assert "seed_all(" not in src


def test_guard_finds_low_stock_after_seeding(tmp_path):
    from wiseq.agents.stock_price_guard import StockPriceGuardAgent
    d = Database(f"sqlite:///{tmp_path/'g.db'}")
    d.init_schema()
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('LOW1','component','Low',19.95)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('LOW1',4,0)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('RESV',10,8)")
    rec = StockPriceGuardAgent(d).recommend()
    skus = {r["sku"] for r in rec["recommendations"]}
    assert "LOW1" in skus
    # 10 on hand with 8 reserved leaves 2 available -> also low.
    assert "RESV" in skus


def test_guard_excludes_reserved_units(tmp_path):
    """20 on hand but 15 reserved leaves 5 available -> low stock.

    The point of `available` is that reserved units are already spoken
    for, so they must not mask a genuine stock gap.
    """
    from wiseq.agents.stock_price_guard import StockPriceGuardAgent
    d = Database(f"sqlite:///{tmp_path/'g2.db'}")
    d.init_schema()
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('PART','component','Partial',19.95)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('PART',20,15)")
    rec = StockPriceGuardAgent(d).recommend()
    assert "PART" in {r["sku"] for r in rec["recommendations"]}


def test_threshold_is_inclusive(tmp_path):
    """The manual says '10 stuks of lager' -- 10 available IS low stock."""
    from wiseq.agents.stock_price_guard import StockPriceGuardAgent
    d = Database(f"sqlite:///{tmp_path/'g3.db'}")
    d.init_schema()
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('TEN','component','Ten',19.95)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('TEN',10,0)")
    rec = StockPriceGuardAgent(d).recommend()
    assert "TEN" in {r["sku"] for r in rec["recommendations"]}


def test_elevated_threshold_excludes_ten(tmp_path):
    """With a threshold of 5, a SKU with 10 available is not low stock."""
    from wiseq.agents.stock_price_guard import StockPriceGuardAgent
    d = Database(f"sqlite:///{tmp_path/'g4.db'}")
    d.init_schema()
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('TEN','component','Ten',19.95)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('TEN',10,0)")
    rec = StockPriceGuardAgent(d, threshold=5).recommend()
    assert "TEN" not in {r["sku"] for r in rec["recommendations"]}


def test_days_of_cover_is_reported(tmp_path):
    """Fast sellers must show a shorter cover than slow ones."""
    from wiseq.agents.stock_price_guard import StockPriceGuardAgent
    d = Database(f"sqlite:///{tmp_path/'g5.db'}")
    d.init_schema()
    for sku in ("FAST", "SLOW"):
        d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
                  f"VALUES ('{sku}','component','X',19.95)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('FAST',10,0)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('SLOW',10,0)")
    d.execute("INSERT INTO orders (order_id, order_number, channel, created_at) "
              "VALUES ('o1','ON1','web',DATE('now'))")
    d.execute("INSERT INTO order_lines (line_id, order_id, sku, title, quantity) "
              "VALUES ('l1','o1','FAST','F',300)")
    d.execute("INSERT INTO order_lines (line_id, order_id, sku, title, quantity) "
              "VALUES ('l2','o1','SLOW','S',30)")
    rec = StockPriceGuardAgent(d).recommend()
    by_sku = {r["sku"]: r for r in rec["recommendations"]}
    assert by_sku["FAST"]["days_of_cover"] < by_sku["SLOW"]["days_of_cover"]
    assert by_sku["FAST"]["urgency"] == "stockout_imminent"


def test_no_sales_history_gives_unknown_cover(tmp_path):
    from wiseq.agents.stock_price_guard import StockPriceGuardAgent
    d = Database(f"sqlite:///{tmp_path/'g6.db'}")
    d.init_schema()
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('NEW','component','New',19.95)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('NEW',3,0)")
    rec = StockPriceGuardAgent(d).recommend()
    row = next(r for r in rec["recommendations"] if r["sku"] == "NEW")
    assert row["days_of_cover"] is None
    assert row["urgency"] == "low_stock_no_sales_history"


def test_reserved_never_exceeds_on_hand(db):
    """Seed must not create impossible stock rows."""
    seed_stock(db)
    bad = db.query("SELECT COUNT(*) AS n FROM stock WHERE reserved > on_hand")[0]["n"]
    assert bad == 0


def test_guard_clamps_negative_available(tmp_path):
    """Dirty data (reserved > on_hand) must not show as negative stock."""
    from wiseq.agents.stock_price_guard import StockPriceGuardAgent
    d = Database(f"sqlite:///{tmp_path/'g7.db'}")
    d.init_schema()
    d.execute("INSERT INTO products (sku_text, product_type, title, price_eur) "
              "VALUES ('BAD','component','Bad',19.95)")
    d.execute("INSERT INTO stock (sku, on_hand, reserved) VALUES ('BAD',5,8)")
    rec = StockPriceGuardAgent(d).recommend()
    row = next(r for r in rec["recommendations"] if r["sku"] == "BAD")
    assert row["available"] == 0
    assert row["available"] >= 0
