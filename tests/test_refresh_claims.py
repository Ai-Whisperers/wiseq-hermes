"""Tests for the claims-ledger freshness checker.

The point of this tool is that a stale claim can never quietly read as a
verified one.  Its verdict logic is therefore tested against fixtures --
no test touches the network.

The fixtures are trimmed copies of what the live pages actually return,
including the awkward bits: a score wrapped in markup, a Trustpilot
profile carrying two different ratings, and a page that is simply not
there.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import refresh_claims as rc  # noqa: E402


# --------------------------------------------------------------------------
# fixtures -- trimmed shapes of the real pages
# --------------------------------------------------------------------------
TRUSTPILOT_HTML = """
<html><body>
<div class="reviews"><span>25</span> reviews</div>
<p>TrustScore 4.5 uit 5</p>
<p class="rating">4,4</p>
<p>[sheeva immens Geüpdatet op 22 sep 2026]</p>
<p>[Anneke 27 sep 2026]</p>
</body></html>
"""

SCAMADVISER_HTML = """
<html><body><script>var x = {"trustScoreText":"Trust Score"};</script>
<div class="trust-score">
  <div class="result-page-text-tile-title-regular">Trust Score</div>
  <span class="text-heading-section-700">0</span>
</div>
<div class="hero"><h1>Very Likely Unsafe</h1></div>
<p>This website has been reported to us as possible scam by
<a href="http://www.webshopchecker.nl"><strong>Webshopchecker</strong></a></p>
<p>This website hasn't been scanned in more than 30 days ago.</p>
</body></html>
"""

BOL_HTML = '<html><body><p>312 resultaten</p></body></html>'


# --------------------------------------------------------------------------
# visible_text
# --------------------------------------------------------------------------
def test_visible_text_drops_scripts_and_tags():
    html = "<div>Trust Score</div><script>var secret = 1;</script><span>0</span>"
    text = rc.visible_text(html)
    assert "Trust Score" in text
    assert "secret" not in text
    assert "<" not in text


def test_visible_text_unescapes_entities():
    assert "&amp;" not in rc.visible_text("a &amp; b")
    assert "€" in rc.visible_text("&euro; 10") or "10" in rc.visible_text("&euro; 10")


# --------------------------------------------------------------------------
# checkers
# --------------------------------------------------------------------------
def test_trustpilot_reads_count_score_and_latest_review():
    obs = rc._trustpilot(TRUSTPILOT_HTML)
    assert obs.ok
    assert obs.fields["reviews"] == "25"
    assert obs.fields["trust_score"] == "4.5"
    assert obs.fields["latest_review"] == "27 sep 2026"


def test_trustpilot_keeps_the_two_ratings_apart():
    """4.4 (displayed) and 4.5 (TrustScore) are different numbers."""
    obs = rc._trustpilot(TRUSTPILOT_HTML)
    assert obs.fields["displayed_rating"] != obs.fields["trust_score"]
    assert obs.fields["displayed_rating"] == "4.4"


def test_scamadviser_reads_score_through_the_markup():
    """The score sits between two spans -- a raw-HTML regex misses it."""
    obs = rc._scamadviser(SCAMADVISER_HTML)
    assert obs.ok
    assert obs.fields["trust_score"] == "0"
    assert obs.fields["verdict"] == "Very Likely Unsafe"
    assert "Webshopchecker" in obs.fields["reporter"]


def test_bol_reads_the_listing_count():
    obs = rc._bol_count(BOL_HTML)
    assert obs.ok
    assert obs.fields["count"] == "312"


def test_checker_on_an_empty_page_is_not_ok():
    obs = rc._trustpilot("<html><body>nothing here</body></html>")
    assert not obs.ok


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
def _claim(**kwargs) -> rc.Claim:
    base = dict(number=1, text="Trustpilot: 25 reviews 4.4/5", status="STALE",
                checker="trustpilot")
    base.update(kwargs)
    return rc.Claim(**base)


def test_matching_values_agree():
    claim = _claim(expected={"reviews": "25", "displayed_rating": "4.4",
                             "trust_score": "4.5"})
    obs = rc._trustpilot(TRUSTPILOT_HTML)
    verdict, detail = rc.compare(claim, obs)
    assert verdict == "AGREE"
    assert "reviews=25" in detail


def test_a_changed_number_is_reported_as_changed():
    claim = _claim(expected={"reviews": "13"})
    verdict, detail = rc.compare(claim, rc._trustpilot(TRUSTPILOT_HTML))
    assert verdict == "CHANGED"
    assert "13" in detail


def test_one_changed_field_makes_the_whole_claim_changed():
    """Partial agreement must not pass as agreement."""
    claim = _claim(expected={"reviews": "25", "trust_score": "4.9"})
    verdict, _ = rc.compare(claim, rc._trustpilot(TRUSTPILOT_HTML))
    assert verdict == "CHANGED"


def test_a_missing_field_is_unreachable_not_agreement():
    """If the page no longer shows the value, that is not a pass."""
    claim = _claim(expected={"reviews": "25", "nonexistent": "x"})
    verdict, detail = rc.compare(claim, rc._trustpilot(TRUSTPILOT_HTML))
    assert verdict == "UNREACHABLE"
    assert "nonexistent" in detail


def test_a_claim_with_no_comparable_value_is_reported_honestly():
    verdict, detail = rc.compare(_claim(expected={}), rc._trustpilot(TRUSTPILOT_HTML))
    assert verdict == "AGREE"
    assert "no machine-comparable" in detail


def test_comparison_ignores_number_formatting():
    claim = _claim(expected={"displayed_rating": "4.4"})
    obs = rc.Observation("trustpilot", "x", {"displayed_rating": "4,4"}, True)
    assert rc.compare(claim, obs)[0] == "AGREE"


def test_a_failed_fetch_is_never_agreement():
    claim = _claim(expected={"reviews": "25"})

    def boom(url, timeout=30):
        return False, "HTTP 403"

    original = rc.fetch
    rc.fetch = boom
    try:
        result = rc.check(claim)
    finally:
        rc.fetch = original
    assert result.verdict == "UNREACHABLE"
    assert result.verdict != "AGREE"


# --------------------------------------------------------------------------
# ledger parsing
# --------------------------------------------------------------------------
LEDGER = """
# Claim ledger

| # | Claim | Status | Source | Scope | Reproduce |
|---|---|---|---|---|---|
| 4 | bol listing count 312 vs 230 own-shop SKUs | **STALE** | src | note | cmd |
| 6 | Scamadviser TrustScore 0 flag on the domain | **STALE** | src | note | cmd |
| 8 | Thuiswinkel Waarborg cost EUR 983-1,759/yr | **INFERRED** | src | note | cmd |
| 12 | Some unrelated internal claim | **VERIFIED** | src | note | cmd |
| 47 | Trustpilot still 13 reviews / 4.5 / organic-only | **VERIFIED** | src | note | cmd |
"""


def test_ledger_parsing_finds_only_machine_checkable_rows():
    claims = rc.build_claims(LEDGER)
    numbers = {c.number for c in claims}
    assert numbers == {4, 6, 8, 47}
    assert 12 not in numbers  # no checker exists for it


def test_ledger_parsing_reads_the_asserted_values():
    claims = {c.number: c for c in rc.build_claims(LEDGER)}
    assert claims[6].expected["trust_score"] == "0"
    assert claims[4].expected["count"] == "312"
    assert claims[47].expected["reviews"] == "13"


def test_ledger_parsing_ignores_duplicate_numbers():
    doubled = LEDGER + "| 4 | bol listing count 999 | **STALE** | s | n | c |\n"
    claims = rc.build_claims(doubled)
    assert [c.number for c in claims].count(4) == 1


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def test_render_explains_every_verdict():
    result = {
        "observed": "2026-10-30", "lanes_reviewed": 0, "connectors_reviewed": 0,
        "verdict_counts": {}, "reviews": [],
    }
    report = rc.render([], "ledger.md", "2026-10-30")
    for verdict in ("AGREE", "CHANGED", "UNREACHABLE", "NO_CHECKER"):
        assert verdict in report


def test_render_lists_rows_needing_a_decision():
    claim = _claim(expected={"reviews": "13"})
    result = rc.CheckResult(claim, rc._trustpilot(TRUSTPILOT_HTML), "CHANGED", "13 vs 25")
    report = rc.render([result], "ledger.md", "2026-10-30")
    assert "Rows needing a decision" in report
    assert "13" in report


def test_render_states_that_it_does_not_edit_the_ledger():
    report = rc.render([], "ledger.md", "2026-10-30")
    assert "does not edit" in report
