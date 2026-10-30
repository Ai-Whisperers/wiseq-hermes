"""Roles, scopes and rotating API tokens for the WiseQ replica.

Why this exists
---------------
The replica holds two very different kinds of power.  Listing a low-stock
article is harmless.  Raising a price-change approval, exporting the
customer list, or triggering a live catalogue sync is not.  A single
shared ``WISEQ_API_TOKEN`` gives every holder of that string all of it,
and it never changes once it is set -- so a token pasted into a chat
window, a shell history file or a colleague's laptop stays valid
forever.

This module adds the two things that fixes:

**Roles and scopes.**  A token is not just a string; it belongs to a
principal with a role, and the role carries a set of scopes.  The API
checks the scope for the operation, not merely "is this a valid token".
A read-only integration token cannot raise an approval even if it leaks.

**Rotation.**  Tokens have an issue time, an expiry, and can be revoked.
Rotation is two-phase: a new token is issued while the old one still
works for a short overlap window, and the old one then stops working.
That is what makes rotation safe to do during business hours -- there is
no instant where nobody can authenticate.

Storage is deliberately simple: the database holds only a **hash** of
each token, never the token itself, so a database dump does not hand
over live credentials.  The token is shown exactly once, at issue time.

Everything here fails closed.  A role that is not configured, a scope
that is not granted, or a token that cannot be verified all result in a
refusal -- never in an accidental permission.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException, Request

#: Scopes the API understands.  A scope not in this set can never be
#: granted -- an unknown scope in a token file is a configuration error,
#: not a permission.
SCOPES: dict[str, str] = {
    "catalogue:read": "Read the catalogue, prices, bundles and shipping rules.",
    "stock:read": "Read stock levels, velocity and days of cover.",
    "approvals:read": "Read the approval queue.",
    "approvals:write": "Raise, decide and cancel approvals.",
    "offers:write": "Draft school offers and quotes.",
    "catalogue:sync": "Trigger a live catalogue or price synchronisation.",
    "customers:read": "Read customer and contact records.",
    "reports:read": "Read the operational reports and audit trail.",
    "admin": "Everything above, plus token administration.",
}

#: Roles and the scopes each one carries.
ROLES: dict[str, tuple[str, ...]] = {
    "readonly": ("catalogue:read", "stock:read", "approvals:read", "reports:read"),
    "operator": (
        "catalogue:read", "stock:read", "approvals:read", "reports:read",
        "approvals:write", "offers:write",
    ),
    "integrator": (
        "catalogue:read", "stock:read", "approvals:read", "reports:read",
        "catalogue:sync",
    ),
    "admin": tuple(SCOPES),
}

#: Paths that never need a token.
OPEN_PATHS = frozenset({"/health", "/metrics"})

#: Methods that change state and therefore always require a token.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: How long an old token keeps working after a rotation.  Long enough to
#: swap a credential in a running client, short enough that a leaked
#: token stops working.
DEFAULT_OVERLAP = timedelta(minutes=30)


# --------------------------------------------------------------------------
# principals and tokens
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Principal:
    """Who is making the request, and what they may do."""

    token_id: str
    name: str
    role: str
    scopes: frozenset[str]

    def has(self, scope: str) -> bool:
        return scope in self.scopes

    def as_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "name": self.name,
            "role": self.role,
            "scopes": sorted(self.scopes),
        }


@dataclass
class IssuedToken:
    """A freshly issued token.

    ``token`` is only ever populated in memory and returned to the
    caller once.  The database keeps the hash.
    """

    token_id: str
    name: str
    role: str
    scopes: tuple[str, ...]
    token: str = ""
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    rotated_from: str | None = None

    def as_dict(self, include_token: bool = False) -> dict:
        payload = {
            "token_id": self.token_id,
            "name": self.name,
            "role": self.role,
            "scopes": list(self.scopes),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "rotated_from": self.rotated_from,
        }
        if include_token:
            payload["token"] = self.token
        return payload


def hash_token(token: str) -> str:
    """Hash a token for storage.  SHA-256 over a high-entropy random
    string is enough -- there is nothing to guess, only to look up.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """A URL-safe random token with enough entropy to be unguessable."""
    return secrets.token_urlsafe(32)


def scopes_for_role(role: str) -> tuple[str, ...]:
    """The scopes a role carries.  An unknown role carries nothing."""
    return ROLES.get(role, ())


def resolve_scopes(role: str, extra: Iterable[str] = ()) -> tuple[str, ...]:
    """Combine a role's scopes with explicitly requested ones.

    An unknown scope is dropped rather than granted: a typo in a token
    request must never widen what the token can do.
    """
    granted = set(scopes_for_role(role))
    for scope in extra:
        if scope in SCOPES:
            granted.add(scope)
    return tuple(sorted(granted))


# --------------------------------------------------------------------------
# database-backed token registry
# --------------------------------------------------------------------------
TOKEN_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
    token_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,
    scopes        TEXT NOT NULL,          -- JSON array of scope names
    token_hash    TEXT NOT NULL UNIQUE,   -- SHA-256 of the token, never the token
    issued_at     ${TS} NOT NULL DEFAULT ${NOW},
    expires_at    ${TS},
    revoked_at    ${TS},
    rotated_from  TEXT,                   -- the token_id this one replaces
    last_used_at  ${TS}
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash);
"""


class TokenRegistry:
    """Issues, verifies, rotates and revokes API tokens.

    The registry is the single place that knows which token is valid.
    It is deliberately separate from the HTTP layer so the same rules
    apply to a script, the API and a test.
    """

    def __init__(self, db) -> None:
        self.db = db

    # -- schema ---------------------------------------------------------
    def init_schema(self) -> None:
        """Ensure the token table exists.

        The table is also part of the main schema, so a normally
        initialised database already has it.  This makes the registry
        usable against a database that was created without the full
        schema -- a test fixture, or a partially migrated instance.
        """
        from .db.schema import DIALECTS

        tokens = DIALECTS.get(self.db.dialect)
        if not tokens:
            raise ValueError(f"unsupported dialect: {self.db.dialect}")

        ddl = TOKEN_TABLE_DDL
        for key, value in tokens.items():
            ddl = ddl.replace("${" + key + "}", value)
        if self.db.dialect == "postgresql":
            ddl = ddl.replace("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE")

        # SQLite's execute() takes one statement at a time; PostgreSQL
        # accepts the whole script.  Split it so both work.
        statements = [s.strip() for s in ddl.split(";") if s.strip()]
        for statement in statements:
            self.db.execute(statement)

    # -- issue ----------------------------------------------------------
    def issue(
        self,
        name: str,
        role: str,
        scopes: Iterable[str] = (),
        expires_in: timedelta | None = None,
        rotated_from: str | None = None,
    ) -> IssuedToken:
        """Issue a new token.

        The plaintext token is returned once and never stored.  A caller
        that loses it must issue a new one -- there is no recovery path,
        by design.
        """
        resolved = resolve_scopes(role, scopes)
        token_id = secrets.token_hex(8)
        secret = generate_token()
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + expires_in if expires_in else None

        self.db.execute(
            """
            INSERT INTO api_tokens
                (token_id, name, role, scopes, token_hash, issued_at, expires_at, rotated_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (token_id, name, role, json.dumps(list(resolved)), hash_token(secret),
             issued_at, expires_at, rotated_from),
        )

        return IssuedToken(token_id=token_id, name=name, role=role,
                           scopes=resolved, token=secret, issued_at=issued_at,
                           expires_at=expires_at, rotated_from=rotated_from)

    # -- verify ---------------------------------------------------------
    def verify(self, token: str) -> Principal | None:
        """Return the principal for a token, or ``None``.

        A token that is unknown, revoked, expired or unverifiable all
        return ``None``.  The caller cannot tell them apart, which is
        the point -- a probe should not learn whether a token exists.
        """
        if not token:
            return None

        rows = self.db.query(
            "SELECT token_id, name, role, scopes, token_hash, issued_at, "
            "expires_at, revoked_at FROM api_tokens WHERE token_hash = ?",
            (hash_token(token),),
        )
        if not rows:
            return None

        row = rows[0]
        if not hmac.compare_digest(str(row["token_hash"]), hash_token(token)):
            return None

        now = datetime.now(timezone.utc)
        if row.get("revoked_at"):
            return None
        expires_at = row.get("expires_at")
        if expires_at is not None and _as_datetime(expires_at) <= now:
            return None

        scopes = row.get("scopes") or "[]"
        if isinstance(scopes, str):
            try:
                scopes = json.loads(scopes)
            except (ValueError, TypeError):
                scopes = []
        scope_set = frozenset(s for s in scopes if s in SCOPES)

        return Principal(token_id=str(row["token_id"]), name=str(row["name"]),
                         role=str(row["role"]), scopes=scope_set)

    # -- rotate ---------------------------------------------------------
    def rotate(
        self,
        token_id: str,
        overlap: timedelta = DEFAULT_OVERLAP,
        scopes: Iterable[str] = (),
    ) -> IssuedToken | None:
        """Replace a token with a new one.

        The old token keeps working for ``overlap`` so a running client
        can be updated without a window where nobody can authenticate.
        After the overlap it stops working.

        Returns the new token, or ``None`` if ``token_id`` is unknown.
        """
        rows = self.db.query(
            "SELECT token_id, name, role, scopes FROM api_tokens WHERE token_id = ?",
            (token_id,),
        )
        if not rows:
            return None
        row = rows[0]

        new_token = self.issue(
            name=row["name"],
            role=row["role"],
            scopes=scopes,
            rotated_from=token_id,
        )

        # The old token stops working once the overlap has passed.
        self.db.execute(
            "UPDATE api_tokens SET expires_at = ? WHERE token_id = ?",
            (datetime.now(timezone.utc) + overlap, token_id),
        )
        return new_token

    # -- revoke ---------------------------------------------------------
    def revoke(self, token_id: str) -> bool:
        """Revoke a token immediately.  Returns whether it existed."""
        rows = self.db.query("SELECT token_id FROM api_tokens WHERE token_id = ?", (token_id,))
        if not rows:
            return False
        self.db.execute(
            "UPDATE api_tokens SET revoked_at = ? WHERE token_id = ?",
            (datetime.now(timezone.utc), token_id),
        )
        return True

    # -- list -----------------------------------------------------------
    def list_tokens(self) -> list[dict]:
        """Every token, without the secret.  Safe to show a human."""
        rows = self.db.query(
            "SELECT token_id, name, role, scopes, issued_at, expires_at, "
            "revoked_at, rotated_from FROM api_tokens ORDER BY issued_at DESC"
        )
        out = []
        for row in rows:
            scopes = row.get("scopes") or "[]"
            if isinstance(scopes, str):
                try:
                    scopes = json.loads(scopes)
                except (ValueError, TypeError):
                    scopes = []
            out.append({
                "token_id": row["token_id"],
                "name": row["name"],
                "role": row["role"],
                "scopes": list(scopes),
                "issued_at": _iso(row.get("issued_at")),
                "expires_at": _iso(row.get("expires_at")),
                "revoked_at": _iso(row.get("revoked_at")),
                "rotated_from": row.get("rotated_from"),
                "active": not row.get("revoked_at"),
            })
        return out


def _as_datetime(value) -> datetime:
    """Read a timestamp back from either dialect."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# --------------------------------------------------------------------------
# the static-token fallback
# --------------------------------------------------------------------------
def configured_token() -> str:
    """The environment token, if one is set.

    This is the single-token mode that predates the registry.  It keeps
    working so an existing deployment is not broken by the upgrade, but
    it is treated as a full ``admin`` token, because that is what it
    always was.
    """
    for name in ("WISEQ_API_TOKEN", "WISEQ_ADMIN_TOKEN"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


# --------------------------------------------------------------------------
# HTTP integration
# --------------------------------------------------------------------------
def _client_host(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else ""


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def presented_token(request: Request) -> str:
    """The token the caller supplied, if any."""
    header = request.headers.get("x-wiseq-token")
    if header:
        return header.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def require_scope(principal: Principal | None, scope: str) -> Principal:
    """Raise 403 unless the principal carries the scope.

    A missing principal is a 401; a principal without the scope is a
    403.  The distinction matters: one says "who are you", the other
    says "not you".
    """
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    if not principal.has(scope):
        raise HTTPException(
            status_code=403,
            detail=(f"This action needs the {scope!r} scope. "
                    f"Your role {principal.role!r} carries: "
                    f"{', '.join(sorted(principal.scopes)) or 'none'}."),
        )
    return principal


def authenticate(request: Request, registry: TokenRegistry | None) -> Principal | None:
    """Identify the caller.

    Order matters: a registry token wins, then the environment token.
    A loopback caller with no token at all is allowed a *read*, which is
    what local development, the health check and the verifier's smoke
    test need.  A write never gets that exemption.
    """
    token = presented_token(request)

    if token and registry is not None:
        principal = registry.verify(token)
        if principal is not None:
            return principal

    env_token = configured_token()
    if token and env_token and hmac.compare_digest(env_token, token):
        return Principal(token_id="env", name="environment token", role="admin",
                         scopes=frozenset(SCOPES))

    return None


def check_api_access(request: Request, registry: TokenRegistry | None = None,
                      required_scope: str | None = None) -> Principal | None:
    """Gate a request.

    The rules:

    * open paths are always allowed;
    * a write always needs a token, from anywhere;
    * a remote read needs a token;
    * a loopback read is allowed without one;
    * when a scope is named, the token must carry it.

    With no token configured at all, remote access **fails closed** --
    "nobody set it up yet" must not mean "open to the internet".
    """
    path = request.url.path
    method = request.method.upper()

    if path in OPEN_PATHS:
        return None

    principal = authenticate(request, registry)
    is_write = method in WRITE_METHODS

    if principal is None:
        if is_write:
            raise HTTPException(
                status_code=401,
                detail=("This action requires an API token. Set WISEQ_API_TOKEN "
                        "and send it as X-WiseQ-Token or Authorization: Bearer "
                        "<token>."))
        if is_loopback(_client_host(request)):
            return None
        if not configured_token():
            raise HTTPException(
                status_code=401,
                detail=("No API token is configured, so remote access is "
                        "refused. Set WISEQ_API_TOKEN to enable remote reads."))
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")

    if required_scope:
        require_scope(principal, required_scope)
    return principal


def auth_status(registry: TokenRegistry | None = None) -> dict:
    """Describe the current auth posture for /health and the demo."""
    env_token = configured_token()
    tokens = registry.list_tokens() if registry is not None else []
    active = [t for t in tokens if t.get("active")]
    return {
        "token_configured": bool(env_token) or bool(active),
        "remote_reads_allowed": bool(env_token) or bool(active),
        "loopback_reads_allowed": True,
        "writes_require_token": True,
        "open_paths": sorted(OPEN_PATHS),
        "roles": {role: list(scopes) for role, scopes in ROLES.items()},
        "scopes": dict(SCOPES),
        "registered_tokens": len(tokens),
        "active_tokens": len(active),
    }
