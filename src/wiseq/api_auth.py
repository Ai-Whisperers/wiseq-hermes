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

from fastapi import HTTPException, Request

from .api_rbac import (
    OPEN_PATHS,
    WRITE_METHODS,
    Principal,
    TokenRegistry,
    authenticate,
    auth_status as _auth_status,
    check_api_access as _check_api_access,
    configured_token as _configured_token,
    is_loopback,
    presented_token as _presented_token,
    require_scope,
)


def _client_host(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else ""


def check_api_access(request: Request, registry: TokenRegistry | None = None,
                      required_scope: str | None = None) -> Principal | None:
    """Raise HTTP 401/403 when the caller is not allowed in.

    Call this as a FastAPI dependency on every route.  Reads from
    loopback are allowed; writes always need a token; reads from
    anywhere else need a token.  When a scope is named, the token must
    carry it.

    The rules themselves live in :mod:`wiseq.api_rbac` so that the same
    policy applies to a script, the API and a test.
    """
    return _check_api_access(request, registry=registry, required_scope=required_scope)


def auth_status(registry: TokenRegistry | None = None) -> dict:
    """Describe the current auth posture for /health and the demo."""
    return _auth_status(registry)
