"""The UCP discovery check must actually detect drift.

The connector's read-only allow list was written when the connector was
written.  If the storefront adds a read tool, or removes one, or
changes its advertised protocol version, the connector keeps working
against a stale assumption -- and nothing errors.

These tests pin the comparison logic so it can tell the three cases
apart:

  * a read tool the connector does not know about -> DRIFT
  * a write tool the connector blocks on purpose -> NOT drift
  * a tool the connector allows that the server no longer publishes -> DRIFT

The third case matters as much as the first: an allow list that has
drifted ahead of the server means the connector believes it can call a
tool that is not there.
"""
from __future__ import annotations

import json

import pytest

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "discover_ucp", ROOT / "scripts" / "discover_ucp.py")
discover_ucp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discover_ucp)

from wiseq.connectors.ucp import READ_ONLY_TOOLS, WRITE_TOOLS


def _tools(*names):
    return [{"name": n, "description": "", "inputSchema": {}} for n in names]


# -- the comparison -------------------------------------------------

def test_a_known_read_tool_is_covered():
    result = discover_ucp.compare_with_connector(_tools("search_catalog", "get_product"))
    assert "search_catalog" in result["covered"]
    assert result["published_but_unknown"] == []


def test_a_full_read_only_surface_is_fully_covered():
    """With every allowed tool published, nothing is left over."""
    result = discover_ucp.compare_with_connector(_tools(*sorted(READ_ONLY_TOOLS)))
    assert result["covered"] == sorted(READ_ONLY_TOOLS)
    assert result["allowed_but_not_published"] == []
    assert result["published_but_unknown"] == []


def test_a_write_tool_blocked_on_purpose_is_not_drift():
    """A published checkout tool is the system working, not failing.

    The connector must refuse to create or complete a checkout.  A
    storefront that publishes one is the expected case.
    """
    result = discover_ucp.compare_with_connector(_tools("create_checkout", "complete_checkout"))
    assert result["published_but_unknown"] == []
    assert "create_checkout" in result["published_but_blocked_on_purpose"]
    assert "complete_checkout" in result["published_but_blocked_on_purpose"]


def test_an_unclassified_published_tool_is_drift():
    """A new read tool the connector does not know about is drift."""
    result = discover_ucp.compare_with_connector(_tools("search_catalog", "brand_new_tool"))
    assert result["published_but_unknown"] == ["brand_new_tool"]


def test_a_tool_the_server_dropped_is_drift():
    """An allow list that has drifted ahead of the server is drift too."""
    result = discover_ucp.compare_with_connector(_tools("search_catalog"))
    assert "lookup_catalog" in result["allowed_but_not_published"]


def test_the_two_lists_do_not_overlap():
    """A tool cannot be both allowed and blocked."""
    assert not (READ_ONLY_TOOLS & WRITE_TOOLS)


# -- the discovery document ------------------------------------------

def test_the_discovery_document_is_normalised():
    document = {"ucp": {
        "version": "2026-08-25",
        "supported_versions": {"2026-01-23": "https://x/1"},
        "capabilities": {
            "dev.ucp.shopping.checkout": [{"version": "2026-08-25"}],
            "dev.ucp.shopping.cart": [{"version": "2026-08-25"}],
        },
        "services": {"dev.ucp.shopping": [
            {"transport": "mcp", "version": "2026-08-25",
             "endpoint": "https://x/api/ucp/mcp"},
        ]},
        "payment_handlers": [],
    }}
    result = discover_ucp.normalise_discovery(document)
    assert result["version"] == "2026-08-25"
    assert result["supported_versions"] == ["2026-01-23"]
    assert result["capabilities"] == [
        "dev.ucp.shopping.cart", "dev.ucp.shopping.checkout"]
    assert result["capability_versions"]["dev.ucp.shopping.checkout"] == ["2026-08-25"]
    assert result["services"][0]["transport"] == "mcp"


def test_a_discovery_document_without_the_ucp_key_still_normalises():
    """Some servers serve the document unwrapped."""
    document = {"version": "2026-01-23", "capabilities": {}, "services": {}}
    result = discover_ucp.normalise_discovery(document)
    assert result["version"] == "2026-01-23"
    assert result["capabilities"] == []


def test_a_bare_document_does_not_crash():
    assert discover_ucp.normalise_discovery({})["version"] is None
