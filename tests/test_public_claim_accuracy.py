"""Regression tests for public-claim accuracy in the Rob-facing documents.

Each test here locks in a correction made on 2026-10-29 after verifying
the live source.  They fail if the documents drift back to a claim the
live site does not support.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "docs" / "MARKET-AND-PROCUREMENT-FINDINGS.md"
FINDINGS = ROOT / "docs" / "PUBLIC-DATA-FINDINGS.md"
HANDOVER = ROOT / "docs" / "HANDOVER.md"

AGENTS_MD = (
    "Passief, ongeveer 13 dB demping",  # Unbreakable row
    "Actief (ANC)",  # Kids ANC row
    "De Unbreakable heeft een volumebegrenzing van",
)


def _text(path: Path) -> str:
    assert path.exists(), f"missing document: {path}"
    return path.read_text(encoding="utf-8")


def test_documents_exist():
    for p in (MARKET, FINDINGS, HANDOVER):
        assert p.exists(), p


# --- SamitaWS is WiseQ's own Shopify app, not a school registry ----------


def test_samitaws_is_described_as_a_shopify_app():
    t = _text(MARKET)
    assert "Sami B2B Wholesale Pricing" in t
    assert "apps.shopify.com/wholesale-sami" in t
    assert "SamitaWSRegistrationForm" in t


def test_samitaws_is_not_called_a_registry_or_supplier_vetting_body():
    """The document must not assert SamitaWS is a Dutch school registry."""
    t = _text(MARKET)
    # Any sentence mentioning SamitaWS and "registry" must also contain a
    # negation, i.e. it is correcting the myth rather than repeating it.
    for sentence in re.split(r"(?<=[.!])\s+", t):
        if "samita" not in sentence.lower():
            continue
        if "registry" in sentence.lower() or "register" in sentence.lower():
            assert re.search(
                r"\bnot\b|\bno\b|corrected|isn't|is not",
                sentence,
                re.I,
            ), f"sentence repeats the SamitaWS-registry myth: {sentence[:200]}"


def test_handover_states_staffel_ladder_is_not_publicly_syncable():
    t = _text(HANDOVER)
    assert "Sami" in t
    assert "not a Dutch school" in t or "not a Dutch school procurement registry" in t


# --- 13 dB is passive attenuation, not a volume limit --------------------


def test_13db_is_attributed_to_unbreakable_not_hero():
    """The 13 dB figure belongs to the Unbreakable, per agents.md."""
    t = _text(MARKET)
    # The Hero row must not carry the 13 dB figure.
    for line in t.splitlines():
        if line.strip().startswith("| Hero |"):
            assert "13 dB" not in line, f"13 dB wrongly attributed to Hero: {line}"
        if line.strip().startswith("| Unbreakable |"):
            assert "13 dB" in line, "Unbreakable row lost the 13 dB attenuation figure"


def test_13db_is_never_described_as_a_volume_limit():
    """A *claim* that 13 dB is the volume limit is forbidden.

    A sentence that contrasts 13 dB with the volume limiter is fine --
    that is the correction.  So the check is on the assertive form:
    "volume limit is 13 dB", "13 dB volume limit", "volumebegrenzing van 13 dB".
    """
    t = _text(MARKET)
    forbidden = [
        r"volume\s+limit(?:er)?\s+(?:is|van|of)\s+13\s*dB",
        r"13\s*dB\s+volume\s+limit(?:er)?",
        r"volume\s+begrenzing\s+van\s+13\s*dB",
        r"13\s*dB\s+volumebegrenzing",
    ]
    for pat in forbidden:
        m = re.search(pat, t, re.I)
        assert m is None, f"13 dB asserted as a volume limit: {m.group(0)!r}"


def test_volume_limiter_figures_are_present():
    t = _text(MARKET)
    assert "85 dB" in t
    assert "93 dB" in t  # Unbreakable limiter, switchable to 85 dB


def test_only_kids_anc_is_described_as_active():
    t = _text(MARKET)
    assert "Kids ANC" in t
    assert "the only ANC model" in t or "het enige WiseQ-model met actieve" in t


# --- Warranty: three positions, not two ----------------------------------


def test_warranty_section_lists_three_positions():
    t = _text(FINDINGS)
    assert "three live public positions" in t.lower()
    # All three surfaces must be named.
    assert "algemene-voorwaarden" in t
    assert "ict-voor-onderwijs" in t
    assert "Amazon.nl" in t


def test_warranty_section_records_physical_damage_as_the_discriminator():
    """Term length alone is not enough to route a claim."""
    t = _text(FINDINGS)
    lowered = t.lower()
    assert "physical damage" in lowered or "fysieke schade" in lowered
    assert "included" in lowered


def test_old_wrong_conclusion_is_gone():
    """The previous 'under-promising, quick win' conclusion must be removed.

    The phrase may still appear inside the explicit correction, so the
    check is that it is not asserted -- i.e. the sentence containing it
    must also mark it as no longer supportable.
    """
    t = _text(FINDINGS)
    for sentence in re.split(r"(?<=[.!])\s+", t):
        if "under-promising" in sentence.lower():
            assert re.search(
                r"no longer supportable|correction|earlier draft|previously",
                sentence,
                re.I,
            ), f"stale 'under-promising' conclusion asserted: {sentence[:200]}"


# --- SIVON device rounds are Chromebook specs, not WiseQ's market --------


def test_sivon_round_is_described_as_chromebook_not_wiseq_target():
    t = _text(MARKET)
    assert "Chromebook" in t
    assert "Ronde 11" in t
    assert "does not describe any product" in t or "covers none of your products" in t


def test_eduv_is_described_as_conditional():
    t = _text(MARKET)
    assert "intent declaration" in t or "intentieverklaring" in t
    assert "not retrievable" in t


def test_handover_carries_the_three_new_decisions():
    t = _text(HANDOVER)
    assert "fifteen things" in t
    assert "Edu-V" in t
    assert "13 dB" in t
    assert "Sami" in t
