"""Portability: the same code must work on PostgreSQL as on SQLite.

PostgreSQL is the production backend (Supabase), SQLite is the local test
backend. The two differ in ways that are easy to get wrong -- placeholder
style, boolean literals and defaults, row types -- so the whole pipeline is
exercised against a real PostgreSQL server whenever one is reachable.

Set WISEQ_TEST_PG_URL to a PostgreSQL DSN to enable these tests, e.g.

    WISEQ_TEST_PG_URL=postgresql://postgres@127.0.0.1:55432/wiseq_test

When no server is reachable the module skips rather than failing, so the
default `pytest` run stays green on a machine without PostgreSQL.
"""
import os

import pytest

PG_URL = os.getenv("WISEQ_TEST_PG_URL")


@pytest.fixture(scope="module")
def pg_db():
    if not PG_URL:
        pytest.skip("WISEQ_TEST_PG_URL is not set")
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 is not installed")
    try:
        conn = psycopg2.connect(PG_URL)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    conn.close()

    from wiseq.db.db import Database
    database = Database(PG_URL)
    database.init_schema()
    yield database
    database.close()


def test_schema_creates_all_tables(pg_db):
    rows = pg_db.query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name")
    names = {r["table_name"] for r in rows}
    for expected in ("products", "orders", "order_lines", "shipping_tariffs",
                     "ean_registry", "approvals", "audit_log", "outbox",
                     "stock", "purchase_intel"):
        assert expected in names, f"missing table {expected}"


def test_placeholders_and_booleans_round_trip(pg_db, repo_dir):
    """Placeholder translation and boolean handling must work on Postgres."""
    from wiseq.ingest.loaders import load_all
    load_all(pg_db, repo_dir)

    row = pg_db.query_one(
        "SELECT sku_text, title, has_ean FROM products WHERE sku_text = ?",
        ("117",))
    assert row is not None
    assert isinstance(row["title"], str)
    assert row["has_ean"] in (0, 1, True, False)


def test_boolean_comparison_is_rewritten_for_postgres(pg_db, repo_dir):
    """A `flag = 1` comparison must be translated, not sent verbatim."""
    from wiseq.ingest.loaders import load_all
    load_all(pg_db, repo_dir)
    # The catalogue stores has_ean as a boolean; querying it with `= 1` is
    # invalid SQL on PostgreSQL and must be adapted by the db layer.
    rows = pg_db.query("SELECT sku_text FROM products WHERE has_ean = 1")
    assert rows, "at least one product carries an EAN"
    assert pg_db.query("SELECT sku_text FROM products WHERE has_ean = 0")


def test_real_order_flow_on_postgres(pg_db, repo_dir):
    """The school-order flow must behave identically on PostgreSQL."""
    from wiseq.agents.school_orders import SchoolOrderAgent
    from wiseq.ingest.loaders import load_all
    from wiseq.orchestrator import build_resolver
    load_all(pg_db, repo_dir)

    agent = SchoolOrderAgent(pg_db, build_resolver(pg_db), discount_pct=15.0)
    order = agent.handle_email(
        "Beste WiseQ team,\n\n"
        "Wij willen graag 10x de MagSafe draadloze oplader en "
        "2x de 45W GaN snellader bestellen voor onze bovenbouw.\n\n"
        "Met vriendelijke groet,\nBasisschool De Zon",
        source_email="pg-test@basisschool.test")

    assert len(order.lines) == 2, "both products must resolve to catalogue lines"
    assert all(l.framing_status.value == "framed" for l in order.lines)
    assert all(l.carrier for l in order.lines)
    assert order.shipping_eur > 0

    offer = agent.build_offer(order.order_number)
    # This catalogue carries no sell prices, so the offer must be blocked.
    assert offer["status"] == "blocked_missing_price"
    assert offer["unpriced_lines"]

    pending = pg_db.query(
        "SELECT * FROM approvals WHERE action_type='price_missing' AND status='pending'")
    assert pending, "a human must be asked to supply the missing prices"
