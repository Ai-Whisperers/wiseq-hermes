"""The human approval gate must actually work.

`POST /approvals/<id>` is the single most important write in this
system: it is how a human approves an offer, a price change, an
external message.  If it fails, every consequential action in the
replica is stuck behind an approval nobody can clear.

A regression once removed `decided_by` from the `ApprovalIn` request
model while the endpoint still read it, so every call answered 500.
The route was never exercised by the unit suite -- only by the shell
smoke script, which is not part of `pytest`.  These tests pin the
route's contract so that class of break fails the build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from wiseq import api as api_mod  # noqa: E402
from wiseq import config as config_mod  # noqa: E402
from wiseq.db.db import Database  # noqa: E402

TOKEN = "pytest-approval-token"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", TOKEN)
    monkeypatch.delenv("WISEQ_ADMIN_TOKEN", raising=False)
    # get_orchestrator() builds the database from the settings, so the
    # settings are what has to point at the temp file.
    monkeypatch.setenv("WISEQ_DATABASE_URL", f"sqlite:///{tmp_path/'approvals.db'}")

    api_mod._db = None
    api_mod._orch = None
    api_mod._registry = None
    # get_settings() caches too, and it is what carries the database URL.
    config_mod._settings = None

    try:
        with TestClient(api_mod.app) as c:
            yield c
    finally:
        # get_orchestrator() caches the orchestrator globally, so without
        # this the next test would reuse the previous test's database.
        api_mod._db = None
        api_mod._orch = None
        api_mod._registry = None
        config_mod._settings = None


def _db():
    """The database the API actually uses."""
    return api_mod.get_orchestrator().db


def _pending_approval(client, approval_id="11111111-2222-3333-4444-555555555555"):
    db = _db()
    db.execute(
        "INSERT INTO approvals (approval_id, agent_name, action_type, payload, "
        "risk, status, requested_at) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (approval_id, "test_agent", "offer_send", "{}", "medium", "pending"))
    return approval_id


def test_the_request_model_declares_every_field_the_route_reads():
    """The route must not read a field the model does not declare.

    This is the exact shape of the bug that broke the approval gate:
    the model and the handler disagreed, and the handler lost.
    """
    import ast
    import inspect

    from wiseq.api import ApprovalIn, decide

    tree = ast.parse(inspect.getsource(decide))
    declared = set(ApprovalIn.model_fields)

    # Every `payload.<name>` the handler reads must be a declared field.
    # The AST is used rather than a line scan because the reads sit inside
    # parenthesised tuples, where a line scan finds nothing.
    read = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "payload"):
            read.add(node.attr)

    assert read, "the handler reads no payload fields; the test is broken"
    missing = read - declared
    assert not missing, (
        f"the approval handler reads payload fields the model does not "
        f"declare: {sorted(missing)}"
    )


def test_deciding_an_approval_succeeds(client):
    approval_id = _pending_approval(client)
    response = client.post(
        f"/approvals/{approval_id}",
        headers={"X-WiseQ-Token": TOKEN},
        json={"decision": "approved", "decided_by": "rob", "note": "looks right"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == "rob"


def test_the_decision_is_persisted_with_who_decided_it(client):
    approval_id = _pending_approval(client)
    client.post(
        f"/approvals/{approval_id}",
        headers={"X-WiseQ-Token": TOKEN},
        json={"decision": "rejected", "decided_by": "rob"},
    )
    row = _db().query_one(
        "SELECT status, decided_by FROM approvals WHERE approval_id=?",
        (approval_id,))
    assert row["status"] == "rejected"
    assert row["decided_by"] == "rob"


def test_the_reason_is_kept_in_the_audit_trail(client):
    """A decision without its reason cannot be explained later."""
    approval_id = _pending_approval(client)
    client.post(
        f"/approvals/{approval_id}",
        headers={"X-WiseQ-Token": TOKEN},
        json={"decision": "approved", "decided_by": "rob",
              "note": "price checked against the master sheet"},
    )
    rows = _db().query(
        "SELECT actor, action, detail FROM audit_log WHERE entity_id=?",
        (approval_id,))
    assert rows, "the decision reason was not written to the audit trail"
    assert rows[0]["actor"] == "rob"
    assert "master sheet" in rows[0]["detail"]


def test_deciding_twice_is_refused(client):
    """The first decision is the one that counts."""
    approval_id = _pending_approval(client)
    first = client.post(
        f"/approvals/{approval_id}",
        headers={"X-WiseQ-Token": TOKEN},
        json={"decision": "approved", "decided_by": "rob"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/approvals/{approval_id}",
        headers={"X-WiseQ-Token": TOKEN},
        json={"decision": "rejected", "decided_by": "someone_else"},
    )
    assert second.status_code == 409, second.text

    row = _db().query_one(
        "SELECT status, decided_by FROM approvals WHERE approval_id=?",
        (approval_id,))
    assert row["status"] == "approved"
    assert row["decided_by"] == "rob"


def test_an_unknown_approval_is_a_404(client):
    response = client.post(
        "/approvals/does-not-exist",
        headers={"X-WiseQ-Token": TOKEN},
        json={"decision": "approved", "decided_by": "rob"},
    )
    assert response.status_code == 404


def test_an_invalid_decision_is_refused(client):
    approval_id = _pending_approval(client)
    response = client.post(
        f"/approvals/{approval_id}",
        headers={"X-WiseQ-Token": TOKEN},
        json={"decision": "maybe", "decided_by": "rob"},
    )
    assert response.status_code == 422


def test_the_decision_needs_a_token(client):
    approval_id = _pending_approval(client)
    response = client.post(
        f"/approvals/{approval_id}",
        json={"decision": "approved", "decided_by": "rob"},
    )
    assert response.status_code in (401, 403), response.text
