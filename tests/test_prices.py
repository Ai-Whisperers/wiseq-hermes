"""Tests for the sell-price import path.

The client's repository ships master data but no sell prices, so a freshly
ingested catalogue is priced at 0 and the school pipeline refuses to quote.
These tests cover the import that closes that gap.
"""
from __future__ import annotations

import pytest

from wiseq.db.db import Database
from wiseq.ingest.prices import (load_prices, parse_price_source,
                                  _norm_sku, _to_price)


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("value,expected", [
    ("19.95", 19.95),
    ("EUR 19,95", 19.95),
    ("€ 24,50", 24.50),
    ("19,95", 19.95),
    (19.95, 19.95),
    ("1.234,56", 1234.56),
    ("0", 0.0),
    ("", None),
    (None, None),
    ("abc", None),
    ("-5", None),
])
def test_to_price_accepts_real_export_shapes(value, expected):
    assert _to_price(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("231", "231"),
    ("231.0", "231"),
    ("0231", "231"),
    (" 231 ", "231"),
    ("", ""),
])
def test_norm_sku_collapses_excel_spellings(value, expected):
    assert _norm_sku(value) == expected


def test_parse_csv_with_header():
    rows = parse_price_source("sku_text,price_eur\n231,19.95\n234,24.50\n")
    assert rows == [{"sku": "231", "price": 19.95},
                    {"sku": "234", "price": 24.50}]


def test_parse_csv_dutch_column_names_and_semicolon():
    rows = parse_price_source("Artikelnummer;Verkoopprijs\n231;19,95\n")
    assert rows == [{"sku": "231", "price": 19.95}]


def test_parse_csv_without_header():
    rows = parse_price_source("231,19.95\n234,24.50\n")
    assert rows == [{"sku": "231", "price": 19.95},
                    {"sku": "234", "price": 24.50}]


def test_parse_json_object_mapping():
    rows = parse_price_source('{"231": 19.95, "234": 24.50}')
    assert rows == [{"sku": "231", "price": 19.95},
                    {"sku": "234", "price": 24.50}]


def test_parse_json_record_list():
    rows = parse_price_source('[{"sku_text": "231", "price_eur": 19.95}]')
    assert rows == [{"sku": "231", "price": 19.95}]


def test_unreadable_price_is_reported_not_zeroed():
    rows = parse_price_source("sku_text,price_eur\n231,not-a-number\n")
    assert rows == [{"sku": "231", "price": None}]


# ---------------------------------------------------------------- writing
@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path}/prices.db")
    d.init_schema()
    d.execute(
        "INSERT INTO products (sku, sku_text, title, product_type, price_eur, "
        "synthetic_price) VALUES (?,?,?,?,?,?)",
        ("id-1", "231", "Draadloze Oplader - MagSafe", "component", 0, 1))
    d.execute(
        "INSERT INTO products (sku, sku_text, title, product_type, price_eur, "
        "synthetic_price) VALUES (?,?,?,?,?,?)",
        ("id-2", "234", "25W MagSafe Snellaader", "component", 0, 1))
    return d


def test_load_prices_writes_and_clears_synthetic_flag(db):
    result = load_prices(db, "sku_text,price_eur\n231,19.95\n234,24.50\n",
                          source_name="FiveX export")
    assert result.prices_written == 2
    assert result.unresolved == []
    row = db.query_one(
        "SELECT price_eur, synthetic_price FROM products WHERE sku_text='231'")
    assert float(row["price_eur"]) == 19.95
    assert row["synthetic_price"] in (0, False)


def test_load_prices_reports_unknown_sku(db):
    result = load_prices(db, "sku_text,price_eur\n999,10.00\n")
    assert result.prices_written == 0
    assert result.not_in_catalogue == ["999"]


def test_load_prices_does_not_write_zero_for_unreadable(db):
    result = load_prices(db, "sku_text,price_eur\n231,???\n")
    assert result.prices_written == 0
    assert result.unresolved == ["231: unreadable price"]
    row = db.query_one("SELECT price_eur FROM products WHERE sku_text='231'")
    assert float(row["price_eur"]) == 0


def test_load_prices_is_idempotent(db):
    csv = "sku_text,price_eur\n231,19.95\n"
    load_prices(db, csv)
    load_prices(db, csv)
    row = db.query_one("SELECT price_eur FROM products WHERE sku_text='231'")
    assert float(row["price_eur"]) == 19.95


def test_load_prices_from_file(tmp_path, db):
    f = tmp_path / "prices.csv"
    f.write_text("sku_text,price_eur\n231,19.95\n", encoding="utf-8")
    result = load_prices(db, f)
    assert result.prices_written == 1
    assert result.source == "prices.csv"
