"""The unverified school discount must survive EVERY documented setup path.

Regression (2026-10-29): the code default was corrected to 0, but
``.env.example`` still shipped 15 and ``docker-compose.yml`` still
defaulted to 15.  The placeholder flag was keyed on env-PRESENCE, so the
documented setup (``cp .env.example .env``) and the Compose path both
silently cleared the flag and presented an invented percentage as a
confirmed WiseQ rule.

This module covers the paths a fresh copy actually takes:

  1. bare python, no .env
  2. ``cp .env.example .env``   (the README path)
  3. ``docker compose up``      (the handover path)

Each must leave the discount flagged as a placeholder.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiseq.config import Settings  # noqa: E402


def _settings(**env) -> Settings:
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


def _env_example_value(name: str) -> str:
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{name} not found in .env.example")


def _compose_default(name: str) -> str:
    """Extract the ``${NAME:-default}`` fallback from docker-compose.yml."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    m = re.search(rf"{re.escape(name)}:\s*\$\{{{re.escape(name)}:-([^}}]*)\}}", text)
    assert m is not None, f"{name} has no composable default in docker-compose.yml"
    return m.group(1).strip()


# --- path 1: bare python ------------------------------------------------


def test_bare_python_keeps_placeholder():
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=None)
    assert s.school_discount_pct == 0.0
    assert s.school_discount_is_placeholder is True


# --- path 2: cp .env.example .env --------------------------------------


def test_env_example_path_keeps_placeholder():
    value = _env_example_value("WISEQ_SCHOOL_DISCOUNT_PCT")
    assert float(value) == 0.0, (
        f".env.example ships an unverified non-zero discount ({value})"
    )
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=value)
    assert s.school_discount_is_placeholder is True


# --- path 3: docker compose --------------------------------------------


def test_compose_path_keeps_placeholder():
    value = _compose_default("WISEQ_SCHOOL_DISCOUNT_PCT")
    assert float(value) == 0.0, (
        f"docker-compose.yml defaults the discount to {value}; a non-zero "
        "default clears the placeholder flag inside the container"
    )
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=value)
    assert s.school_discount_is_placeholder is True


# --- the flag must be value-based, not presence-based --------------------


def test_flag_is_value_based_not_presence_based():
    """Setting the env var to an unverified value must not clear the flag.

    Both 0 and the legacy demonstration 15 are known-unverified values,
    so neither can be promoted to a confirmed rule by being configured.
    """
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=15, WISEQ_SCHOOL_DISCOUNT_CONFIRMED=None)
    assert s.school_discount_pct == 15.0
    assert s.school_discount_is_placeholder is True, (
        "an explicitly-set unverified value cleared the placeholder flag"
    )

    s0 = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=0, WISEQ_SCHOOL_DISCOUNT_CONFIRMED=None)
    assert s0.school_discount_is_placeholder is True


def test_a_confirmed_value_clears_the_flag():
    """Confirmation needs BOTH a real value and an explicit confirmation."""
    s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=12.5,
                  WISEQ_SCHOOL_DISCOUNT_CONFIRMED="true")
    assert s.school_discount_pct == 12.5
    assert s.school_discount_is_placeholder is False


def test_unverified_value_stays_flagged_even_if_confirmed():
    """0 and 15 can never be confirmed -- they are not WiseQ rules."""
    for value in ("0", "15"):
        s = _settings(WISEQ_SCHOOL_DISCOUNT_PCT=value,
                      WISEQ_SCHOOL_DISCOUNT_CONFIRMED="true")
        assert s.school_discount_is_placeholder is True, (
            f"the unverified value {value} was allowed to be confirmed"
        )


# --- the operator must be able to see it --------------------------------


def test_health_endpoint_exposes_the_placeholder_state():
    """A health check that hides the placeholder lets it pass as a rule."""
    api = (ROOT / "src" / "wiseq" / "api.py").read_text(encoding="utf-8")
    assert "school_discount_is_placeholder" in api, (
        "/health does not expose the placeholder state"
    )
    assert "school_discount_pct" in api


def test_demo_labels_the_placeholder():
    demo = (ROOT / "scripts" / "demo_for_rob.py").read_text(encoding="utf-8")
    assert "PLACEHOLDER, NOT A WISEQ RULE" in demo
    assert "school_discount_is_placeholder" in demo
