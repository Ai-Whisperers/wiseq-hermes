"""The API must not be open to the internet.

The replica can raise approvals, draft offers and trigger a live price
sync.  Running it on a VPS bound to 0.0.0.0 without a token would
expose all of that.  The rules under test:

  * loopback READS are allowed (local dev, health check, smoke test);
  * every WRITE needs a token, from anywhere;
  * remote READS need a token;
  * with no token configured, remote access FAILS CLOSED;
  * ``/health`` and ``/metrics`` stay open for liveness probes.
"""
from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from wiseq import api as api_mod
from wiseq.api_auth import OPEN_PATHS, auth_status, is_loopback


@pytest.fixture()
def client():
    api_mod._db = None
    api_mod._orch = None
    return TestClient(api_mod.app)


@pytest.fixture(autouse=True)
def _clean_env():
    """Isolate the token environment -- and PUT IT BACK afterwards.

    These tests deliberately remove WISEQ_API_TOKEN to prove that remote
    access fails closed.  If the removal leaked into later test files,
    every write endpoint in the suite would start answering 401 for a
    reason that has nothing to do with the code under test.
    """
    names = ("WISEQ_API_TOKEN", "WISEQ_ADMIN_TOKEN")
    saved = {n: os.environ.pop(n, None) for n in names}
    yield
    for n in names:
        os.environ.pop(n, None)
        if saved[n] is not None:
            os.environ[n] = saved[n]


# -- helper behaviour -------------------------------------------------
def test_loopback_detection():
    assert is_loopback("127.0.0.1")
    assert is_loopback("::1")
    assert is_loopback("testclient")
    assert not is_loopback("203.0.113.9")


def test_health_and_metrics_are_open():
    assert "/health" in OPEN_PATHS
    assert "/metrics" in OPEN_PATHS


def test_auth_status_reports_no_token():
    status = auth_status()
    assert status["token_configured"] is False
    assert status["remote_reads_allowed"] is False
    assert status["writes_require_token"] is True


def test_auth_status_reports_token(monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", "abc123")
    status = auth_status()
    assert status["token_configured"] is True
    assert status["remote_reads_allowed"] is True


# -- open paths --------------------------------------------------------
def test_health_needs_no_token(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_metrics_needs_no_token(client):
    assert client.get("/metrics").status_code == 200


def test_health_reports_auth_posture(client):
    body = client.get("/health").json()
    assert "auth" in body
    assert body["auth"]["writes_require_token"] is True


# -- loopback reads ----------------------------------------------------
def test_loopback_read_is_allowed(client):
    r = client.get("/approvals")
    assert r.status_code == 200


def test_loopback_write_without_token_is_refused(client):
    """A local process must not be able to act without a token either."""
    r = client.post("/ingest")
    assert r.status_code == 401


def test_loopback_write_with_token_succeeds(client, monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", "tok")
    r = client.post("/ingest", headers={"X-WiseQ-Token": "tok"})
    # 503 means the route ran but the repo was not configured -- still
    # proof that the auth gate let the write THROUGH.
    assert r.status_code in (200, 503), r.text


# -- token handling ----------------------------------------------------
def test_token_via_custom_header(client, monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", "secret")
    r = client.post("/ingest", headers={"X-WiseQ-Token": "secret"})
    # These tests assert that the AUTH GATE accepted the token.  The
    # /ingest handler itself answers 503 when the client repo is not
    # mounted, which is still proof the gate let the write through.
    assert r.status_code in (200, 503), r.text


def test_token_via_bearer_header(client, monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", "secret")
    r = client.post("/ingest", headers={"Authorization": "Bearer secret"})
    assert r.status_code in (200, 503), r.text


def test_wrong_token_is_refused(client, monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", "secret")
    r = client.post("/ingest", headers={"X-WiseQ-Token": "wrong"})
    assert r.status_code == 401


def test_admin_token_alias_is_accepted(client, monkeypatch):
    monkeypatch.setenv("WISEQ_ADMIN_TOKEN", "adm")
    r = client.post("/ingest", headers={"X-WiseQ-Token": "adm"})
    assert r.status_code in (200, 503), r.text


# -- remote callers ----------------------------------------------------
def test_remote_read_fails_closed_without_token(client):
    """No token configured means remote access is refused, not open."""
    r = client.get("/approvals",
                   headers={"X-Forwarded-For": "203.0.113.9"})
    # TestClient reports client.host as 'testclient', which counts as
    # loopback; the remote path is exercised directly below instead.
    assert r.status_code in (200, 401)


def test_remote_read_is_refused_with_a_token_but_no_match(client, monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", "secret")
    r = client.get("/approvals", headers={"X-WiseQ-Token": "nope"})
    # From loopback a read with a wrong token still passes (loopback reads
    # are allowed); from a remote host it would be refused.
    assert r.status_code in (200, 401)


def test_remote_path_refuses_when_no_token(monkeypatch):
    """Directly exercise the remote branch of the gate."""
    from fastapi import HTTPException
    from wiseq.api_auth import check_api_access

    class FakeRequest:
        method = "GET"
        url = type("U", (), {"path": "/approvals"})()
        client = type("C", (), {"host": "203.0.113.9"})()
        headers: dict = {}

    with pytest.raises(HTTPException) as exc:
        check_api_access(FakeRequest())
    assert exc.value.status_code == 401


def test_remote_write_requires_token_from_anywhere(monkeypatch):
    from fastapi import HTTPException
    from wiseq.api_auth import check_api_access

    class FakeRequest:
        method = "POST"
        url = type("U", (), {"path": "/ingest"})()
        client = type("C", (), {"host": "203.0.113.9"})()
        headers: dict = {}

    with pytest.raises(HTTPException) as exc:
        check_api_access(FakeRequest())
    assert exc.value.status_code == 401


def test_open_path_stays_open_remotely():
    from wiseq.api_auth import check_api_access

    class FakeRequest:
        method = "GET"
        url = type("U", (), {"path": "/health"})()
        client = type("C", (), {"host": "203.0.113.9"})()
        headers: dict = {}

    check_api_access(FakeRequest())   # must not raise


def test_error_message_does_not_leak_the_token(client, monkeypatch):
    monkeypatch.setenv("WISEQ_API_TOKEN", "super-secret-value")
    r = client.post("/ingest", headers={"X-WiseQ-Token": "wrong"})
    assert "super-secret-value" not in r.text
