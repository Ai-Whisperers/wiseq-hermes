"""Tests for the MCP connector review tool.

The review exists to stop a connector being installed on the strength of
a star count alone.  Its verdict logic is what a human acts on, so the
verdict rules are tested here rather than left to a live API call.

No test touches the network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import review_mcp_candidates as rmc  # noqa: E402


def _review(meta: dict, lane: str = "seo-audit") -> dict:
    """Run the verdict logic over a fake GitHub payload."""
    return _review_with(meta, lane)


def _review_with(meta: dict, lane: str) -> dict:
    """Call the pure part of review() with a stubbed API."""
    original = rmc.api_get
    rmc.api_get = lambda path, token: meta
    try:
        return rmc.review("owner/repo", lane, None)
    finally:
        rmc.api_get = original


def _meta(**kwargs) -> dict:
    base = {
        "html_url": "https://github.com/owner/repo",
        "license": {"spdx_id": "MIT"},
        "stargazers_count": 100,
        "pushed_at": "2026-10-01T00:00:00Z",
        "archived": False,
        "open_issues_count": 2,
        "has_issues": True,
        "description": "a connector",
    }
    base.update(kwargs)
    return base


def test_permissive_licence_and_fresh_push_is_usable():
    row = _review(_meta())
    assert row["verdict"] == "USABLE"
    assert row["license"] == "MIT"
    assert row["risks"] == []


def test_no_licence_is_blocking():
    """All rights are reserved by default -- that must block."""
    row = _review(_meta(license=None))
    assert row["verdict"] == "REVIEW_REQUIRED"
    assert any("NO LICENCE" in r for r in row["risks"])


def test_noassertion_licence_is_blocking():
    row = _review(_meta(license={"spdx_id": "NOASSERTION"}))
    assert row["verdict"] == "REVIEW_REQUIRED"
    assert any("NO LICENCE" in r for r in row["risks"])


def test_copyleft_licence_needs_a_read():
    row = _review(_meta(license={"spdx_id": "GPL-3.0"}))
    assert row["verdict"] == "REVIEW_REQUIRED"
    assert any("copyleft" in r for r in row["risks"])


def test_archived_repository_is_blocking():
    row = _review(_meta(archived=True))
    assert row["verdict"] == "REVIEW_REQUIRED"
    assert any("archived" in r for r in row["risks"])


def test_stale_push_is_a_caution_not_a_block():
    row = _review(_meta(pushed_at="2015-01-01T00:00:00Z"))
    assert row["verdict"] == "USABLE_WITH_CAUTION"
    assert any("stale" in r for r in row["risks"])


def test_fresh_push_is_not_a_caution():
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    row = _review(_meta(pushed_at=recent))
    assert not any("stale" in r for r in row["risks"])


def test_high_risk_lane_always_needs_a_credential_warning():
    row = _review(_meta(), lane="bol-com")
    assert row["high_risk_lane"] is True
    assert any("revocable credential" in r for r in row["risks"])


def test_low_risk_lane_has_no_credential_warning():
    row = _review(_meta(), lane="seo-audit")
    assert row["high_risk_lane"] is False
    assert not any("revocable credential" in r for r in row["risks"])


def test_unfetchable_repository_is_unknown_not_usable():
    """A failed lookup must never read as a pass."""
    row = _review_with({"__error__": "HTTP 404"}, "seo-audit")
    assert row["verdict"] == "UNKNOWN"
    assert "error" in row


def test_days_since_reads_iso_timestamps():
    assert rmc.days_since("2026-10-01T00:00:00Z") is not None
    assert rmc.days_since("") is None
    assert rmc.days_since("not a date") is None


def test_render_produces_a_table_with_every_review():
    result = {
        "observed": "2026-10-30",
        "lanes_reviewed": 1,
        "connectors_reviewed": 1,
        "verdict_counts": {"USABLE": 1},
        "reviews": [{
            "repo": "owner/repo", "lane": "seo-audit", "license": "MIT",
            "days_since_push": 10, "verdict": "USABLE", "risks": [],
        }],
    }
    report = rmc.render(result)
    assert "owner/repo" in report
    assert "USABLE" in report
    assert "| Verdict | Connectors |" in report


def test_render_explains_every_verdict():
    result = {
        "observed": "2026-10-30", "lanes_reviewed": 0, "connectors_reviewed": 0,
        "verdict_counts": {}, "reviews": [],
    }
    report = rmc.render(result)
    for verdict in ("USABLE", "USABLE_WITH_CAUTION", "REVIEW_REQUIRED", "UNKNOWN"):
        assert verdict in report
