"""Tests for the per-page public-site audit.

The audit reads the live storefront, but the PARSING is what can silently
break, and a parser that reports a false finding is worse than no audit
at all: it teaches the reader to ignore the report.

These tests use recorded HTML, so none of them touches the network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_pages  # noqa: E402


# A page shaped like a real Shopify page: Open Graph uses `property`,
# ordinary meta uses `name`, and the two appear in different orders.
SHOPIFY_PAGE = """
<html><head>
<title>Over WiseQ | Veilige technologie voor kinderen</title>
<meta name="description" content="Leer WiseQ kennen.">
<meta property="og:title" content="Over WiseQ">
<meta property="og:description" content="Leer WiseQ kennen.">
<meta property="og:image" content="https://example.invalid/a.png">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="canonical" href="https://www.wiseq.nl/pages/over-ons">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"WiseQ"}
</script>
</head><body><h1>Over WiseQ</h1><p>Op WiseQ-producten geldt 1 jaar garantie.</p></body></html>
"""

REVERSED_ORDER_PAGE = """
<html><head>
<meta content="Achtergrond" name="description">
<meta content="Titel" property="og:title">
</head><body><h1>x</h1></body></html>
"""

NO_OG_PAGE = """
<html><head><title>Kaal</title></head><body><h1>Kaal</h1></body></html>
"""

BROKEN_JSONLD_PAGE = """
<html><head><title>Kapot</title>
<script type="application/ld+json">{not valid json</script>
</head><body><h1>Kapot</h1></body></html>
"""


def test_meta_content_reads_name_attribute():
    assert audit_pages.meta_content(SHOPIFY_PAGE, "description") == "Leer WiseQ kennen."


def test_meta_content_reads_property_attribute():
    """Open Graph uses property=, not name= -- reading only name= misses all OG tags."""
    assert audit_pages.meta_content(SHOPIFY_PAGE, "og:title") == "Over WiseQ"
    assert audit_pages.meta_content(SHOPIFY_PAGE, "og:description") == "Leer WiseQ kennen."
    assert audit_pages.meta_content(SHOPIFY_PAGE, "og:image") == "https://example.invalid/a.png"


def test_meta_content_ignores_attribute_order():
    """Shopify emits meta tags in both orders across pages."""
    assert audit_pages.meta_content(REVERSED_ORDER_PAGE, "description") == "Achtergrond"
    assert audit_pages.meta_content(REVERSED_ORDER_PAGE, "og:title") == "Titel"


def test_meta_content_returns_empty_when_absent():
    assert audit_pages.meta_content(NO_OG_PAGE, "og:title") == ""
    assert audit_pages.meta_content(SHOPIFY_PAGE, "og:nothing") == ""


def test_visible_text_ignores_script_content():
    """A rule mentioned only inside a script is not a published rule."""
    page = (
        "<html><body><script>var x = '5 jaar garantie';</script>"
        "<p>1 jaar garantie</p></body></html>"
    )
    text = audit_pages.visible_text(page)
    assert "1 jaar garantie" in text
    assert "5 jaar garantie" not in text


def test_visible_text_decodes_entities():
    text = audit_pages.visible_text("<p>5 &amp; 10 &euro; per stuk</p>")
    assert "5 & 10" in text
    assert "€" in text


def test_json_ld_parses_and_types_are_found():
    blocks = audit_pages.json_ld_blocks(SHOPIFY_PAGE)
    assert len(blocks) == 1
    assert audit_pages.schema_types(blocks) == ["Organization"]


def test_malformed_json_ld_is_reported_not_swallowed():
    blocks = audit_pages.json_ld_blocks(BROKEN_JSONLD_PAGE)
    assert len(blocks) == 1
    assert blocks[0].get("__parse_error__") is True


def test_canonical_is_extracted():
    assert audit_pages.canonical_of(SHOPIFY_PAGE) == "https://www.wiseq.nl/pages/over-ons"


def test_claims_are_read_from_visible_text():
    claims = audit_pages.claims_from(audit_pages.visible_text(SHOPIFY_PAGE))
    assert claims["warranty_years"] == 1


def test_cross_check_flags_a_warranty_contradiction():
    pages = [
        {"url": "https://www.wiseq.nl/pages/a", "claims": {"warranty_years": 1}},
        {"url": "https://www.wiseq.nl/pages/b", "claims": {"warranty_years": 2}},
    ]
    findings = audit_pages.cross_check(pages)
    assert len(findings) == 1
    assert findings[0]["rule"] == "warranty years"
    assert set(findings[0]["values"]) == {"1", "2"}


def test_cross_check_is_quiet_when_pages_agree():
    pages = [
        {"url": "https://www.wiseq.nl/pages/a", "claims": {"warranty_years": 2}},
        {"url": "https://www.wiseq.nl/pages/b", "claims": {"warranty_years": 2}},
    ]
    assert audit_pages.cross_check(pages) == []


def test_cross_check_ignores_unrelated_rules():
    """A page that states no warranty does not create a contradiction."""
    pages = [
        {"url": "https://www.wiseq.nl/pages/a", "claims": {"warranty_years": 1}},
        {"url": "https://www.wiseq.nl/pages/b", "claims": {"staffel": True}},
    ]
    assert audit_pages.cross_check(pages) == []


def test_urlparse_path_drops_the_query():
    """The sitemap child URL carries a ?from=&to= range; it must be dropped."""
    assert audit_pages.urlparse_path(
        "https://www.wiseq.nl/sitemap_pages_1.xml?from=1&to=2"
    ) == "https://www.wiseq.nl/sitemap_pages_1.xml"


def test_urlparse_path_keeps_the_marker_needed_for_routing():
    """discover_urls routes on the sitemap name, so it must survive."""
    path = audit_pages.urlparse_path(
        "https://www.wiseq.nl/sitemap_pages_1.xml?from=1&to=2"
    )
    assert "sitemap_pages" in path


def test_report_renders_contradiction_with_its_pages():
    result = {
        "observed": "2026-10-30",
        "discovered": {"pages": 2, "collections": 0, "blogs": 0,
                       "articles": 0, "products": 0, "agentic": 0},
        "audited": {"pages": 2, "products_sampled": 0},
        "pages": [
            {"url": "https://www.wiseq.nl/pages/a", "status": 200, "word_count": 10,
             "h1_count": 1, "schema_types": ["Organization"], "claims": {"warranty_years": 1}},
            {"url": "https://www.wiseq.nl/pages/b", "status": 200, "word_count": 10,
             "h1_count": 1, "schema_types": [], "claims": {"warranty_years": 2}},
        ],
        "findings": [{
            "rule": "warranty years",
            "severity": "contradiction",
            "values": {"1": ["/pages/a"], "2": ["/pages/b"]},
            "pages": ["/pages/a", "/pages/b"],
            "explanation": "Pages disagree.",
        }],
        "issues": {"unreachable": [], "noindex": [], "missing_meta_description": [],
                   "missing_canonical": [], "missing_structured_data": [],
                   "malformed_structured_data": [], "missing_h1": [],
                   "multiple_h1": [], "missing_viewport": [], "missing_open_graph": []},
    }
    report = audit_pages.render_report(result)
    assert "CONTRADICTION" in report
    assert "/pages/a" in report
    assert "/pages/b" in report
    assert "Pages disagree." in report


# -- HTML vs plain-text resources ------------------------------------------

def test_markdown_resources_are_not_judged_by_html_rules():
    """The agent brief is Markdown; holding it to "has an h1" is noise."""
    assert audit_pages.is_html_resource("https://www.wiseq.nl/pages/over-ons")
    assert audit_pages.is_html_resource("https://www.wiseq.nl/blogs/nieuws/x")
    assert not audit_pages.is_html_resource("https://www.wiseq.nl/agents.md")
    assert not audit_pages.is_html_resource("https://www.wiseq.nl/sitemap.xml")
    assert not audit_pages.is_html_resource("https://www.wiseq.nl/products.json")


def test_markdown_resource_is_not_flagged_for_missing_html():
    """A Markdown resource must not show up as missing canonical/viewport."""
    assert audit_pages.is_html_resource("https://www.wiseq.nl/agents.md") is False
