"""Tests for the public-site audit script.

The audit reads the live storefront. These tests run against a captured
snapshot so the parsing logic is pinned down without the network.

The snapshot was taken from ``https://www.wiseq.nl/products.json?limit=250``
on 2026-10-29 and reflects what the audit reported that day: 230 live
products, 2 business-rule lines, 5 sample products, and a zero-priced
e-book that is free on purpose.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_public_site.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_public_site", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_module()


@pytest.fixture(scope="module")
def snapshot():
    path = SCRIPT.parents[1] / "data" / "public" / "public-site-audit-latest.json"
    if not path.exists():
        pytest.skip("no public-site audit snapshot captured yet")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# catalogue analysis
# ---------------------------------------------------------------------------

def test_audit_counts_the_live_catalogue(audit, snapshot):
    """The captured run saw 230 live products."""
    raw = snapshot.get("raw_catalogue")
    if not raw:
        pytest.skip("snapshot has no raw catalogue")
    result = audit.analyse_catalogue(raw)
    assert result["products"] == 230
    assert result["variants"] == 230


def test_business_rules_are_detected(audit, snapshot):
    """The B2B fee line and the school line are rules, not stock."""
    result = audit.analyse_catalogue(snapshot["raw_catalogue"])
    titles = [r["title"] for r in result["business_rules"]]
    assert "Administratie- en verzendkosten" in titles
    assert "Schoolbestelling" in titles


def test_samples_are_detected(audit, snapshot):
    result = audit.analyse_catalogue(snapshot["raw_catalogue"])
    assert len(result["samples"]) == 5
    skus = {s["sku"] for s in result["samples"]}
    assert "Sample.Kids.ANC.Black" in skus


def test_zero_price_is_split_into_free_and_unset(audit, snapshot):
    """A free e-book and a rule with no price are different situations."""
    result = audit.analyse_catalogue(snapshot["raw_catalogue"])
    kinds = {row["kind"] for row in result["zero_priced_variants"]}
    assert "free" in kinds
    assert "no_price_set" in kinds


def test_bundle_skus_are_normalised_in_the_live_catalogue(audit, snapshot):
    """The live store writes bundles as "117 + 240"."""
    result = audit.analyse_catalogue(snapshot["raw_catalogue"])
    assert any("+" in sku for sku in result["skus"])
    assert all(" + " not in sku for sku in result["skus"])


def test_free_item_is_not_counted_as_priced(audit):
    payload = {"products": [{
        "title": "Free thing",
        "product_type": "",
        "tags": [],
        "variants": [{
            "sku": "FREE.1",
            "price": "0.00",
            "compare_at_price": "19.95",
        }],
    }]}
    result = audit.analyse_catalogue(payload)
    assert result["with_price"] == 0
    assert result["zero_priced_variants"][0]["kind"] == "free"


def test_variant_without_price_is_unset(audit):
    payload = {"products": [{
        "title": "No price",
        "product_type": "",
        "tags": [],
        "variants": [{"sku": "X.1", "price": None, "compare_at_price": None}],
    }]}
    result = audit.analyse_catalogue(payload)
    assert result["zero_priced_variants"][0]["kind"] == "no_price_set"


def test_bundle_skus_are_normalised(audit):
    payload = {"products": [{
        "title": "Bundle",
        "product_type": "",
        "tags": [],
        "variants": [{"sku": "117 + 240", "price": "30.95",
                      "compare_at_price": None}],
    }]}
    result = audit.analyse_catalogue(payload)
    assert "117+240" in result["skus"]


# ---------------------------------------------------------------------------
# agents.md parsing
# ---------------------------------------------------------------------------

def test_agents_md_business_facts_are_extracted(audit):
    text = """
- Adres: Wijzend 56, 1613 KP Grootebroek, Nederland
- E-mail: info@wiseq.nl
- Telefoon: +31 (0)228 75 70 25
- KVK-nummer: 84801964
- Levergebied: Nederland en België
- Gratis verzending vanaf €15.
Betaalmethoden: iDEAL / Wero, Klarna, Visa, Mastercard, American Express, Bancontact, PayPal, Apple Pay, Google Pay, Shop Pay.
Op WiseQ-producten geldt **1 jaar garantie** op fabricagefouten.
**30 dagen bedenktijd**, gerekend vanaf de dag na ontvangst.
- Op werkdagen vóór 15:00 uur besteld wordt dezelfde dag verzonden.
- Ook te koop via: bol.com en Amazon
Agents mogen een betaling niet zelfstandig afronden.
"""
    facts = audit.analyse_agents_md(text)
    assert facts["kvk"] == "84801964"
    assert facts["email"] == "info@wiseq.nl"
    assert facts["free_shipping_threshold"] == "€15"
    assert facts["warranty"] == "1"
    assert facts["return_window"] == "30"
    assert facts["same_day_cutoff"] == "15:00"
    assert "bol.com" in facts["sales_channels"]
    assert "Amazon" in facts["sales_channels"]
    assert facts["mentions_no_self_checkout"] is True


def test_agents_md_handles_missing_facts(audit):
    facts = audit.analyse_agents_md("nothing useful here")
    assert "kvk" not in facts
    assert facts["mentions_mcp"] is False


# ---------------------------------------------------------------------------
# report rendering
# ---------------------------------------------------------------------------

def test_report_states_what_it_does_not_establish(audit, snapshot):
    report = audit.render_report(snapshot)
    assert "does not establish" in report
    assert "does not measure revenue" in report


def test_report_marks_the_observation_date(audit, snapshot):
    report = audit.render_report(snapshot)
    assert snapshot["observed"] in report


def test_report_lists_the_agent_endpoints(audit, snapshot):
    report = audit.render_report(snapshot)
    assert "api/ucp/mcp" in report
    assert "agents.md" in report


def test_blocked_checker_is_not_reported_as_a_zero_score(audit):
    """A checker that refuses us must not become "no reputation"."""
    reputation = {
        "trustpilot": {
            "url": "https://nl.trustpilot.com/review/wiseq.nl",
            "status": 403,
            "readable": False,
            "blocked": True,
            "headline": None,
        }
    }
    report = audit._render_reputation(reputation)
    body = "\n".join(report)
    assert "refused the request" in body
    assert "no reviews" not in body.lower()
    assert "0.0" not in body


def test_scamadviser_verdict_is_read_from_the_page(audit, monkeypatch):
    """The Scamadviser verdict lives in HTML-escaped embedded JSON."""
    page = (
        '<script>var d = {"hero":{"title":"Very Likely Unsafe"},'
        '"lastUpdated":{"label":"Last Update:","date":"3 months ago"},'
        '"partnerWarning":"This website has been reported to us as possible '
        "scam by &lt;a href='x'&gt;&lt;strong&gt;Webshopchecker&lt;/strong&gt;"
        '&lt;/a&gt;"};</script>'
    )

    def fake_fetch(url, timeout=45):
        if "scamadviser" in url:
            return 200, page
        return 403, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    result = audit.collect_reputation()

    scam = result["scamadviser"]
    assert scam["readable"] is True
    assert scam["headline"] == "Very Likely Unsafe"
    assert scam["reported_by"] == "Webshopchecker"
    assert scam["last_updated"] == "3 months ago"

    # The blocked ones stay blocked, with no invented headline.
    assert result["trustpilot"]["readable"] is False
    assert result["trustpilot"]["headline"] is None


def test_reputation_section_is_in_the_report(audit, monkeypatch):
    def fake_fetch(url, timeout=45):
        if "scamadviser" in url:
            return 200, '<script>{"hero":{"title":"Very Likely Unsafe"}}</script>'
        return 403, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    reputation = audit.collect_reputation()
    body = "\n".join(audit._render_reputation(reputation))
    assert "Very Likely Unsafe" in body
    assert "the checker refused the request" in body


def test_circular_flag_is_detected(audit, monkeypatch):
    """WebshopChecker's only external report IS the Scamadviser flag.

    Two sites showing the same flag must not read as two independent
    confirmations, so the audit has to say so explicitly.
    """
    page = """
    <html><body>
      <h1>wiseq.nl betrouwbaar?</h1>
      <p>1 externe melding gevonden</p>
      <p>Verdacht volgens Scamadviser</p>
      <p>Scamadviser &middot; 21-08-2026</p>
      <p>AI risicoscore: 0/100</p>
      <p>Domein 7 jaar, 9 maanden en 11 dagen oud</p>
      <p>Geen community meldingen zichtbaar</p>
      <p>Geen keurmerk gevonden</p>
      <p>Laatst gecontroleerd op 23 augustus 2026.</p>
    </body></html>
    """

    def fake_fetch(url, timeout=45):
        if "webshopchecker" in url:
            return 200, page
        return 403, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    result = audit.collect_reputation()

    wsc = result["webshopchecker"]
    assert wsc["readable"] is True
    assert wsc["external_reports"] == 1
    assert wsc["circular_with_scamadviser"] is True
    assert wsc["report_source"] == "Scamadviser"
    assert wsc["ai_risk_score"] == 0
    assert wsc["community_reports"] == 0
    assert wsc["keurmerk"] == "not found"

    body = "\n".join(audit._render_reputation(result))
    assert "not independent" in body
    assert "It is one." in body


def test_bol_archive_falls_back_to_snapshot(audit, monkeypatch):
    """web.archive.org rate-limits; the stored capture must still surface.

    Without the fallback the bol.com section would be empty on any run
    that the archive happens to refuse, and the historical figures would
    silently drop out of the report.
    """
    def fake_fetch(url, timeout=45):
        return 429, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    result = audit.collect_bol_archive()

    assert "2021-11-20" in result
    entry = result["2021-11-20"]
    assert entry["readable"] is True
    assert entry["from_snapshot"] is True
    assert entry["listings"] == 176
    assert entry["total_reviews"] == 1084
    assert entry["positivity_pct"] == "90,7"
    assert entry["seller_id"] == "1428598"
    assert entry["kvk"] == "71702830"


def test_bol_archive_separates_the_two_seller_accounts(audit, monkeypatch):
    """The two captures are DIFFERENT accounts, not one account over time.

    An earlier revision of this audit presented the two captures as a
    176 -> 203 listing growth story.  They are separate bol.com seller
    accounts with separate KvK numbers, so the report must not present
    them as a timeline and must not imply the 2021 figures are Wiseq B.V.'s.
    """
    def fake_fetch(url, timeout=45):
        return 429, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    result = audit.collect_bol_archive()

    a = result["2021-11-20"]
    b = result["2022-05-27"]
    assert a["seller_id"] != b["seller_id"]
    assert a["kvk"] != b["kvk"]

    # Only the capture carrying Wiseq B.V.'s KvK is flagged as such.
    assert b["kvk"] == audit.WISEQ_KVK
    assert b["is_wiseq_bv"] is True
    assert a["is_wiseq_bv"] is False

    body = "\n".join(audit._render_bol_archive(result))
    assert "two separate bol.com seller accounts" in body
    assert "not one account" in body
    # The identity split must be spelled out, with both KvK numbers.
    assert audit.WISEQ_KVK in body
    assert "71702830" in body
    assert "Wiseq B.V." in body


def test_bol_archive_never_renders_a_growth_series(audit, monkeypatch):
    """A reader scanning two dated rows must not infer a trend.

    Guard the specific wording that produced the false story: a
    "growth"-style framing, or the word "history" implying one account.
    """
    def fake_fetch(url, timeout=45):
        return 429, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    body = "\n".join(audit._render_bol_archive(audit.collect_bol_archive())).lower()
    assert "seller history" not in body
    for phrase in ("grew", "growth", "increased", "rose from"):
        assert phrase not in body, f"timeline wording leaked: {phrase!r}"


def test_bol_archive_keeps_the_three_metrics_distinct(audit, monkeypatch):
    """Product reviews, seller score and aggregator rating are not one metric."""
    def fake_fetch(url, timeout=45):
        return 429, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    body = "\n".join(audit._render_bol_archive(audit.collect_bol_archive()))
    assert "must not be mixed" in body
    assert "Product reviews" in body
    assert "Seller score" in body


def test_bol_archive_section_labels_itself_historical(audit, monkeypatch):
    """A listing count without its date reads as current. Guard that."""
    def fake_fetch(url, timeout=45):
        return 429, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    body = "\n".join(audit._render_bol_archive(audit.collect_bol_archive()))
    assert "historical" in body.lower()
    assert "archived" in body.lower()


def test_bol_archive_reports_an_unretrievable_capture_as_such(audit, monkeypatch):
    """A blocked archive must never be rendered as a zero listing count."""
    def fake_fetch(url, timeout=45):
        return 503, ""

    monkeypatch.setattr(audit, "fetch", fake_fetch)
    monkeypatch.setattr(audit, "_bol_snapshot", lambda: {})
    body = "\n".join(audit._render_bol_archive(audit.collect_bol_archive()))
    assert "not retrievable" in body
    assert "| - |" in body


def test_bol_page_parser_reads_identity_and_metrics(audit):
    """The parser must pull KvK, seller id and the rolling score.

    The rolling 3-month seller score is a different metric from the
    product-review counters; mixing them is how wrong numbers travel.
    """
    page = """
    <html><body>
      <p>Actief sinds: 5 juni 2018</p>
      <p>Handelsnaam</p><p>WISEQ NL</p>
      <p>KvK-nummer</p><p>84801964</p>
      <p>Btw-nummer</p><p>NL863378201B01</p>
      <p>Beoordeling</p><p>8,5</p>
      <p>Afgelopen 3 maanden:</p><p>122 beoordelingen</p>
      <p>93,8% positieve beoordelingen</p>
      <p>Alle beoordelingen (864)</p>
      <p>Positieve beoordelingen (776)</p>
      <p>Negatieve beoordelingen (37)</p>
      <p>Neutrale beoordelingen (51)</p>
      <p>Over de verkoper</p><p>Aanbod</p><p>(203)</p>
      <a href="https://www.bol.com/nl/nl/v/wiseq-nl/1357877/">x</a>
    </body></html>
    """
    got = audit._parse_bol_page(page)
    assert got["kvk"] == "84801964"
    assert got["btw"] == "NL863378201B01"
    assert got["seller_id"] == "1357877"
    assert got["active_since"] == "5 juni 2018"
    assert got["listings"] == 203
    assert got["total_reviews"] == 864
    assert got["positivity_pct"] == "93,8"
    # The seller score is its own metric and must be keyed separately.
    assert got["seller_score"] == "8,5"
    assert got["reviews_last_3_months"] == 122
