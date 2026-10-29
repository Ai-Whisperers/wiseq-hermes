"""Tests for the live Shopify catalogue sync.

These tests never touch the network.  They use a small fixture that mirrors
the shape of a real Shopify ``/products.json`` payload, including the details
that actually bit us against the live store:

* bundle SKUs are written with spaces (``117 + 240``) in the storefront but
  without spaces in the catalogue (``117+240``);
* internal rules (``intern`` / ``niet-los-bestelbaar`` tags) must never be
  priced;
* sample products are flagged, not silently sold;
* a variant with no price is reported as unresolved, never written as zero.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from wiseq.ingest.shopify import (
    ShopifyVariant,
    _normalise_bundle_sku,
    build_price_rows,
    parse_shopify_products,
    sync_shopify,
    write_price_csv,
)

FIXTURE_PRODUCTS = [
    {
        "id": 1,
        "title": "Losse Oplader - Universele USB Adapter",
        "handle": "losse-oplader",
        "product_type": "USB-adapter",
        "tags": ["kleur-wit", "soort-adapter"],
        "variants": [
            {
                "id": 11,
                "sku": "101",
                "price": "7.95",
                "available": True,
                "grams": 60,
                "compare_at_price": None,
            }
        ],
    },
    {
        "id": 2,
        "title": "25W Draadloze Magnetische Snellader - Wit",
        "handle": "magsafe",
        "product_type": "Draadloze lader",
        "tags": ["aansluiting-magsafe"],
        "variants": [
            {
                "id": 21,
                "sku": "234+121",
                "price": "37.95",
                "available": True,
                "grams": 210,
                "compare_at_price": None,
            }
        ],
    },
    {
        "id": 3,
        "title": "38W Snellader 3 Poorten",
        "handle": "snellader-3p",
        "product_type": "Oplaadset",
        "tags": ["soort-set"],
        "variants": [
            {
                "id": 31,
                "sku": "117 + 240",
                "price": "39.95",
                "available": True,
                "grams": 420,
                "compare_at_price": None,
            }
        ],
    },
    {
        "id": 4,
        "title": "Schoolbestelling",
        "handle": "schoolbestelling",
        "product_type": "Schoolbestelling",
        "tags": ["intern", "schoolbestelling"],
        "variants": [
            {
                "id": 41,
                "sku": "SCHOOL-TAMARISK",
                "price": "0.00",
                "available": True,
                "grams": 0,
                "compare_at_price": None,
            }
        ],
    },
    {
        "id": 5,
        "title": "Administratie- en verzendkosten",
        "handle": "b2b-toeslag",
        "product_type": "Toeslag",
        "tags": ["b2b-toeslag", "niet-los-bestelbaar"],
        "variants": [
            {
                "id": 51,
                "sku": None,
                "price": "3.57",
                "available": True,
                "grams": 0,
                "compare_at_price": None,
            }
        ],
    },
    {
        "id": 6,
        "title": "Sample - Hero - Draadloos - Blauw",
        "handle": "sample-hero",
        "product_type": "",
        "tags": ["sample"],
        "variants": [
            {
                "id": 61,
                "sku": "Sample.Hero.Blue",
                "price": "10.00",
                "available": True,
                "grams": 180,
                "compare_at_price": None,
            }
        ],
    },
    {
        "id": 7,
        "title": "Laptopkar 2200W - UV Desinfectie",
        "handle": "laptopkar",
        "product_type": "Laptopkar",
        "tags": [],
        "variants": [
            {
                "id": 71,
                "sku": "Laptopkar.2200W",
                "price": "1390.00",
                "available": True,
                "grams": 20000,
                "compare_at_price": None,
            }
        ],
    },
    {
        "id": 8,
        "title": "Gehoorbescherming - Blauw",
        "handle": "gehoor",
        "product_type": "Gehoorbescherming",
        "tags": [],
        "variants": [
            {
                "id": 81,
                "sku": "999",
                "price": "0.00",
                "available": True,
                "grams": 90,
                "compare_at_price": None,
            }
        ],
    },
]


@pytest.fixture()
def parsed():
    return parse_shopify_products(FIXTURE_PRODUCTS)


@pytest.fixture()
def variants(parsed):
    return parsed[0]


@pytest.fixture()
def rules(parsed):
    return parsed[1]


def test_parse_flattens_one_record_per_variant(variants, rules):
    # 8 fixture products, but one variant carries no SKU (the B2B surcharge
    # rule), so it becomes a rule rather than a variant.
    assert len(variants) == 6
    assert all(isinstance(v, ShopifyVariant) for v in variants)
    assert len(rules) == 2   # the EUR 0 school line and the B2B surcharge


def test_business_sku_strips_variant_suffix():
    assert ShopifyVariant("234+121", "t", "h", 1.0, "p").business_sku == "234+121"
    assert ShopifyVariant("231.White", "t", "h", 1.0, "p").business_sku == "231"
    assert ShopifyVariant("Tab.Hoes.Groen10.2", "t", "h", 1.0, "p").business_sku == "Tab"


def test_bundle_sku_normalisation_is_whitespace_insensitive():
    assert _normalise_bundle_sku("117 + 240") == "117+240"
    assert _normalise_bundle_sku("117+240") == "117+240"
    assert _normalise_bundle_sku("  111 +  216  ") == "111+216"


def test_internal_rules_are_never_priced(variants):
    priced, _unresolved, _unknown = build_price_rows(variants, {"101"})
    skus = {row["shopify_sku"] for row in priced}
    assert "SCHOOL-TAMARISK" not in skus


def test_school_rule_left_the_variant_list(variants, rules):
    """The EUR 0 school line must not be quotable as a product."""
    assert "SCHOOL-TAMARISK" not in {v.sku for v in variants}
    assert any(r["is_school_rule"] for r in rules)


def test_b2b_surcharge_rule_is_captured_not_dropped(rules):
    """The EUR 2.95 ex-VAT B2B surcharge is a real business rule.

    It has no SKU, so a naive parser drops it -- and a rule that silently
    disappears is a rule that silently stops being charged.
    """
    surcharge = [r for r in rules if r["is_b2b_surcharge"]]
    assert len(surcharge) == 1
    assert surcharge[0]["price_eur"] == 3.57
    # EUR 3.57 incl. 21% VAT is EUR 2.95 ex-VAT
    assert round(3.57 / 1.21, 2) == 2.95


def test_school_rule_is_captured(rules):
    school = [r for r in rules if r["is_school_rule"]]
    assert len(school) == 1
    assert school[0]["price_eur"] == 0.0


def test_sample_products_are_flagged_not_hidden(variants):
    priced, _unresolved, unknown = build_price_rows(variants, {"101"})
    samples = [row for row in priced + unknown if row.get("is_sample")]
    assert len(samples) == 1
    assert samples[0]["price_eur"] == 10.0


def test_zero_price_variant_is_unresolved_not_zero(variants):
    priced, unresolved, _unknown = build_price_rows(variants, {"101", "999"})
    zero_sku = {row["shopify_sku"] for row in priced} & {"999"}
    assert not zero_sku
    assert any(row["shopify_sku"] == "999" for row in unresolved)


def test_bundle_with_spaces_matches_normalised_catalogue(variants):
    known = {"101", "234+121", "117+240"}
    priced, _unresolved, unknown = build_price_rows(variants, known)
    skus = {row["shopify_sku"] for row in priced}
    assert "117 + 240" in skus
    # and the spaced bundle is not reported as unknown
    assert "117 + 240" not in {row["shopify_sku"] for row in unknown}


def test_unmodelled_product_is_reported_as_not_in_catalogue(variants):
    _priced, _unresolved, unknown = build_price_rows(variants, {"101"})
    titles = {row["live_title"] for row in unknown}
    assert "Laptopkar 2200W - UV Desinfectie" in titles


def test_write_price_csv_round_trips(tmp_path, variants):
    priced, _unresolved, _unknown = build_price_rows(variants, {"101"})
    out = write_price_csv(priced, tmp_path / "prices.csv")
    with out.open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(priced)
    assert rows[0]["price_eur"]
    assert all(float(r["price_eur"]) > 0 for r in rows)


def test_sync_shopify_uses_registry_and_spine(monkeypatch, tmp_path):
    registry = tmp_path / "wiseq-component-registry.csv"
    with registry.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["component_sku", "title"])
        writer.writerow(["101", "Losse Oplader"])
    spine = tmp_path / "wiseq-bundle-spine.csv"
    with spine.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bundle_sku", "bundle_title", "component_1", "component_2",
                         "component_3", "components_resolved", "needs_format_fix"])
        writer.writerow(["117+240", "38W Snellader 3 Poorten", "117", "240", "", "", ""])
        writer.writerow(["234+121", "25W MagSafe + adapter", "234", "121", "", "", ""])

    monkeypatch.setattr(
        "wiseq.ingest.shopify.fetch_shopify_products",
        lambda store=None, **kw: FIXTURE_PRODUCTS,
    )

    report = sync_shopify(
        store="https://example.invalid",
        registry=registry,
        csv_out=tmp_path / "out.csv",
        load_into_db=False,
    )
    assert report["products_fetched"] == len(FIXTURE_PRODUCTS)
    # the EUR 0 school line and the B2B surcharge are rules, not products
    assert report["non_sellable_skipped"] == 2
    assert len(report["order_rules"]) == 2
    assert any(r["is_b2b_surcharge"] for r in report["order_rules"])
    # 101 (component) + 234+121 (bundle) + 117 + 240 (bundle, spaced)
    assert report["priced_rows"] == 3
    assert report["unresolved"] == []
    assert report["samples_seen"][0]["sku"] == "Sample.Hero.Blue"
    assert Path(report["csv_written"]).exists()
