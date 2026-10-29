"""The integration catalogue must turn research into an actionable backlog."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiseq.agents.integration_catalogue import (
    ALREADY_COVERED,
    LANE_PURPOSE,
    IntegrationCatalogueAgent,
    score_candidate,
)
from wiseq.db.db import Database


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path/'t.db'}")
    d.init_schema()
    return d


@pytest.fixture()
def repo(tmp_path):
    """A minimal stand-in for the client repository's data/oss directory."""
    oss = tmp_path / "data" / "oss"
    oss.mkdir(parents=True)
    (oss / "bol-com.json").write_text(json.dumps({
        "query": "bol.com+api",
        "total_count": 64,
        "items": [
            {"full_name": "picqer/bol-retailer-php-client",
             "url": "https://github.com/picqer/bol-retailer-php-client",
             "stars": 29, "lang": "PHP", "desc": "PHP Client for bol.com"},
            {"full_name": "BarstWardenburg/bol-mcp",
             "url": "https://github.com/x/bol-mcp", "stars": 5,
             "lang": "TypeScript",
             "desc": "MCP server for bol.com Retailer API automation"},
            {"full_name": "pennersr/python-bol-api",
             "url": "https://github.com/pennersr/python-bol-api",
             "stars": 13, "lang": "Python", "desc": "A wrapper for the bol.com API"},
        ],
    }), encoding="utf-8")
    (oss / "ean-gs1.json").write_text(json.dumps({
        "query": "ean+gs1", "total_count": 10,
        "items": [
            {"full_name": "gs1/gs1-toolkit", "url": "u", "stars": 900,
             "lang": "Python", "desc": "GS1 barcode toolkit with OpenAPI"},
        ],
    }), encoding="utf-8")
    (oss / "broken.json").write_text("{not json", encoding="utf-8")
    return tmp_path


# -- scoring ----------------------------------------------------------
def test_python_scores_above_non_python():
    py = score_candidate({"full_name": "a/b", "lang": "Python", "stars": 10})
    php = score_candidate({"full_name": "c/d", "lang": "PHP", "stars": 10})
    assert py["score"] > php["score"]


def test_mcp_candidate_scores_above_plain_one():
    mcp = score_candidate({"full_name": "a/b-mcp", "lang": "Python", "stars": 10,
                           "desc": "MCP server for bol.com"})
    plain = score_candidate({"full_name": "a/b", "lang": "Python", "stars": 10,
                             "desc": "A library for bol.com"})
    assert mcp["score"] > plain["score"]


def test_openapi_hint_is_detected():
    s = score_candidate({"full_name": "a/b", "lang": "Python", "stars": 1,
                         "desc": "generated from an OpenAPI spec"})
    assert any("OpenAPI" in r for r in s["reasons"])


def test_stars_use_log_scale():
    """A 300-star project must not erase a 30-star one."""
    small = score_candidate({"full_name": "a/b", "lang": "Python", "stars": 30})
    big = score_candidate({"full_name": "c/d", "lang": "Python", "stars": 300})
    assert big["score"] - small["score"] < 1.5


def test_missing_stars_do_not_crash():
    s = score_candidate({"full_name": "a/b", "lang": None, "stars": None})
    assert s["score"] >= 0


# -- lane loading -----------------------------------------------------
def test_lanes_are_loaded_with_provenance(repo, db):
    agent = IntegrationCatalogueAgent(db, repo=repo)
    lanes = agent.load_lanes()
    names = {l["lane"] for l in lanes}
    assert "bol-com" in names
    assert "ean-gs1" in names


def test_malformed_json_is_skipped_not_fatal(repo, db):
    agent = IntegrationCatalogueAgent(db, repo=repo)
    lanes = agent.load_lanes()
    assert "broken" not in {l["lane"] for l in lanes}


def test_missing_oss_dir_yields_no_lanes(tmp_path, db):
    agent = IntegrationCatalogueAgent(db, repo=tmp_path)
    assert agent.load_lanes() == []


def test_no_repo_yields_no_lanes(db):
    assert IntegrationCatalogueAgent(db, repo=None).load_lanes() == []


# -- backlog ----------------------------------------------------------
def test_backlog_counts_lanes_and_candidates(repo, db):
    b = IntegrationCatalogueAgent(db, repo=repo).build_backlog()
    assert b["lanes"] == 2
    assert b["candidates"] == 4


def test_uncovered_lanes_are_counted(repo, db):
    b = IntegrationCatalogueAgent(db, repo=repo).build_backlog()
    # bol-com is covered by the replica, ean-gs1 is not.
    assert b["uncovered_lanes"] == 1


def test_every_candidate_keeps_its_provenance(repo, db):
    b = IntegrationCatalogueAgent(db, repo=repo).build_backlog()
    lane = next(x for x in b["backlog"] if x["lane"] == "bol-com")
    top = lane["top"][0]
    assert top["provenance_query"]
    assert top["lane"] == "bol-com"


def test_uncovered_lanes_rank_first(repo, db):
    b = IntegrationCatalogueAgent(db, repo=repo).build_backlog()
    assert b["backlog"][0]["already_covered"] is None


def test_backlog_is_audited(repo, db):
    IntegrationCatalogueAgent(db, repo=repo).build_backlog()
    rows = db.query("SELECT action FROM audit_log WHERE action='integration_backlog_built'")
    assert len(rows) == 1


def test_lane_purpose_covers_every_known_lane():
    """A lane with no purpose text is a research lane nobody can act on."""
    for lane in ("bol-com", "ean-gs1", "accounting", "helpdesk"):
        assert lane in LANE_PURPOSE


def test_covered_lanes_reference_real_lanes():
    for lane in ALREADY_COVERED:
        assert lane in LANE_PURPOSE


# -- decision gate ----------------------------------------------------
def test_request_decision_creates_an_approval(repo, db):
    aid = IntegrationCatalogueAgent(db, repo=repo).request_decision()
    row = db.query_one("SELECT * FROM approvals WHERE approval_id=?", (aid,))
    assert row is not None
    assert row["status"] == "pending"
    assert row["action_type"] == "integration_backlog_review"


def test_request_decision_installs_nothing(repo, db):
    """The backlog must not trigger any external side effect."""
    before = db.query("SELECT COUNT(*) AS n FROM approvals")[0]["n"]
    IntegrationCatalogueAgent(db, repo=repo).request_decision()
    after = db.query("SELECT COUNT(*) AS n FROM approvals")[0]["n"]
    assert after == before + 1


def test_request_decision_payload_names_top_lanes(repo, db):
    aid = IntegrationCatalogueAgent(db, repo=repo).request_decision()
    payload = json.loads(
        db.query_one("SELECT payload FROM approvals WHERE approval_id=?",
                     (aid,))["payload"])
    assert payload["lanes"] == 2
    assert payload["top_lanes"]


def test_real_repository_lanes_are_all_classified(db):
    """Guard against a new research lane landing without a purpose."""
    real = Path(__file__).resolve().parents[1] / "data" / "wiseq-repo"
    oss = real / "data" / "oss"
    if not oss.exists():
        pytest.skip("client repository not present in this checkout")
    for path in oss.glob("*.json"):
        assert path.stem in LANE_PURPOSE, f"{path.stem} has no purpose text"
