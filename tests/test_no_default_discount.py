"""No code path may apply a school discount that was never configured.

On 2026-10-29 the orchestrator's default was ``discount_pct=15.0``.  Two
callers (``scripts/demo_end_to_end.py`` and ``scripts/verify_all.sh``)
constructed the orchestrator WITHOUT passing a discount, so they silently
applied 15% to a real quote -- taking EUR 34.08 off a EUR 227.22 school
order -- while every document in the repo correctly said that 15% is not
a WiseQ rule.

That is the exact failure this repo had already fixed once in prose
(the docs) but not in code.  These tests pin the code half of it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _orchestrator_discount_default() -> float | None:
    src = (REPO / "src" / "wiseq" / "orchestrator.py").read_text(encoding="utf-8")
    m = re.search(
        r"def __init__\(self,\s*db:\s*Database.*?discount_pct:\s*float\s*\|\s*None\s*=\s*([\d.]+)\s*\)",
        src, re.S,
    )
    if m:
        return float(m.group(1))
    return None


def test_orchestrator_default_is_not_a_hardcoded_percentage():
    """The default must come from settings, not a literal."""
    default = _orchestrator_discount_default()
    assert default is None, (
        f"WiseQOrchestrator still hardcodes discount_pct={default}. "
        "An unset discount must never become a fabricated discount.")


def test_orchestrator_falls_back_to_configured_value(monkeypatch):
    from wiseq.config import get_settings
    from wiseq.orchestrator import WiseQOrchestrator

    settings = get_settings()
    assert settings.school_discount_pct == 0.0, (
        "the shipped default discount must be 0, not a placeholder percentage")

    # constructing without an explicit discount must yield the settings value
    orch = WiseQOrchestrator(db=None)  # type: ignore[arg-type]
    assert orch.discount_pct == settings.school_discount_pct


def test_no_script_constructs_the_orchestrator_without_a_discount():
    """Every caller must pass the discount explicitly."""
    callers = []
    for path in list((REPO / "scripts").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"WiseQOrchestrator\(([^)]*)\)", text, re.S):
            args = m.group(1)
            callers.append((path.name, args))
    assert callers, "no orchestrator construction found -- guard is vacuous"

    for name, args in callers:
        if "discount_pct" in args:
            continue
        # a caller may legitimately omit it if it never quotes
        path = next(p for p in (REPO / "scripts").rglob("*.py") if p.name == name)
        text = path.read_text(encoding="utf-8")
        if "school_order_agent" in text or "quote" in text.lower():
            pytest.fail(
                f"{name} builds the orchestrator without discount_pct but "
                f"quotes school orders -- it would apply the default")


def test_demo_end_to_end_shows_the_placeholder_not_a_bare_zero():
    """The end-to-end demo must label an unset discount honestly."""
    text = (REPO / "scripts" / "demo_end_to_end.py").read_text(encoding="utf-8")
    assert "PLACEHOLDER" in text, (
        "demo_end_to_end.py must label an unset discount as a placeholder")
    assert "school_discount_is_placeholder" in text


def test_no_source_file_hardcodes_a_discount_percentage():
    """No shipped .py file may hardcode a discount percentage.

    A literal default is how the 15% fabrication survived a full audit of
    the documentation: the prose said 0%, the code said 15%.
    """
    offenders = []
    for path in sorted(list((REPO / "src").rglob("*.py"))
                       + list((REPO / "scripts").rglob("*.py"))):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                # a comment explaining the bug is fine
                continue
            # Only a NONZERO literal is a problem: 0 is the honest default
            # and is used legitimately (order model, warranty outcomes).
            for m in re.finditer(r"discount[^=\n]{0,40}=\s*([0-9]+(?:\.[0-9]+)?)\b",
                                 line):
                if float(m.group(1)) != 0.0:
                    offenders.append(f"{path.name}:{i} {stripped[:80]}")
                    break
    assert not offenders, (
        "hardcoded discount percentage(s) found:\n  " + "\n  ".join(offenders))
