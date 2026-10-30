"""Tests for roles, scopes and rotating API tokens.

The security property under test is narrow and important: *a token that
carries a scope must be the only thing that can perform that scope's
operation*.  A shared admin token does not satisfy it, and neither does
a valid token that happens to be for the wrong role.

The second property is that rotation never leaves a gap and never leaves
a dead credential: the old token works during the overlap window and
stops working afterwards, on its own.

No test touches the network.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiseq.api_rbac import (  # noqa: E402
    ROLES,
    SCOPES,
    Principal,
    TokenRegistry,
    hash_token,
    resolve_scopes,
    scopes_for_role,
)
from wiseq.db.db import Database  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path/'rbac.db'}")
    database.init_schema()
    return database


@pytest.fixture()
def registry(db):
    reg = TokenRegistry(db)
    reg.init_schema()
    return reg


# --------------------------------------------------------------------------
# scopes and roles
# --------------------------------------------------------------------------
def test_every_role_carries_only_known_scopes():
    for role, scopes in ROLES.items():
        for scope in scopes:
            assert scope in SCOPES, f"role {role} names unknown scope {scope}"


def test_an_unknown_role_carries_nothing():
    assert scopes_for_role("wizard") == ()


def test_the_admin_role_carries_every_scope():
    assert set(ROLES["admin"]) == set(SCOPES)


def test_readonly_cannot_write():
    assert "approvals:write" not in ROLES["readonly"]
    assert "offers:write" not in ROLES["readonly"]


def test_readonly_cannot_reach_customer_data():
    assert "customers:read" not in ROLES["readonly"]


def test_an_unknown_scope_is_dropped_not_granted():
    """A typo must never widen what a token can do."""
    resolved = resolve_scopes("readonly", ["catalogue:read", "not:a:scope"])
    assert "not:a:scope" not in resolved
    assert "catalogue:read" in resolved


def test_an_explicit_scope_can_widen_within_the_known_set():
    resolved = resolve_scopes("readonly", ["approvals:write"])
    assert "approvals:write" in resolved


def test_an_unknown_scope_cannot_be_added_to_admin():
    resolved = resolve_scopes("admin", ["superuser"])
    assert "superuser" not in resolved


# --------------------------------------------------------------------------
# issuing
# --------------------------------------------------------------------------
def test_an_issued_token_verifies(registry):
    issued = registry.issue("ci", "readonly")
    principal = registry.verify(issued.token)
    assert principal is not None
    assert principal.name == "ci"
    assert principal.role == "readonly"


def test_a_token_carries_its_role_scopes(registry):
    issued = registry.issue("ci", "operator")
    principal = registry.verify(issued.token)
    assert principal.has("approvals:write")
    assert not principal.has("admin")


def test_an_unknown_token_does_not_verify(registry):
    assert registry.verify("not-a-real-token") is None


def test_an_empty_token_does_not_verify(registry):
    assert registry.verify("") is None


def test_the_secret_is_never_stored(registry):
    issued = registry.issue("ci", "readonly")
    rows = registry.db.query("SELECT token_hash, scopes FROM api_tokens")
    assert len(rows) == 1
    assert issued.token not in rows[0]["token_hash"]
    assert rows[0]["token_hash"] == hash_token(issued.token)


def test_the_hash_is_stable_and_one_way():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
    assert "abc" not in hash_token("abc")


def test_two_issued_tokens_are_different(registry):
    a = registry.issue("a", "readonly")
    b = registry.issue("b", "readonly")
    assert a.token != b.token


def test_an_expired_token_does_not_verify(registry):
    issued = registry.issue("short", "readonly", expires_in=timedelta(seconds=-1))
    assert registry.verify(issued.token) is None


def test_a_token_with_an_expiry_in_the_future_verifies(registry):
    issued = registry.issue("long", "readonly", expires_in=timedelta(days=1))
    assert registry.verify(issued.token) is not None


# --------------------------------------------------------------------------
# rotation
# --------------------------------------------------------------------------
def test_rotation_returns_a_new_token(registry):
    original = registry.issue("ci", "readonly")
    rotated = registry.rotate(original.token_id)
    assert rotated is not None
    assert rotated.token != original.token
    assert rotated.rotated_from == original.token_id


def test_the_old_token_works_during_the_overlap(registry):
    """Rotation must not leave a gap where nobody can authenticate."""
    original = registry.issue("ci", "readonly")
    registry.rotate(original.token_id, overlap=timedelta(minutes=30))
    assert registry.verify(original.token) is not None


def test_the_old_token_stops_working_after_the_overlap(registry):
    original = registry.issue("ci", "readonly")
    registry.rotate(original.token_id, overlap=timedelta(minutes=30))
    # Move the old token's expiry into the past.
    registry.db.execute(
        "UPDATE api_tokens SET expires_at = ? WHERE token_id = ?",
        ("2000-01-01 00:00:00", original.token_id),
    )
    assert registry.verify(original.token) is None


def test_the_new_token_works_after_rotation(registry):
    original = registry.issue("ci", "readonly")
    rotated = registry.rotate(original.token_id)
    assert registry.verify(rotated.token) is not None


def test_rotating_an_unknown_token_returns_none(registry):
    assert registry.rotate("no-such-token") is None


def test_rotation_keeps_the_role(registry):
    original = registry.issue("ci", "operator")
    rotated = registry.rotate(original.token_id)
    principal = registry.verify(rotated.token)
    assert principal.role == "operator"
    assert principal.has("approvals:write")


# --------------------------------------------------------------------------
# revocation
# --------------------------------------------------------------------------
def test_revoking_stops_the_token_working(registry):
    issued = registry.issue("leaky", "admin")
    assert registry.revoke(issued.token_id) is True
    assert registry.verify(issued.token) is None


def test_revoking_an_unknown_token_reports_false(registry):
    assert registry.revoke("no-such-token") is False


def test_revoking_does_not_affect_other_tokens(registry):
    keep = registry.issue("keep", "readonly")
    drop = registry.issue("drop", "readonly")
    registry.revoke(drop.token_id)
    assert registry.verify(keep.token) is not None


# --------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------
def test_the_list_never_contains_a_secret(registry):
    issued = registry.issue("ci", "readonly")
    listed = registry.list_tokens()
    assert len(listed) == 1
    assert issued.token not in str(listed)
    assert "token_hash" not in listed[0]


def test_the_list_reports_revocation(registry):
    issued = registry.issue("ci", "readonly")
    registry.revoke(issued.token_id)
    listed = registry.list_tokens()
    assert listed[0]["active"] is False


# --------------------------------------------------------------------------
# the principal
# --------------------------------------------------------------------------
def test_a_principal_reports_its_scopes_sorted():
    p = Principal(token_id="x", name="n", role="readonly",
                  scopes=frozenset({"catalogue:read", "stock:read"}))
    assert p.as_dict()["scopes"] == ["catalogue:read", "stock:read"]
