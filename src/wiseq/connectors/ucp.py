"""Live Universal Commerce Protocol (UCP) connector for WiseQ's storefront.

What this is
------------
WiseQ's Shopify store already publishes a full agent-facing commerce
interface:

* discovery    ``https://www.wiseq.nl/.well-known/ucp``
* agent brief  ``https://www.wiseq.nl/agents.md``
* MCP endpoint ``https://www.wiseq.nl/api/ucp/mcp``

The MCP endpoint speaks JSON-RPC 2.0 and exposes 13 tools, of which
``search_catalog``, ``lookup_catalog`` and ``get_product`` are read-only and
need no credentials.  The remaining ten (``create_checkout``,
``complete_checkout``, the cart and order tools) are *write* operations and are
deliberately **not** wired into this module -- an agent must never be able to
finish a purchase without a human.

This was verified live on 2026-10-29: a ``search_catalog`` call for
"MagSafe oplader" returned SKU ``231`` at EUR 18.95, which matches the
catalogue price the storefront mirror imported.

How the handshake works
-----------------------
The MCP server is stateless.  A working call is:

1. ``initialize`` with the protocol version and client info.
2. ``tools/list`` (or ``tools/call``) with ``meta.ucp-agent.profile``.

The one non-obvious detail: ``meta.ucp-agent.profile`` must point at a
**JSON** document.  Pointing it at an HTML page fails with
``Invalid content type`` and at a page without a version with
``Missing ucp version``.  ``/.well-known/ucp.json`` satisfies both.

Amounts come back in minor units (cents), per the UCP spec, so EUR 1895 is
EUR 18.95.  This module converts to major units before handing a number to
anything else, because a price quoted to a buyer in cents is a business error.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..ingest.prices import _norm_sku

DEFAULT_STORE = "https://www.wiseq.nl"
DEFAULT_MCP = f"{DEFAULT_STORE}/api/ucp/mcp"
DEFAULT_DISCOVERY = f"{DEFAULT_STORE}/.well-known/ucp.json"
PROTOCOL_VERSION = "2025-06-18"
UCP_VERSION = "2026-08-25"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# Tools this connector is allowed to call.  Everything that can create money
# or commit the buyer is excluded on purpose -- the human-approval gate in
# :mod:`wiseq.agents.base` is the only thing allowed to authorise a purchase.
READ_ONLY_TOOLS = frozenset({
    "search_catalog",
    "lookup_catalog",
    "get_product",
    "get_cart",
    "get_checkout",
    "get_order",
})

# Tools that must never be invoked by an unattended agent.
WRITE_TOOLS = frozenset({
    "create_checkout",
    "update_checkout",
    "complete_checkout",
    "cancel_checkout",
    "create_cart",
    "update_cart",
    "cancel_cart",
})


class UCPError(RuntimeError):
    """Raised when the UCP/MCP endpoint cannot be used."""


class UCPRateLimited(UCPError):
    """Raised when the storefront rate-limits the agent.

    The storefront asks the caller to back off for a number of seconds.
    That is not a missing product, and it must never be recorded as one --
    otherwise a throttled run looks like an empty catalogue.
    """

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


_RATE_LIMIT_RE = re.compile(r"retry after (\d+)", re.IGNORECASE)


@dataclass
class UCPProduct:
    """One product as returned by the storefront's UCP catalogue."""

    id: str
    title: str
    handle: str = ""
    url: str = ""
    price_min: float | None = None
    price_max: float | None = None
    currency: str = "EUR"
    skus: list[str] = field(default_factory=list)
    variants: list[dict] = field(default_factory=list)
    description: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def business_skus(self) -> list[str]:
        """The business SKUs, without any variant suffix."""
        out: list[str] = []
        for sku in self.skus:
            base = sku.split(".")[0].strip()
            if base and base not in out:
                out.append(base)
        return out


def _error_detail(error: dict) -> str:
    """Render a JSON-RPC error's ``data`` field as text.

    ``data`` is not guaranteed to be an object.  The storefront returns a
    plain string there for some failures, and calling ``.get`` on it raises
    inside the error handler, which hides the real failure.
    """
    data = error.get("data")
    if isinstance(data, dict):
        parts = [str(data.get("code", "")), str(data.get("content", ""))]
        return " ".join(p for p in parts if p).strip()
    if isinstance(data, str):
        return data
    if data:
        return str(data)
    return ""


def _http_post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": BROWSER_UA,
        },
    )
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
            return _parse_jsonrpc(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            parsed = _parse_jsonrpc(body)
            error = parsed.get("error")
            if error:
                message = f"{error.get('message')} [{_error_detail(error)}]"
                match = _RATE_LIMIT_RE.search(message)
                if "rate limit" in message.lower() or match:
                    raise UCPRateLimited(
                        message, retry_after=int(match.group(1)) if match else 0
                    ) from exc
                raise UCPError(message) from exc
            raise UCPError(f"HTTP {exc.code} from {url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise UCPError(f"could not reach {url}: {last}")


def _parse_jsonrpc(body: str) -> dict:
    """Parse a JSON-RPC response, tolerating SSE framing."""
    text = body.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UCPError(f"unparseable response: {text[:200]}") from exc


def _amount_to_major(amount: object) -> float | None:
    """Convert UCP minor units (cents) to major units."""
    try:
        return round(float(amount) / 100.0, 2)
    except (TypeError, ValueError):
        return None


class UCPClient:
    """A small client for the storefront's UCP MCP endpoint."""

    def __init__(
        self,
        endpoint: str = DEFAULT_MCP,
        profile: str = DEFAULT_DISCOVERY,
        store: str = DEFAULT_STORE,
        min_interval: float = 0.35,
    ):
        self.endpoint = endpoint
        self.profile = profile
        self.store = store.rstrip("/")
        self.min_interval = min_interval
        self._last_call = 0.0
        self._server_info: dict | None = None
        self._sku_index: dict[str, str] | None = None
        self._index_loaded = False

    def _throttle(self) -> None:
        """Keep a minimum gap between calls.

        The storefront rate-limits aggressively -- a 139-SKU scan without
        spacing trips it and stalls the whole run.  Half a second per call
        keeps a full catalogue scan inside the limit.
        """
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()

    # -- protocol ------------------------------------------------------
    def initialize(self) -> dict:
        """Run the MCP handshake and return the server info."""
        response = _http_post_json(
            self.endpoint,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "wiseq-hermes", "version": "1.0"},
                },
            },
        )
        self._server_info = response.get("result", {})
        return self._server_info

    def list_tools(self) -> list[dict]:
        """Enumerate the tools the storefront publishes."""
        if self._server_info is None:
            self.initialize()
        response = _http_post_json(
            self.endpoint, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        return response.get("result", {}).get("tools", [])

    def _meta(self) -> dict:
        return {"ucp-agent": {"profile": self.profile}}

    def call_tool(self, name: str, arguments: dict, _id: int = 3) -> dict:
        """Invoke a tool and return its structured content.

        Refuses to call any write tool.  Checkout completion is a money
        movement, and this system never lets an agent make one.
        """
        if name in WRITE_TOOLS:
            raise UCPError(
                f"tool '{name}' is write-only and is blocked by policy; "
                "a human must authorise any checkout"
            )
        if name not in READ_ONLY_TOOLS:
            raise UCPError(f"tool '{name}' is not on the read-only allow list")
        if self._server_info is None:
            self.initialize()
        self._throttle()
        response = _http_post_json(
            self.endpoint,
            {
                "jsonrpc": "2.0",
                "id": _id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        if "error" in response:
            error = response["error"]
            message = f"{error.get('message')} [{_error_detail(error)}]"
            match = _RATE_LIMIT_RE.search(message)
            if "rate limit" in message.lower() or match:
                raise UCPRateLimited(
                    message, retry_after=int(match.group(1)) if match else 0
                )
            raise UCPError(message)
        result = response.get("result", {})
        structured = result.get("structuredContent")
        if structured is None:
            text = (result.get("content") or [{}])[0].get("text", "")
            try:
                structured = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                structured = {"raw": text}
        return structured

    # -- catalogue -----------------------------------------------------
    def search_catalog(self, query: str, limit: int = 20, **context) -> list[UCPProduct]:
        """Search the storefront catalogue.  Read-only."""
        catalog: dict = {"query": query, "limit": limit}
        if context:
            catalog["context"] = context
        payload = self.call_tool(
            "search_catalog", {"meta": self._meta(), "catalog": catalog}
        )
        return [self._to_product(p) for p in payload.get("products", [])]

    def get_product(self, identifier: str) -> UCPProduct | None:
        """Look one product up by product id (GID) or business SKU.

        ``get_product``/``lookup_catalog`` only accept the Shopify product
        id (``gid://shopify/Product/<n>``).  Passing a bare SKU returns no
        products rather than an error, which is easy to mistake for "the
        product does not exist".  A SKU is therefore resolved through the
        storefront mirror first, and only falls back to a catalogue search.
        """
        if identifier.startswith("gid://"):
            payload = self.call_tool(
                "get_product",
                {"meta": self._meta(), "catalog": {"id": identifier}},
            )
            products = payload.get("products") or []
            if products:
                return self._to_product(products[0])
            product = payload.get("product")
            return self._to_product(product) if isinstance(product, dict) else None

        gid = self.resolve_gid(identifier)
        if gid is None:
            return None
        payload = self.call_tool(
            "get_product",
            {"meta": self._meta(), "catalog": {"id": gid}},
        )
        products = payload.get("products") or []
        if products:
            return self._to_product(products[0])
        product = payload.get("product")
        return self._to_product(product) if isinstance(product, dict) else None

    def lookup_catalog(self, identifiers: list[str]) -> list[UCPProduct]:
        """Look several products up at once.  Read-only.

        Ids may be GIDs or business SKUs; SKUs are resolved first.  The
        endpoint accepts at most ten ids per call.
        """
        gids = [self.resolve_gid(i) or i for i in identifiers]
        out: list[UCPProduct] = []
        for start in range(0, len(gids), 10):
            chunk = [g for g in gids[start:start + 10] if g]
            if not chunk:
                continue
            payload = self.call_tool(
                "lookup_catalog",
                {"meta": self._meta(), "catalog": {"ids": chunk}},
            )
            out.extend(self._to_product(p) for p in payload.get("products", []))
        return out

    # -- id resolution -------------------------------------------------
    def resolve_gid(self, sku: str) -> str | None:
        """Map a business SKU to the storefront's product id.

        Uses the public Shopify catalogue, which carries both the numeric
        product id and every variant SKU, so no search round-trip and no
        credentials are needed.
        """
        if self._sku_index is None:
            self.load_sku_index()
        index = self._sku_index
        if sku in index:
            return index[sku]
        # Bundle SKUs are written "111 + 216" on the storefront and stored as
        # "111+216" in the catalogue; accept either spelling.
        normalised = _norm_sku(sku)
        if normalised in index:
            return index[normalised]
        return None

    def load_sku_index(self, limit: int = 250) -> dict[str, str]:
        """Build the SKU -> product-id index from the public catalogue."""
        import urllib.request

        url = f"{self.store}/products.json?limit={limit}"
        request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        index: dict[str, str] = {}
        for product in payload.get("products", []):
            gid = f"gid://shopify/Product/{product.get('id')}"
            for variant in product.get("variants", []) or []:
                variant_sku = (variant.get("sku") or "").strip()
                if not variant_sku:
                    continue
                # The storefront writes bundle SKUs as "111 + 216" while the
                # catalogue key is "111+216".  The same normalisation the
                # price importer uses is applied here so a bundle resolves
                # from either spelling.
                index.setdefault(_norm_sku(variant_sku), gid)
                index.setdefault(variant_sku, gid)
            if not product.get("variants"):
                index.setdefault((product.get("handle") or ""), gid)
        self._sku_index = index
        self._index_loaded = True
        return index


    # -- helpers -------------------------------------------------------
    def _to_product(self, raw: dict) -> UCPProduct:
        price_range = raw.get("price_range") or {}
        pmin = price_range.get("min") or {}
        pmax = price_range.get("max") or {}
        variants = raw.get("variants") or []
        skus = [v.get("sku") for v in variants if v.get("sku")]
        if not skus and raw.get("sku"):
            skus = [raw["sku"]]
        description = raw.get("description") or {}
        if isinstance(description, dict):
            description = description.get("html") or description.get("text") or ""
        return UCPProduct(
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            handle=raw.get("handle", ""),
            url=raw.get("url", ""),
            price_min=_amount_to_major(pmin.get("amount")),
            price_max=_amount_to_major(pmax.get("amount")),
            currency=pmin.get("currency") or pmax.get("currency") or "EUR",
            skus=skus,
            variants=variants,
            description=description if isinstance(description, str) else "",
            raw=raw,
        )

    # -- reporting -----------------------------------------------------
    def describe(self) -> dict:
        """A compact description of what the storefront publishes."""
        tools = self.list_tools()
        return {
            "endpoint": self.endpoint,
            "profile": self.profile,
            "server": (self._server_info or {}).get("serverInfo", {}),
            "protocol": (self._server_info or {}).get("protocolVersion"),
            "tools_total": len(tools),
            "read_only_tools": sorted(
                t["name"] for t in tools if t["name"] in READ_ONLY_TOOLS
            ),
            "blocked_write_tools": sorted(
                t["name"] for t in tools if t["name"] in WRITE_TOOLS
            ),
            "observed": time.strftime("%Y-%m-%d"),
        }


def sync_ucp_catalog(
    db=None,
    client: UCPClient | None = None,
    skus: list[str] | None = None,
    load_into_db: bool = True,
    resume: bool = False,
    progress_path: str | Path | None = None,
) -> dict:
    """Pull prices for known SKUs from the live UCP catalogue.

    This is the authoritative counterpart to the storefront mirror in
    :mod:`wiseq.ingest.shopify`: the Shopify mirror reads the whole
    catalogue in one request, while UCP gives a per-SKU lookup that also
    returns what the storefront considers canonical for a given SKU.

    The two are cross-checked, not assumed equal: a disagreement is reported
    as ``price_mismatches`` rather than being silently resolved.
    """
    client = client or UCPClient()
    client.initialize()

    if skus is None and db is not None:
        skus = [
            row["sku_text"]
            for row in db.query(
                "SELECT sku_text FROM products WHERE price_eur <= 0 "
                "OR synthetic_price = 1 ORDER BY sku_text"
            )
        ]
    skus = skus or []

    # A full 139-SKU scan trips the storefront's rate limit partway
    # through, and its back-off window is measured in tens of minutes.
    # With resume=True the scan remembers what it already resolved, so a
    # later run asks only for the SKUs it never got -- the storefront sees
    # FEWER calls on each attempt, not more.
    store = None
    progress = None
    if resume or progress_path is not None:
        from .ucp_scan import ScanProgress, ScanStore, default_store_path

        store = ScanStore(progress_path or default_store_path(db))
        progress = store.load()
        progress.runs += 1

    resolved: list[dict] = []
    mismatches: list[dict] = []
    not_found: list[str] = []
    rate_limited = False
    retry_after = 0

    if progress is not None:
        # Replay what earlier runs already resolved.
        for sku, price in progress.resolved.items():
            resolved.append({
                "sku": sku,
                "price": price,
                "title": progress.titles.get(sku, ""),
                "source": "ucp:mcp",
            })
        not_found.extend(progress.not_found)

    todo = progress.pending(skus) if progress is not None else list(skus)

    for sku in todo:
        try:
            product = client.get_product(sku)
        except UCPRateLimited as exc:
            # The storefront is throttling us.  Stop immediately and report
            # it.  Recording every remaining SKU as "not found" would make a
            # throttled run indistinguishable from an empty catalogue, and
            # that is exactly the kind of quiet failure this system exists
            # to prevent.
            rate_limited = True
            retry_after = exc.retry_after
            break
        except UCPError:
            not_found.append(sku)
            if progress is not None:
                progress.failed.append(sku)
            continue
        if product is None:
            not_found.append(sku)
            if progress is not None:
                progress.not_found.append(sku)
            continue
        if product.price_min is None:
            not_found.append(sku)
            if progress is not None:
                progress.not_found.append(sku)
            continue
        resolved.append({
            "sku": sku,
            "price": product.price_min,
            "title": product.title,
            "source": "ucp:mcp",
        })
        if progress is not None:
            progress.resolved[sku] = product.price_min
            progress.titles[sku] = product.title
            # Save after EVERY resolved SKU, so a crash or a rate limit
            # loses at most one lookup.
            store.save(progress)
        if db is not None:
            existing = db.query(
                "SELECT price_eur, synthetic_price FROM products WHERE sku_text = ?",
                (sku,),
            )
            if existing and existing[0]["price_eur"] not in (None, 0):
                # A SYNTHETIC price is a placeholder seeded for local
                # development, not a price WiseQ published.  Comparing it
                # against the live catalogue would report every single
                # product as a mismatch, which buries the real signal.
                # A placeholder is only a mismatch if it is ZERO -- that
                # is a missing price, and a missing price must block an
                # offer rather than be silently replaced.
                is_synthetic = bool(existing[0].get("synthetic_price"))
                if is_synthetic and float(existing[0]["price_eur"]) > 0:
                    pass
                elif abs(float(existing[0]["price_eur"]) - product.price_min) > 0.005:
                    mismatches.append({
                        "sku_text": sku,
                        "catalogue_price": float(existing[0]["price_eur"]),
                        "ucp_price": product.price_min,
                        "title": product.title,
                        "synthetic_catalogue_price": is_synthetic,
                    })

    if progress is not None:
        progress.not_found = sorted(set(progress.not_found))
        progress.failed = sorted(set(progress.failed))
        store.save(progress)

    loaded = None
    if db is not None and load_into_db and resolved:
        # NOTE: this was `from .prices import load_prices`, which resolves
        # to wiseq.connectors.prices -- a module that does not exist.
        # load_prices lives in wiseq.ingest.prices.  The bug was invisible
        # until a scan actually RESOLVED prices AND was asked to load them,
        # because the import sits inside the `if` branch.
        from ..ingest.prices import load_prices

        result = load_prices(db, resolved, source_name="ucp:mcp")
        loaded = result.as_dict()

    return {
        "endpoint": client.endpoint,
        "requested": len(skus),
        "requested_this_run": len(todo),
        "resolved": len(resolved),
        "not_found": not_found,
        "price_mismatches": mismatches,
        "rate_limited": rate_limited,
        "retry_after_seconds": retry_after,
        "complete": not rate_limited and len(not_found) == 0,
        "loaded": loaded,
        "observed": time.strftime("%Y-%m-%d"),
        "resumable": resume,
        "runs": progress.runs if progress is not None else 1,
        "remaining": (len(progress.pending(skus)) if progress is not None
                      else 0),
    }
