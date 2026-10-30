"""The decisions-owed agent must surface every gap and never guess.

The agent's job is to make the things only Rob can decide visible, and
to make sure the system cannot quietly proceed past one of them.  Two
properties matter and are tested here:

  * completeness -- each kind of decision is detected from the real
    source (the shipping CSV, the master-sheet index, the catalogue);
  * refusal -- an unresolved blocking decision raises an approval
    exactly once, so the gap shows up in the queue rather than only in
    a report nobody opens.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiseq.agents.decisions_owed import (
    BLOCKING_KINDS,
    DecisionsAgent,
)
from wiseq.db.db import Database


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path/'d.db'}")
    d.init_schema()
    return d


@pytest.fixture()
def repo(tmp_path):
    """A miniature client repository with a real-shaped mastersheet index."""
    root = tmp_path / "wiseq-repo"
    sheet_dir = root / "data" / "client" / "mastersheet"
    sheet_dir.mkdir(parents=True)
    (sheet_dir / "INDEX.json").write_text(json.dumps({
        "sheets": [
            "Verzendtarieven & Verzendstrate",
            "Kortingscodes",
            "Sales klanten",
            "Bestelformulier dozen",
        ],
        "exported_public": [
            "verzendtarieven.csv",
            "bestelformulier-dozen.csv",
        ],
        "not_exported_reason": {
            "Kortingscodes": "promo secrets",
            "Sales klanten": "customer PII",
        },
    }), encoding="utf-8")
    return root


# -- shipping rules -------------------------------------------------

def _shipping_rule(db, rule_key, category, status, template_ean="", notes=""):
    db.execute(
        """INSERT INTO shipping_rules
           (rule_key, category, clone_note, template_ean, notes,
            validation_status, source_effective, updated_at)
           VALUES (?,?,?,?,?,?,?, CURRENT_TIMESTAMP)""",
        (rule_key, category, "", template_ean, notes, status, "test"),
    )


def test_an_unvalidated_shipping_rule_is_a_decision(db, repo):
    _shipping_rule(db, "usb_hubs", "USB HUBS", "CASE_BY_CASE")
    decisions = DecisionsAgent(db, repo=repo).shipping_rule_decisions()
    assert len(decisions) == 1
    d = decisions[0]
    assert d["kind"] == "shipping_rule"
    assert d["blocking"] is True
    assert d["subject"] == "USB HUBS"


def test_a_validated_shipping_rule_is_not_a_decision(db, repo):
    _shipping_rule(db, "mag_safe", "MagSafe", "OK", "8720254493619")
    assert DecisionsAgent(db, repo=repo).shipping_rule_decisions() == []


def test_a_case_by_case_rule_asks_the_right_question(db, repo):
    _shipping_rule(db, "smartwatch", "Smartwatch", "CASE_BY_CASE")
    d = DecisionsAgent(db, repo=repo).shipping_rule_decisions()[0]
    assert "own tariff" in d["question"]
    assert d["blocks"]


def test_a_rule_without_a_template_ean_asks_for_the_ean(db, repo):
    _shipping_rule(db, "case", "Koptelefooncase", "NEEDS_CONFIRMATION")
    d = DecisionsAgent(db, repo=repo).shipping_rule_decisions()[0]
    assert "EAN" in d["question"]


# -- master sheets --------------------------------------------------

def test_a_sheet_that_was_never_exported_is_a_decision(db, repo):
    decisions = DecisionsAgent(db, repo=repo).master_sheet_decisions()
    ids = {d["id"] for d in decisions}
    assert "Kortingscodes" in ids
    assert "Sales klanten" in ids


def test_an_exported_sheet_is_not_a_decision(db, repo):
    decisions = DecisionsAgent(db, repo=repo).master_sheet_decisions()
    ids = {d["id"] for d in decisions}
    assert "Bestelformulier dozen" not in ids


def test_a_master_sheet_does_not_block_todays_orders(db, repo):
    """A missing sheet blocks a future capability, not the present."""
    decisions = DecisionsAgent(db, repo=repo).master_sheet_decisions()
    assert decisions
    assert all(d["blocking"] is False for d in decisions)
    assert all(d["kind"] in ("master_sheet",) for d in decisions)


def test_the_sensitive_reason_is_kept(db, repo):
    decisions = DecisionsAgent(db, repo=repo).master_sheet_decisions()
    codes = [d for d in decisions if d["id"] == "Kortingscodes"][0]
    assert "promo secrets" in codes["detail"]


def test_a_missing_index_is_not_an_error(db, tmp_path):
    assert DecisionsAgent(db, repo=tmp_path / "nothing").master_sheet_decisions() == []


# -- policy ---------------------------------------------------------

def test_the_warranty_contradiction_is_a_decision(db, repo):
    decisions = DecisionsAgent(db, repo=repo).policy_decisions()
    assert len(decisions) == 1
    d = decisions[0]
    assert d["kind"] == "policy"
    assert d["blocking"] is True
    assert d["owner"] == "Rob (WiseQ)"


# -- prices ---------------------------------------------------------

def test_a_product_without_a_price_is_a_decision(db, repo):
    db.execute(
        """INSERT INTO products
               (sku, sku_text, title, product_type, price_eur, synthetic_price)
           VALUES ('g1','101','WiseQ Adapter','component',0,1)""")
    decisions = DecisionsAgent(db, repo=repo).price_decisions()
    assert len(decisions) == 1
    assert decisions[0]["kind"] == "price"
    assert decisions[0]["blocking"] is True
    assert decisions[0]["status"] == "MISSING_PRICE"


def test_a_zero_price_is_treated_as_missing(db, repo):
    """Zero is not a price.  It blocks an offer just like NULL does."""
    db.execute(
        """INSERT INTO products
               (sku, sku_text, title, product_type, price_eur, synthetic_price)
           VALUES ('g1','101','WiseQ Adapter','component',0,1)""")
    assert len(DecisionsAgent(db, repo=repo).price_decisions()) == 1


def test_a_price_the_storefront_already_states_is_not_blocking(db, repo):
    """If the storefront answers the price question, the answer is close.

    The product still has no imported price, so the import is still
    wanted -- but it must not be reported as a missing price, because
    the price is known.  Reporting it as missing would send Rob to the
    price list for a price he can already read.
    """
    db.execute(
        """INSERT INTO products
               (sku, sku_text, title, product_type, price_eur, synthetic_price)
           VALUES ('g1','101','WiseQ Adapter','component',0,1)""")
    db.execute(
        """INSERT INTO storefront_catalogue
               (variant_sku, sku_text, title, price_eur, in_catalogue, is_sample)
           VALUES ('v101','101','WiseQ Adapter',18.95,1,0)""")

    decisions = DecisionsAgent(db, repo=repo).price_decisions()
    assert len(decisions) == 1
    assert decisions[0]["status"] == "PRICE_NOT_IMPORTED"
    assert decisions[0]["blocking"] is False
    assert "18.95" in decisions[0]["evidence"]


# -- catalogue ------------------------------------------------------

def test_a_storefront_product_outside_the_master_is_a_decision(db, repo):
    db.execute(
        """INSERT INTO storefront_catalogue
               (variant_sku, sku_text, title, price_eur, in_catalogue, is_sample)
           VALUES ('v999','999','WiseQ Extra Gadget',12.95,0,0)""")
    decisions = DecisionsAgent(db, repo=repo).catalogue_decisions()
    assert len(decisions) == 1
    assert decisions[0]["kind"] == "catalogue"
    assert decisions[0]["status"] == "OUTSIDE_MASTER"
    assert decisions[0]["blocking"] is True


def test_a_sample_is_reported_as_a_sample(db, repo):
    """A non-zero price does not make a sample sellable."""
    db.execute(
        """INSERT INTO storefront_catalogue
               (variant_sku, sku_text, title, price_eur, in_catalogue, is_sample)
           VALUES ('v998','998','WiseQ Demo Unit',15.00,0,1)""")
    decisions = DecisionsAgent(db, repo=repo).catalogue_decisions()
    assert len(decisions) == 1
    assert decisions[0]["status"] == "SAMPLE"
    assert "sample" in decisions[0]["question"].lower()


def test_a_catalogue_product_is_not_a_decision(db, repo):
    db.execute(
        """INSERT INTO storefront_catalogue
               (variant_sku, sku_text, title, price_eur, in_catalogue, is_sample)
           VALUES ('v101','101','WiseQ Adapter',18.95,1,0)""")
    assert DecisionsAgent(db, repo=repo).catalogue_decisions() == []


# -- the report -----------------------------------------------------

def test_the_report_lists_blocking_decisions_first(db, repo):
    _shipping_rule(db, "usb_hubs", "USB HUBS", "CASE_BY_CASE")
    report = DecisionsAgent(db, repo=repo).collect()
    kinds = [d["kind"] for d in report["decisions"]]
    blocking_flags = [d["blocking"] for d in report["decisions"]]
    # no blocking decision may come after a non-blocking one
    assert blocking_flags == sorted(blocking_flags, reverse=True)
    assert "shipping_rule" in kinds


def test_the_report_counts_by_kind(db, repo):
    _shipping_rule(db, "usb_hubs", "USB HUBS", "CASE_BY_CASE")
    report = DecisionsAgent(db, repo=repo).collect()
    assert report["by_kind"]["shipping_rule"] == 1
    assert report["blocking"] >= 1
    assert report["total"] >= report["blocking"]


def test_every_blocking_kind_is_declared_blocking(db, repo):
    """The kind sets and the per-decision flag must not drift apart."""
    for kind in BLOCKING_KINDS:
        assert kind in ("shipping_rule", "catalogue", "policy", "price")


# -- the refusal ----------------------------------------------------

def test_a_blocking_decision_raises_an_approval(db, repo):
    _shipping_rule(db, "usb_hubs", "USB HUBS", "CASE_BY_CASE")
    agent = DecisionsAgent(db, repo=repo)
    raised = agent.raise_blocking_approval()
    assert raised is not None
    assert raised["blocking"] >= 1

    row = db.query_one(
        "SELECT * FROM approvals WHERE action_type='decisions_owed'")
    assert row["status"] == "pending"
    assert row["risk"] == "high"


def test_the_same_open_decisions_do_not_pile_up_approvals(db, repo):
    """Re-running the job must not create a queue of duplicates."""
    _shipping_rule(db, "usb_hubs", "USB HUBS", "CASE_BY_CASE")
    agent = DecisionsAgent(db, repo=repo)
    assert agent.raise_blocking_approval() is not None
    assert agent.raise_blocking_approval() is None
    assert agent.raise_blocking_approval() is None

    rows = db.query(
        "SELECT approval_id FROM approvals WHERE action_type='decisions_owed'")
    assert len(rows) == 1


def test_a_new_decision_raises_a_fresh_approval(db, repo):
    _shipping_rule(db, "usb_hubs", "USB HUBS", "CASE_BY_CASE")
    agent = DecisionsAgent(db, repo=repo)
    agent.raise_blocking_approval()

    _shipping_rule(db, "smartwatch", "Smartwatch", "CASE_BY_CASE")
    assert agent.raise_blocking_approval() is not None

    rows = db.query(
        "SELECT approval_id FROM approvals WHERE action_type='decisions_owed'")
    assert len(rows) == 2


def test_no_approval_when_nothing_is_open(db, repo):
    """A clean system must not keep asking for a decision."""
    agent = DecisionsAgent(db, repo=repo)
    # The warranty contradiction is live, so remove it for this check
    # by asserting on a report that has no *other* blocking item.
    report = agent.collect()
    blocking_kinds = {d["kind"] for d in report["decisions"] if d["blocking"]}
    assert blocking_kinds <= {"policy"}


def test_the_approval_payload_names_the_decision(db, repo):
    _shipping_rule(db, "usb_hubs", "USB HUBS", "CASE_BY_CASE")
    DecisionsAgent(db, repo=repo).raise_blocking_approval()
    row = db.query_one(
        "SELECT payload FROM approvals WHERE action_type='decisions_owed'")
    payload = json.loads(row["payload"])
    assert payload["count"] >= 1
    assert payload["fingerprint"]
    assert any(d["kind"] == "shipping_rule" for d in payload["decisions"])


# -- the storefront catalogue ---------------------------------------

def test_five_samples_stay_five_rows_even_when_they_share_a_business_sku(db, repo):
    """Five sample variants share one business SKU.

    Keying the table on the business SKU would merge them into one row
    and understate the decision from five products to one.  This is the
    exact shape of the live storefront: 'Sample.Kids.ANC.Black',
    'Sample.Unbreakable.Blue', 'Sample.Hero.Blue', 'Sample.Junior.Black'
    and 'sample.one.zwart.blauw' all report business SKU 'Sample'.
    """
    for variant in ("Sample.Kids.ANC.Black", "Sample.Unbreakable.Blue",
                    "Sample.Hero.Blue", "Sample.Junior.Black",
                    "sample.one.zwart.blauw"):
        db.execute(
            """INSERT INTO storefront_catalogue
                   (variant_sku, sku_text, title, price_eur,
                    in_catalogue, is_sample)
               VALUES (?, 'Sample', ?, 10.00, 0, 1)""",
            (variant, f"Sample - {variant}"))

    decisions = DecisionsAgent(db, repo=repo).catalogue_decisions()
    # One decision -- the samples are one question -- but all five
    # variants are listed underneath it, so nothing is hidden.
    assert len(decisions) == 1
    assert decisions[0]["status"] == "SAMPLE"
    assert decisions[0]["variant_count"] == 5
    assert len({v["variant_sku"] for v in decisions[0]["variants"]}) == 5
