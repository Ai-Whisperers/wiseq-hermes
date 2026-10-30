"""Tests for the UCP/Shopify price parity checker.

The comparison logic is what protects the offer path: a price that
disagrees between the storefront catalogue and the storefront's own UCP
endpoint silently corrupts a quote.  These tests pin the normalisation
and the strictness (a missing price is never a match).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_ucp_parity import _eur, _load_resolved, check  # noqa: E402

PUBLIC = ROOT / "data" / "public"


class TestEurNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("12.95", 12.95),
            ("12,95", 12.95),
            ("€ 12.95", 12.95),
            ("€12,95", 12.95),
            (" 16.95 ", 16.95),
            (11.5, 11.5),
            (7, 7.0),
        ],
    )
    def test_parses_every_price_shape(self, raw, expected):
        assert _eur(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "not-a-price", "???"])
    def test_unparseable_is_none_not_zero(self, raw):
        # A zero would compare equal to a zero-priced catalogue row and
        # produce a false match.
        assert _eur(raw) is None

    def test_rounds_to_cents(self):
        assert _eur("12.954") == 12.95
        assert _eur("12.9551") == 12.96


class TestCheck:
    def test_identical_prices_match(self):
        result = check({"101": 7.95}, {"101": {"price": 7.95}})
        assert result["matched"] == ["101"]
        assert result["mismatched"] == []
        assert result["unusable"] == []

    def test_string_and_numeric_prices_match(self):
        result = check({"101": 7.95}, {"101": {"price": "7.95"}})
        assert result["matched"] == ["101"]

    def test_euro_string_matches(self):
        result = check({"101": 7.95}, {"101": {"price": "€ 7,95"}})
        assert result["matched"] == ["101"]

    def test_differing_price_is_a_mismatch(self):
        result = check({"101": 7.95}, {"101": {"price": 8.95}})
        assert result["matched"] == []
        assert result["mismatched"][0][0] == "101"

    def test_bundle_sku_is_compared_by_its_own_key(self):
        # "111+216" is a real bundle SKU and must not be folded into 111.
        result = check({"111+216": 16.95}, {"111+216": {"price": 16.95}})
        assert result["matched"] == ["111+216"]

    def test_sku_missing_from_catalogue_is_unusable_not_a_match(self):
        result = check({}, {"999": {"price": 5.0}})
        assert result["matched"] == []
        assert result["unusable"][0][0] == "999"
        assert result["unusable"][0][1] == "not_in_catalogue"

    def test_missing_ucp_price_is_unusable_not_a_match(self):
        result = check({"101": 7.95}, {"101": {"price": None}})
        assert result["matched"] == []
        assert result["unusable"][0][1] == "no_ucp_price"

    def test_zero_catalogue_price_does_not_match_a_real_price(self):
        result = check({"101": 0.0}, {"101": {"price": 7.95}})
        assert result["matched"] == []
        assert len(result["mismatched"]) == 1

    def test_bare_scalar_entry_is_accepted(self):
        # The scan file has been written with both shapes over time.
        result = check({"101": 7.95}, {"101": 7.95})
        assert result["matched"] == ["101"]

    def test_totals_cover_every_resolved_sku(self):
        catalogue = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0}
        resolved = {
            "1": {"price": 1.0},
            "2": {"price": 9.9},   # mismatch
            "3": {"price": None},  # unusable
            "5": {"price": 5.0},   # not in catalogue
        }
        result = check(catalogue, resolved)
        assert result["total"] == 4
        assert len(result["matched"]) == 1
        assert len(result["mismatched"]) == 1
        assert len(result["unusable"]) == 2


class TestSnapshotLoading:
    def test_reads_the_live_progress_shape(self, tmp_path):
        path = tmp_path / "scan.json"
        path.write_text('{"resolved": {"101": 7.95}}', encoding="utf-8")
        assert _load_resolved(path) == {"101": 7.95}

    def test_reads_the_committed_snapshot_shape(self, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text('{"prices": {"101": 7.95}}', encoding="utf-8")
        assert _load_resolved(path) == {"101": 7.95}

    def test_empty_file_is_an_error(self, tmp_path):
        path = tmp_path / "scan.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError):
            _load_resolved(path)


class TestCommittedSnapshots:
    """The committed snapshots must agree with each other.

    This is the offline proof of the same invariant the live parity check
    proves: the storefront's UCP prices and the storefront's own catalogue
    prices are the same numbers.
    """

    def _load(self, name):
        import json
        return json.loads((PUBLIC / name).read_text(encoding="utf-8"))

    def test_ucp_price_snapshot_exists_and_is_complete(self):
        data = self._load("ucp-price-snapshot.json")
        prices = data["prices"]
        assert data["resolved_count"] == 139
        assert len(prices) == 139
        assert not data["not_found"]
        assert not data["failed"]

    def test_catalogue_price_snapshot_exists_and_is_complete(self):
        data = self._load("catalogue-price-snapshot.json")
        assert data["product_count"] == 139
        assert len(data["prices"]) == 139

    def test_the_two_snapshots_agree_to_the_cent(self):
        ucp = self._load("ucp-price-snapshot.json")["prices"]
        catalogue = self._load("catalogue-price-snapshot.json")["prices"]
        assert set(ucp) == set(catalogue)
        mismatched = {
            sku: (catalogue[sku], ucp[sku])
            for sku in ucp
            if round(float(catalogue[sku]), 2) != round(float(ucp[sku]), 2)
        }
        assert mismatched == {}, f"price drift between snapshots: {mismatched}"

    def test_no_price_is_zero_or_negative(self):
        for name in ("ucp-price-snapshot.json", "catalogue-price-snapshot.json"):
            for sku, price in self._load(name)["prices"].items():
                assert float(price) > 0, f"{name}:{sku} has a non-positive price"
