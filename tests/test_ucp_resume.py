"""Tests for the resumable UCP catalogue scan.

The storefront rate-limits a full catalogue scan, and its back-off window
is measured in tens of minutes.  A scan that discards the prices it
already fetched has to start over every time, which keeps tripping the
limit.  The resumable scan remembers its progress and asks only for the
SKUs it never got.
"""
from __future__ import annotations

import json

import pytest

from wiseq.connectors.ucp_scan import ScanProgress, ScanStore, default_store_path


def test_progress_starts_empty():
    progress = ScanProgress()
    assert progress.resolved == {}
    assert progress.not_found == []
    assert progress.failed == []
    assert progress.runs == 0


def test_pending_skips_work_already_done():
    progress = ScanProgress()
    progress.resolved["1"] = 10.0
    progress.not_found.append("2")
    assert progress.pending(["1", "2", "4"]) == ["4"]


def test_pending_retries_failed_skus():
    """A transient failure must not drop a product from the catalogue."""
    progress = ScanProgress()
    progress.failed.append("3")
    assert progress.pending(["3", "4"]) == ["3", "4"]


def test_pending_does_not_retry_not_found():
    """A product the catalogue genuinely lacks must not be re-asked."""
    progress = ScanProgress()
    progress.not_found.append("2")
    assert progress.pending(["2"]) == []


def test_store_round_trips(tmp_path):
    path = tmp_path / "scan.json"
    store = ScanStore(path)
    progress = ScanProgress()
    progress.resolved["231"] = 18.95
    progress.titles["231"] = "Draadloze Oplader"
    progress.not_found.append("999")
    store.save(progress)

    loaded = store.load()
    assert loaded.resolved == {"231": 18.95}
    assert loaded.titles["231"] == "Draadloze Oplader"
    assert loaded.not_found == ["999"]
    assert loaded.updated_at


def test_store_writes_atomically(tmp_path):
    """A crash mid-write must not leave a corrupt progress file."""
    path = tmp_path / "scan.json"
    store = ScanStore(path)
    progress = ScanProgress()
    progress.resolved["1"] = 1.0
    store.save(progress)

    # No temp files left behind.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    # And the file on disk is valid JSON.
    json.loads(path.read_text(encoding="utf-8"))


def test_store_recovers_from_corrupt_file(tmp_path):
    """A corrupt progress file must not stop a scan."""
    path = tmp_path / "scan.json"
    path.write_text("{not json at all", encoding="utf-8")
    progress = ScanStore(path).load()
    assert progress.resolved == {}


def test_store_recovers_from_wrong_shape(tmp_path):
    path = tmp_path / "scan.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    progress = ScanStore(path).load()
    assert progress.resolved == {}


def test_default_store_path_for_sqlite():
    class _DB:
        database_url = "sqlite:///./wiseq.db"

    assert default_store_path(_DB()).name == "wiseq.ucp_scan.json"


def test_default_store_path_falls_back():
    class _DB:
        pass

    assert default_store_path(_DB()).name == "wiseq.ucp_scan.json"


# -- the connector's resume behaviour -------------------------------------

class _Product:
    def __init__(self, price, title="T"):
        self.price_min = price
        self.title = title


class _FakeClient:
    """A UCP client that resolves a fixed set and can be rate limited."""

    endpoint = "http://example.invalid/ucp"

    def __init__(self, prices, rate_limit_after=None):
        self.prices = prices
        self.calls: list[str] = []
        self.rate_limit_after = rate_limit_after

    def initialize(self):
        return {}

    def get_product(self, identifier):
        self.calls.append(identifier)
        if self.rate_limit_after is not None and len(self.calls) > self.rate_limit_after:
            from wiseq.connectors.ucp import UCPRateLimited

            raise UCPRateLimited("Rate limit exceeded [Too many requests]", 120)
        if identifier not in self.prices:
            return None
        return _Product(self.prices[identifier])


class _FakeDB:
    def __init__(self):
        self.executed = []

    def query(self, sql, params=()):
        return []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))


def test_resume_does_not_requery_resolved_skus(tmp_path):
    """After a rate limit, the next run asks only for the remaining SKUs."""
    from wiseq.connectors.ucp import sync_ucp_catalog

    path = tmp_path / "scan.json"
    prices = {str(i): 10.0 + i for i in range(1, 6)}

    # First run: resolves 1-3, then trips the limit on the 4th call.
    client1 = _FakeClient(prices, rate_limit_after=3)
    report1 = sync_ucp_catalog(
        db=_FakeDB(), client=client1,
        skus=[str(i) for i in range(1, 6)],
        load_into_db=False, resume=True, progress_path=path,
    )
    assert report1["rate_limited"] is True
    assert report1["resolved"] == 3
    assert report1["complete"] is False
    assert report1["remaining"] == 2

    # Second run: the client resolves everything, but the scan must only
    # ASK about the SKUs it never resolved.
    client2 = _FakeClient(prices)
    report2 = sync_ucp_catalog(
        db=_FakeDB(), client=client2,
        skus=[str(i) for i in range(1, 6)],
        load_into_db=False, resume=True, progress_path=path,
    )
    assert report2["requested_this_run"] == 2
    assert sorted(client2.calls) == ["4", "5"]
    assert report2["resolved"] == 5
    assert report2["complete"] is True
    assert report2["runs"] == 2


def test_without_resume_a_rerun_requeries_everything(tmp_path):
    """Without resume, behaviour is unchanged: every SKU is asked again."""
    from wiseq.connectors.ucp import sync_ucp_catalog

    path = tmp_path / "scan.json"
    prices = {"1": 10.0, "2": 20.0}
    client = _FakeClient(prices)
    report = sync_ucp_catalog(
        db=_FakeDB(), client=client, skus=["1", "2"],
        load_into_db=False, progress_path=path,
    )
    assert sorted(client.calls) == ["1", "2"]
    assert report["requested_this_run"] == 2
    assert report["resumable"] is False


def test_progress_persists_across_a_new_store(tmp_path):
    """Progress survives a process restart."""
    from wiseq.connectors.ucp import sync_ucp_catalog

    path = tmp_path / "scan.json"
    prices = {"1": 10.0, "2": 20.0}
    # Resolve only the first SKU, then hit the limit.
    client = _FakeClient(prices, rate_limit_after=1)
    sync_ucp_catalog(db=_FakeDB(), client=client, skus=["1", "2"],
                     load_into_db=False, resume=True, progress_path=path)

    # A completely new store object, as a fresh process would build.
    fresh = ScanStore(path).load()
    assert fresh.resolved == {"1": 10.0}
    # SKU 2 was never resolved, so it is still pending.
    assert fresh.pending(["1", "2"]) == ["2"]


# -- the synthetic-price mismatch rule -------------------------------------

class _DBWithPrice:
    """A database stub that reports a stored price for one SKU."""

    def __init__(self, price_eur, synthetic_price):
        self._price = price_eur
        self._synthetic = synthetic_price

    def query(self, sql, params=()):
        if "FROM products" in sql:
            return [{"price_eur": self._price, "synthetic_price": self._synthetic}]
        return []

    def execute(self, sql, params=()):
        return None


def test_synthetic_placeholder_is_not_a_mismatch():
    """A seeded placeholder price must not be reported as a mismatch."""
    from wiseq.connectors.ucp import sync_ucp_catalog

    db = _DBWithPrice(20.34, 1)
    report = sync_ucp_catalog(
        db=db, client=_FakeClient({"1": 7.95}), skus=["1"],
        load_into_db=False,
    )
    assert report["price_mismatches"] == []
    assert report["resolved"] == 1


def test_real_price_difference_is_a_mismatch():
    """A genuine published price that disagrees IS a mismatch."""
    from wiseq.connectors.ucp import sync_ucp_catalog

    db = _DBWithPrice(20.34, 0)
    report = sync_ucp_catalog(
        db=db, client=_FakeClient({"1": 7.95}), skus=["1"],
        load_into_db=False,
    )
    assert len(report["price_mismatches"]) == 1
    assert report["price_mismatches"][0]["catalogue_price"] == 20.34
    assert report["price_mismatches"][0]["ucp_price"] == 7.95
    assert report["price_mismatches"][0]["synthetic_catalogue_price"] is False
