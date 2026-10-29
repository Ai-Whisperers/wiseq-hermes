"""Tests for the live UCP/MCP connector.

These run entirely offline: the network is stubbed.  The live behaviour was
verified separately against ``https://www.wiseq.nl/api/ucp/mcp`` on
2026-10-29, where a ``search_catalog`` call for "MagSafe oplader" returned
SKU ``231`` at EUR 18.95.

What these tests actually pin down:

* the read-only allow list and the write-tool block,
* the JSON-RPC handshake and the profile requirement,
* cents-to-euros conversion (UCP returns minor units),
* SKU -> product-id resolution, including bundle SKUs like ``117 + 240``,
* that a price disagreement between two sources is reported, not resolved.
"""
from __future__ import annotations

import json

import pytest

from wiseq.connectors import ucp
from wiseq.connectors.ucp import (
    UCPClient,
    UCPError,
    UCPProduct,
    UCPRateLimited,
    _amount_to_major,
    _error_detail,
    _parse_jsonrpc,
)

GID_231 = "gid://shopify/Product/10296656560461"


def _raw_product(sku="231", title="Draadloze Oplader", amount=1895):
    return {
        "id": GID_231,
        "title": title,
        "handle": "draadloze-oplader",
        "url": "https://www.wiseq.nl/products/draadloze-oplader",
        "description": {"html": "<p>Beschrijving</p>"},
        "price_range": {
            "min": {"amount": amount, "currency": "EUR"},
            "max": {"amount": amount, "currency": "EUR"},
        },
        "list_price_range": {
            "min": {"amount": 0, "currency": "EUR"},
            "max": {"amount": 0, "currency": "EUR"},
        },
        "variants": [
            {"id": "gid://shopify/ProductVariant/1", "sku": sku, "title": "Wit"}
        ],
    }


# ---------------------------------------------------------------------------
# protocol plumbing
# ---------------------------------------------------------------------------

def test_parse_jsonrpc_plain_json():
    assert _parse_jsonrpc('{"result": {"a": 1}}')["result"]["a"] == 1


def test_parse_jsonrpc_sse_framing():
    body = 'event: message\ndata: {"result": {"ok": true}}\n\n'
    assert _parse_jsonrpc(body)["result"]["ok"] is True


def test_parse_jsonrpc_rejects_garbage():
    with pytest.raises(UCPError):
        _parse_jsonrpc("not json at all")


def test_amount_to_major_converts_cents():
    assert _amount_to_major(1895) == 18.95
    assert _amount_to_major("2795") == 27.95
    assert _amount_to_major(0) == 0.0
    assert _amount_to_major(None) is None
    assert _amount_to_major("nonsense") is None


def test_amount_to_major_never_returns_cents():
    """A price quoted in cents to a buyer is a business error."""
    for raw in (1895, 2795, 1099):
        assert _amount_to_major(raw) < 1000


# ---------------------------------------------------------------------------
# tool policy
# ---------------------------------------------------------------------------

def test_write_tools_are_blocked():
    client = UCPClient()
    for tool in ("create_checkout", "complete_checkout", "update_cart"):
        with pytest.raises(UCPError, match="write-only"):
            client.call_tool(tool, {})


def test_unknown_tool_is_blocked():
    client = UCPClient()
    with pytest.raises(UCPError, match="read-only allow list"):
        client.call_tool("drop_everything", {})


def test_read_only_tools_are_allowed():
    client = UCPClient()
    assert "search_catalog" in ucp.READ_ONLY_TOOLS
    assert "get_product" in ucp.READ_ONLY_TOOLS
    assert "lookup_catalog" in ucp.READ_ONLY_TOOLS


def test_read_and_write_sets_do_not_overlap():
    assert not (ucp.READ_ONLY_TOOLS & ucp.WRITE_TOOLS)


# ---------------------------------------------------------------------------
# client behaviour with a stubbed transport
# ---------------------------------------------------------------------------

class StubClient(UCPClient):
    """A client whose HTTP layer is replaced with canned responses."""

    def __init__(self, products=None, tool_payloads=None):
        super().__init__()
        self._products = products or {}
        self._tool_payloads = tool_payloads or {}
        self.calls = []

    def _post(self, payload):
        raise NotImplementedError

    def initialize(self):
        self._server_info = {
            "protocolVersion": ucp.PROTOCOL_VERSION,
            "serverInfo": {"name": "universal-commerce", "version": "0.1.0"},
        }
        return self._server_info

    def call_tool(self, name, arguments, _id=3):
        if name in ucp.WRITE_TOOLS:
            raise UCPError(f"tool '{name}' is write-only and is blocked by policy")
        if name in self._tool_payloads:
            return self._tool_payloads[name]
        self.calls.append((name, arguments))
        if name == "search_catalog":
            return {"products": list(self._products.values())}
        if name in ("get_product", "lookup_catalog"):
            wanted = []
            ids = ([arguments["catalog"]["id"]] if name == "get_product"
                   else arguments["catalog"]["ids"])
            for ident in ids:
                if ident in self._products:
                    wanted.append(self._products[ident])
            return {"products": wanted}
        return {}

    def load_sku_index(self, limit=250):
        index = {}
        for product in self._products.values():
            gid = product["id"]
            for variant in product.get("variants", []):
                sku = (variant.get("sku") or "").strip()
                if sku:
                    index.setdefault(sku, gid)
                    index.setdefault(sku.split(".")[0].strip(), gid)
        self._sku_index = index
        self._index_loaded = True
        return index


def test_search_catalog_returns_products():
    client = StubClient(products={GID_231: _raw_product()})
    client.initialize()
    products = client.search_catalog("MagSafe oplader")
    assert len(products) == 1
    assert products[0].price_min == 18.95
    assert products[0].currency == "EUR"
    assert products[0].skus == ["231"]


def test_get_product_by_sku_resolves_the_product_id():
    """A bare SKU must work even though the endpoint only accepts ids."""
    client = StubClient(products={GID_231: _raw_product()})
    client.initialize()
    product = client.get_product("231")
    assert product is not None
    assert product.price_min == 18.95
    # the connector had to translate the SKU into the product id
    assert client.calls[-1][1]["catalog"]["id"] == GID_231


def test_get_product_by_gid_skips_the_index():
    client = StubClient(products={GID_231: _raw_product()})
    client.initialize()
    product = client.get_product(GID_231)
    assert product is not None
    assert product.price_min == 18.95


def test_get_product_for_unknown_sku_returns_none():
    client = StubClient(products={GID_231: _raw_product()})
    client.initialize()
    assert client.get_product("DOES-NOT-EXIST") is None


def test_lookup_catalog_accepts_skus():
    client = StubClient(products={GID_231: _raw_product()})
    client.initialize()
    products = client.lookup_catalog(["231"])
    assert len(products) == 1
    assert products[0].skus == ["231"]


def test_lookup_catalog_chunks_at_ten():
    products = {}
    for index in range(23):
        gid = f"gid://shopify/Product/{index}"
        products[gid] = _raw_product(sku=str(index), title=f"P{index}")
    client = StubClient(products=products)
    client.initialize()
    client.lookup_catalog(list(products.keys()))
    sizes = [len(call[1]["catalog"]["ids"]) for call in client.calls]
    assert max(sizes) <= 10
    assert sum(sizes) == 23


def test_bundle_sku_is_resolved():
    """Bundle SKUs are written with spaces around the plus on the storefront."""
    bundle = _raw_product(sku="117 + 240", title="45W Oplader 3-Poorts")
    gid = bundle["id"]
    client = StubClient(products={gid: bundle})
    client.initialize()
    product = client.get_product("117 + 240")
    assert product is not None
    assert product.price_min == 18.95


# ---------------------------------------------------------------------------
# the product wrapper
# ---------------------------------------------------------------------------

def test_product_business_skus_strips_variant_suffix():
    product = UCPProduct(id="x", title="t", skus=["231.5", "231", "333"])
    assert product.business_skus == ["231", "333"]


def test_product_description_is_flattened():
    client = StubClient(products={GID_231: _raw_product()})
    client.initialize()
    product = client.get_product(GID_231)
    assert product.description.startswith("<p>")


# ---------------------------------------------------------------------------
# cross-source price reconciliation
# ---------------------------------------------------------------------------

class FakeDB:
    """Minimal database double for the reconciliation path."""

    def __init__(self, catalogue):
        self.catalogue = catalogue
        self.updates = []

    def query(self, sql, params=None):
        if "price_eur" in sql and "products" in sql and "sku_text = ?" in sql:
            sku = params[0]
            row = self.catalogue.get(sku)
            return [row] if row else []
        if "SELECT sku_text FROM products" in sql:
            return [{"sku_text": sku} for sku in self.catalogue]
        return []

    def execute(self, sql, params=None):
        self.updates.append((sql, params))


def test_sync_reports_price_mismatches(monkeypatch):
    """Two sources disagreeing must be reported, not silently resolved."""
    db = FakeDB({"231": {"sku_text": "231", "price_eur": 15.0}})
    client = StubClient(products={GID_231: _raw_product(amount=1895)})

    monkeypatch.setattr(ucp, "sync_ucp_catalog", ucp.sync_ucp_catalog)
    report = ucp.sync_ucp_catalog(db=db, client=client, skus=["231"],
                                  load_into_db=False)
    assert report["resolved"] == 1
    assert len(report["price_mismatches"]) == 1
    assert report["price_mismatches"][0]["catalogue_price"] == 15.0
    assert report["price_mismatches"][0]["ucp_price"] == 18.95


def test_sync_reports_agreeing_prices(monkeypatch):
    db = FakeDB({"231": {"sku_text": "231", "price_eur": 18.95}})
    client = StubClient(products={GID_231: _raw_product(amount=1895)})
    report = ucp.sync_ucp_catalog(db=db, client=client, skus=["231"],
                                  load_into_db=False)
    assert report["price_mismatches"] == []


def test_sync_reports_unresolvable_skus():
    db = FakeDB({})
    client = StubClient(products={})
    report = ucp.sync_ucp_catalog(db=db, client=client, skus=["NOPE"],
                                  load_into_db=False)
    assert report["resolved"] == 0
    assert "NOPE" in report["not_found"]


def test_sync_never_writes_zero_prices():
    """A missing price must never become a zero price."""
    db = FakeDB({"231": {"sku_text": "231", "price_eur": 0}})
    client = StubClient(products={})
    report = ucp.sync_ucp_catalog(db=db, client=client, skus=["231"],
                                  load_into_db=False)
    assert report["resolved"] == 0
    assert db.updates == []


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------

def test_error_detail_handles_string_data():
    """``data`` can be a plain string; calling .get on it used to crash."""
    assert _error_detail({"data": "Too many requests"}) == "Too many requests"
    assert _error_detail({"data": None}) == ""
    assert _error_detail({}) == ""
    assert "42" in _error_detail({"data": {"code": 42}})


class RateLimitedClient(StubClient):
    """A client that gets throttled after the first call."""

    def __init__(self, products=None, fail_after=1):
        super().__init__(products=products)
        self.fail_after = fail_after
        self.seen = 0

    def load_sku_index(self, limit=250):
        """Every SKU resolves, so the throttle is actually reached."""
        index = {str(i): GID_231 for i in range(500)}
        self._sku_index = index
        self._index_loaded = True
        return index

    def call_tool(self, name, arguments, _id=3):
        self.seen += 1
        if self.seen > self.fail_after:
            raise UCPRateLimited(
                "Rate limit exceeded [Too many requests, please retry after 2688 seconds]",
                retry_after=2688,
            )
        return super().call_tool(name, arguments, _id)


def test_rate_limit_stops_the_sync_immediately():
    """A throttled run must not look like an empty catalogue."""
    db = FakeDB({"231": {"sku_text": "231", "price_eur": 18.95}})
    client = RateLimitedClient(products={GID_231: _raw_product()}, fail_after=1)
    report = ucp.sync_ucp_catalog(
        db=db, client=client,
        skus=[str(i) for i in range(50)], load_into_db=False,
    )
    assert report["rate_limited"] is True
    assert report["retry_after_seconds"] == 2688
    assert report["complete"] is False


def test_rate_limit_does_not_fill_not_found():
    """Remaining SKUs must not be recorded as missing when throttled."""
    db = FakeDB({"231": {"sku_text": "231", "price_eur": 18.95}})
    client = RateLimitedClient(products={GID_231: _raw_product()}, fail_after=0)
    report = ucp.sync_ucp_catalog(
        db=db, client=client,
        skus=["231", "232", "233", "234"], load_into_db=False,
    )
    assert report["rate_limited"] is True
    assert report["not_found"] == []


def test_rate_limit_is_an_ucp_error():
    """Callers that only catch UCPError still catch a throttle."""
    assert issubclass(UCPRateLimited, UCPError)


def test_complete_flag_is_true_for_a_clean_run():
    db = FakeDB({"231": {"sku_text": "231", "price_eur": 18.95}})
    client = StubClient(products={GID_231: _raw_product()})
    report = ucp.sync_ucp_catalog(db=db, client=client, skus=["231"],
                                  load_into_db=False)
    assert report["complete"] is True
    assert report["rate_limited"] is False
