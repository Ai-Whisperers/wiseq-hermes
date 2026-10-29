"""The school discount must never be presented as a verified WiseQ rule.

The live site publishes *staffelprijzen* (volume tiers), not a flat
discount, and no percentage appears in the client's operating manual or in
Rob's 2026-10-28 transcript. The default of 15% exists only so the
discount line is visible in the demo -- so the demo has to say so out
loud, and the API has to expose whether the value was ever confirmed.

These tests exist because the failure mode is quiet: an invented
percentage inside a real quotation, and nobody noticing.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiseq.config import Settings  # noqa: E402


def _settings(**env) -> Settings:
    """Build Settings with a controlled environment."""
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        return Settings()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_default_discount_is_flagged_as_placeholder():
    """With nothing configured, the value is 0 and still flagged."""
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=None)
    assert s.school_discount_pct == 0.0
    assert s.school_discount_is_placeholder is True


def test_env_example_shipped_value_keeps_the_placeholder_flag():
    """The documented `cp .env.example .env` setup must not promote 0 to a rule.

    Regression (2026-10-29): .env.example shipped `WISEQ_SCHOOL_DISCOUNT_PCT=15`
    and the placeholder flag was based on env-PRESENCE rather than value, so
    following the README setup turned an invented 15% into a "confirmed"
    discount while the demo claimed it was still a placeholder.
    """
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    shipped = None
    for line in env_example.splitlines():
        if line.strip().startswith("WISEQ_SCHOOL_DISCOUNT_PCT="):
            shipped = line.split("=", 1)[1].strip()
    assert shipped is not None, "WISEQ_SCHOOL_DISCOUNT_PCT missing from .env.example"
    assert float(shipped) == 0.0, (
        f".env.example ships a non-zero unverified discount ({shipped})"
    )

    # And with that exact shipped value the flag must still be on.
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=shipped)
    assert s.school_discount_is_placeholder is True, (
        "the shipped .env.example value silently cleared the placeholder flag"
    )


def test_explicit_discount_is_not_a_placeholder():
    """A real staffel value still needs an explicit confirmation.

    Setting a number in an env file is not evidence that the number came
    from the client, so confirmation is a separate, deliberate signal.
    """
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=12.5,
                  WISEQ_SCHOOL_DISCOUNT_CONFIRMED="true")
    assert s.school_discount_pct == 12.5
    assert s.school_discount_is_placeholder is False


def test_demo_says_the_discount_is_a_placeholder(monkeypatch):
    """The demo Rob watches must not present 15% as WiseQ's rule."""
    demo = ROOT / "scripts" / "demo_for_rob.py"
    source = demo.read_text(encoding="utf-8")
    assert "PLACEHOLDER, NOT A WISEQ RULE" in source
    assert "school_discount_is_placeholder" in source


def test_no_source_comment_claims_the_discount_is_from_the_manual():
    """A false provenance comment is how a placeholder becomes a 'rule'."""
    config = (ROOT / "src" / "wiseq" / "config.py").read_text(encoding="utf-8")
    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and "discount" in stripped.lower():
            assert "manual" not in stripped.lower() or "no percentage appears" in stripped.lower()


def test_env_example_documents_the_placeholder():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "WISEQ_SCHOOL_DISCOUNT_PCT" in env
    # The example must flag it, not just set a number.
    lowered = env.lower()
    assert "placeholder" in lowered or "unverified" in lowered or "staffel" in lowered
