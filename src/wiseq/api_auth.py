"""API authentication for the WiseQ operations replica.

The API can do things that matter: raise an approval, draft an offer,
trigger a live price sync, list customers.  Running it on a VPS with
``0.0.0.0`` and no authentication would expose all of that to the
internet.

The rule mirrors what the war-room server already does in this
environment:

  * **loopback is always allowed** -- local development, the Docker
    health check and the verifier's own smoke test all connect from
    127.0.0.1 and must not need a token;
  * **remote callers need a token** -- sent as ``X-WiseQ-Token`` or as a
    ``Bearer`` header.

The token is compared with ``hmac.compare_digest`` so it cannot be
brute-forced by timing.  When no token is configured, remote access
**fails closed**: an unauthenticated request is refused rather than
allowed, because "no token configured" most often means "nobody set it
up yet" and defaulting to open would be the dangerous choice.
"""
from __future__ import annotations

import hmac
import os
from typing import Iterable

from fastapi import HTTPException, Request

#: Requests that are safe to serve without a token, because they expose
#: no business data and are needed for liveness probes.
OPEN_PATHS = frozenset({"/health", "/metrics"})

#: Methods that change state and therefore always require a token, even
#: from loopback.  A local process should not be able to silently raise
#: a price approval just because it shares the host.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _client_host(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else ""


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def _presented_token(request: Request) -> str:
    header = request.headers.get("x-wiseq-token")
    if header:
        return header.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _configured_token() -> str:
    for name in ("WISEQ_API_TOKEN", "WISEQ_ADMIN_TOKEN"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def check_api_access(request: Request) -> None:
    """Raise HTTP 401 when the caller is not allowed in.

    Call this as a FastAPI dependency on every route.  Reads from
    loopback are allowed; writes always need a token; reads from
    anywhere else need a token.
    """
    path = request.url.path
    method = request.method.upper()

    if path in OPEN_PATHS:
        return

    token = _configured_token()
    presented = _presented_token(request)

    if token and presented and hmac.compare_digest(token, presented):
        return

    if method in WRITE_METHODS:
        raise HTTPException(
            status_code=401,
            detail=("This action requires an API token. Set WISEQ_API_TOKEN "
                    "and send it as X-WiseQ-Token or Authorization: Bearer "
                    "<token>."))

    if is_loopback(_client_host(request)):
        # A local read is fine.  Local WRITES were already refused above.
        return

    if not token:
        raise HTTPException(
            status_code=401,
            detail=("No API token is configured, so remote access is "
                    "refused. Set WISEQ_API_TOKEN to enable remote reads."))

    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API token.")


def auth_status() -> dict:
    """Describe the current auth posture for /health and the demo."""
    token = _configured_token()
    return {
        "token_configured": bool(token),
        "remote_reads_allowed": bool(token),
        "loopback_reads_allowed": True,
        "writes_require_token": True,
        "open_paths": sorted(OPEN_PATHS),
    }
