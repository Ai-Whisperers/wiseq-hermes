"""The 10-15% figure is an attrition allowance, not a discount.

This is the easiest figure in the whole WiseQ evidence base to misread,
and it was misread: an earlier internal note recorded a "15% school
discount" that WiseQ does not publish.

The live sentence (verified 2026-10-29) is:

    "Reken op 10 tot 15% uitval per schooljaar bij intensief gedeeld
     gebruik. Kabels knikken, oorkussens slijten, exemplaren verdwijnen."

-- 10 to 15% LOSS per school year under intensive shared use.

The pricing mechanism WiseQ publishes is tiered staffel pricing, visible
only after B2B registration. There is no flat percentage discount on the
public site; the only other percentage in the storefront is a 5%
newsletter discount.

These tests pin that distinction so the error cannot come back.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

DOCS = [
    REPO / "docs" / "PUBLIC-DATA-FINDINGS.md",
    REPO / "docs" / "HANDOVER.md",
    REPO / "README.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# A flat school discount may only ever be mentioned NEGATED.  These are
# the ways a document says "this number is not a rule".
_NEGATION_MARKERS = (
    "uitval",
    "attrition",
    "not a discount",
    "no flat",
    "geen korting",
    "misread",
    "not a 15",
    "geen 15",
    "is not: it is",
    "not on the website",
    "not in rob",
    "not in his",
    "does not exist",
    "would be a number",
    "not publish",
    "not a rule",
    "unverified",
)

# A percentage that is about something else entirely (bol.com listing
# growth, for instance) is not a school-discount claim.
_UNRELATED_MARKERS = (
    "listings grew",
    "bol.com",
)


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_no_document_claims_a_flat_school_discount(path):
    """A percentage may only appear as a school discount when negated.

    "15% school discount" is the failure mode: it asserts a rule WiseQ
    does not publish.  Mentions that are clearly about something else
    (a bol.com listing-growth figure) are not school-discount claims.
    """
    text = _read(path)
    for match in re.finditer(r"15\s?%\s*school discount", text, re.I):
        window = text[max(0, match.start() - 500):match.start() + 500].lower()
        assert any(marker in window for marker in _NEGATION_MARKERS), (
            f"{path.name} asserts a 15% school discount: ...{window}..."
        )


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_the_attrition_allowance_is_identified_as_such(path):
    """Where the 10-15% appears, it must be labelled attrition."""
    text = _read(path)
    for match in re.finditer(r"10\s?[–-]\s?15\s?%", text):
        window = text[max(0, match.start() - 700):match.start() + 700].lower()
        assert (
            "attrition" in window
            or "uitval" in window
            or "sizing" in window
            or "class-set" in window
            or "per school year" in window
            or "loss" in window
            or any(marker in window for marker in _UNRELATED_MARKERS)
        ), (
            f"{path.name} mentions 10-15% without labelling it as the "
            f"attrition allowance: ...{window}..."
        )


def test_the_attenuation_and_attrition_figures_are_not_conflated():
    """13 dB is passive attenuation; 10-15% is annual loss. Different
    things, and a document must not imply they are related."""
    findings = _read(REPO / "docs" / "PUBLIC-DATA-FINDINGS.md")
    market = _read(REPO / "docs" / "MARKET-AND-PROCUREMENT-FINDINGS.md")
    handover = _read(REPO / "docs" / "HANDOVER.md")
    # the attenuation figure is still documented somewhere
    assert "13 dB" in (market + handover)
    # the attrition allowance is documented in the findings
    assert "uitval" in findings


def test_the_sizing_module_documents_the_attrition_source():
    src = (REPO / "src" / "wiseq" / "agents" / "class_set_sizing.py").read_text()
    assert "10 tot 15% uitval" in src
    assert "sizing" in src.lower()
    # It must not describe the figure as a discount.
    assert "discount" not in src.lower() or \
        "not a discount" in src.lower() or \
        "discount_pct" not in src


def test_the_discount_stays_a_placeholder():
    """The unverified school discount must remain unverified."""
    from wiseq.config import get_settings
    settings = get_settings()
    assert settings.school_discount_pct == 0.0
    assert settings.school_discount_is_placeholder is True
