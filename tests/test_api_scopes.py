"""HTTP-level tests for scope enforcement.

The unit tests cover the registry.  These cover the thing that actually
matters to a user: *can this token perform this operation through the
API?*  A token that verifies but is refused by the route is correctly
useless, and that is the behaviour worth pinning down.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from wiseq import api as api_mod  # noqa: E402
from wiseq.api_rbac import TokenRegistry  # noqa: E402
from wiseq.db.db import Database  # noqa: E402


#: The bootstrap credential.  The environment token is the admin of last
#: resort -- it is how the very first token gets issued -- so the tests
#: use it as the admin credential and use issued tokens for everything
#: else.
BOOTSTRAP_TOKEN = "pytest-bootstrap-admin"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A client over a fresh database with a fresh token registry."""
    monkeypatch.setenv("WISEQ_API_TOKEN", BOOTSTRAP_TOKEN)
    monkeypatch.delenv("WISEQ_ADMIN_TOKEN", raising=False)

    db = Database(f"sqlite:///{tmp_path/'api.db'}")
    db.init_schema()

    api_mod._db = db
    api_mod._orch = None
    api_mod._registry = None

    registry = TokenRegistry(db)
    registry.init_schema()
    api_mod._registry = registry

    with TestClient(api_mod.app) as c:
        yield c


def _issue(client, role, scopes=()):
    """Issue a token through the API itself, as an admin would."""
    response = client.post(
        "/auth/tokens",
        headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN},
        json={"name": "test", "role": role, "scopes": list(scopes)},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


# --------------------------------------------------------------------------
# token administration
# --------------------------------------------------------------------------
def test_issuing_a_token_returns_the_secret_once(client):
    response = client.post("/auth/tokens",
                           headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN},
                           json={"name": "ci", "role": "readonly"})
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["role"] == "readonly"


def test_the_issued_secret_is_not_stored_in_the_clear(client):
    secret = _issue(client, "readonly")
    listed = client.get("/auth/tokens", headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN}).json()["tokens"]
    assert secret not in str(listed)


def test_an_unknown_role_carries_no_scopes(client):
    body = client.post("/auth/tokens",
                        headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN},
                        json={"name": "x", "role": "wizard"}).json()
    assert body["scopes"] == []


def test_an_unknown_scope_is_reported_as_ignored(client):
    body = client.post("/auth/tokens", headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN},
                       json={"name": "x", "role": "readonly",
                             "scopes": ["catalogue:read", "bogus:scope"]}).json()
    assert "bogus:scope" in body["ignored_scopes"]
    assert "bogus:scope" not in body["scopes"]


def test_the_roles_endpoint_lists_the_scopes(client):
    body = client.get("/auth/roles", headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN}).json()
    assert "readonly" in body["roles"]
    assert "approvals:write" in body["scopes"]


# --------------------------------------------------------------------------
# scope enforcement on real routes
# --------------------------------------------------------------------------
def test_a_readonly_token_can_read_the_catalogue(client):
    token = _issue(client, "readonly")
    response = client.get("/prices/gaps",
                           headers={"X-WiseQ-Token": token})
    assert response.status_code == 200


def test_a_readonly_token_cannot_raise_an_approval(client):
    """The scope check is what stops a leaked read token from acting."""
    token = _issue(client, "readonly")
    response = client.post("/school-orders",
                           headers={"X-WiseQ-Token": token},
                           json={"email": "x@example.com", "body": "10 tablets"})
    assert response.status_code == 403
    assert "offers:write" in response.json()["detail"]


def test_an_operator_token_can_raise_an_approval(client):
    token = _issue(client, "operator")
    response = client.post("/school-orders",
                           headers={"X-WiseQ-Token": token},
                           json={"email": "x@example.com", "body": "10 tablets"})
    assert response.status_code != 403


def test_an_integrator_token_cannot_raise_an_approval(client):
    """Catalogue sync is not the same power as raising an approval."""
    token = _issue(client, "integrator")
    response = client.post("/school-orders",
                           headers={"X-WiseQ-Token": token},
                           json={"email": "x@example.com", "body": "10 tablets"})
    assert response.status_code == 403


def test_a_readonly_token_cannot_decide_an_approval(client):
    token = _issue(client, "readonly")
    response = client.post("/approvals/does-not-exist",
                           headers={"X-WiseQ-Token": token},
                           json={"decision": "approved", "decided_by": "test"})
    assert response.status_code == 403


def test_a_readonly_token_cannot_run_the_scheduler(client):
    token = _issue(client, "readonly")
    response = client.post("/scheduler/run", headers={"X-WiseQ-Token": token})
    assert response.status_code == 403


def test_an_admin_token_can_list_tokens(client):
    token = _issue(client, "admin")
    response = client.get("/auth/tokens", headers={"X-WiseQ-Token": token})
    assert response.status_code == 200


# --------------------------------------------------------------------------
# rotation over HTTP
# --------------------------------------------------------------------------
def test_rotating_a_token_returns_a_new_secret(client):
    secret = _issue(client, "readonly")
    listed = client.get("/auth/tokens", headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN}).json()["tokens"]
    token_id = listed[0]["token_id"]

    response = client.post(f"/auth/tokens/{token_id}/rotate",
                          headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN},
                          json={"overlap_minutes": 5})
    assert response.status_code == 200
    assert response.json()["token"] != secret


def test_rotating_an_unknown_token_is_a_404(client):
    secret = _issue(client, "admin")
    response = client.post("/auth/tokens/nope/rotate",
                          headers={"X-WiseQ-Token": secret},
                          json={"overlap_minutes": 5})
    assert response.status_code == 404


def test_revoking_a_token_stops_it_working(client):
    secret = _issue(client, "readonly")
    listed = client.get("/auth/tokens", headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN}).json()["tokens"]
    token_id = listed[0]["token_id"]

    response = client.post(f"/auth/tokens/{token_id}/revoke",
                          headers={"X-WiseQ-Token": BOOTSTRAP_TOKEN})
    assert response.status_code == 200

    # The revoked token must no longer authenticate.  A write is used
    # because a loopback READ is allowed without any token at all --
    # that exemption is deliberate and would mask the revocation here.
    after = client.post("/school-orders",
                        headers={"X-WiseQ-Token": secret},
                        json={"email": "x@example.com", "body": "10 tablets"})
    assert after.status_code == 401


def test_revoking_an_unknown_token_is_a_404(client):
    secret = _issue(client, "admin")
    response = client.post("/auth/tokens/nope/revoke",
                          headers={"X-WiseQ-Token": secret})
    assert response.status_code == 404


# --------------------------------------------------------------------------
# the health endpoint
# --------------------------------------------------------------------------
def test_health_reports_the_auth_posture(client):
    body = client.get("/health").json()
    assert body["auth"]["writes_require_token"] is True
    assert "roles" in body["auth"]


def test_the_warranty_contradiction_is_served_over_http(client):
    """The contradiction must be reachable, not only importable.

    An operator checking the system needs one URL that says "your public
    pages disagree".  If this route disappears, the contradiction goes
    back to being invisible.
    """
    response = client.get("/policy/warranty")
    assert response.status_code == 200

    body = response.json()
    assert body["contradicted"] is True
    assert body["years_found"] == [1, 2]
    assert body["internal_manual_years"] == 2
    assert body["blocks_automated_customer_answer"] is True
    assert body["resolution_owner"] == "Rob (WiseQ)"
