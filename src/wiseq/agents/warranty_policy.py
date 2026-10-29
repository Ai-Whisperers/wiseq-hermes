"""Warranty and repair pricing policy.

WiseQ's public pages conflict with each other and with the internal
operating manual:

  * General terms (https://www.wiseq.nl/pages/algemene-voorwaarden):
    "fabrieksgarantie van 1 jaar".
  * School-facing pages: a stronger two-year promise, in at least one
    page including physical damage.
  * Amazon listings and the internal manual: "2 jaar productgarantie".

The internal manual (data/client/Handleiding_opzet.txt) is the
authoritative source for what the business ACTUALLY DOES, and it settles
the contradiction: the warranty period is two years for normal physical
wear-and-tear, and out-of-warranty repairs are handled with a discount
schedule rather than refused.

Source (verified 2026-10-29, data/client/Handleiding_opzet.txt):

    Stuk maar geen fysieke breuk:
      Binnen 2 jaar: nieuwe opsturen
      Buiten 2 jaar: buiten garantie - 30% korting

    Fysieke breuk - Breuk zonder specifieke reden:
      One, Junior en Hero
        0-6 maanden   - Garantie - nieuwe opsturen
        6-12 maanden  - Geen garantie - 30% korting
        Na 12 maanden - Geen garantie - 30% korting
      Unbreakable en ANC
        0-3 maanden   - Garantie - nieuwe opsturen
        3-6 maanden   - Geen garantie - 50% korting
        6-12 maanden  - Geen garantie - 30% korting
        Na 12 maanden - Geen garantie - 30% korting

    Breuk door eigen schuld (geven ze zelf aan):
      One, Junior en Hero:
        0-6 maanden - 50% korting
        6-12 maanden - 30% korting
        Na 12 maanden - 30% korting
      Unbreakable en ANC:
        Altijd 30% korting
        Als ze hier niet mee akkoord gaan verhogen naar 50% korting

    BT Wireless - Nieuwe opsturen mits binnen 1 jaar anders buiten garantie

This module only CLASSIFIES and PROPOSES.  It never sends a message, and
it never issues a refund: the repair decision is a human approval, and
the discount schedule is a commercial policy Rob must approve before it
is shown to a customer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DamageType(str, Enum):
    """The three damage categories the manual distinguishes."""

    NO_PHYSICAL_BREAK = "no_physical_break"
    PHYSICAL_BREAK = "physical_break"
    OWN_FAULT = "own_fault"


class ModelFamily(str, Enum):
    """Model families with different physical-break windows."""

    ONE_JUNIOR_HERO = "one_junior_hero"
    UNBREAKABLE_ANC = "unbreakable_anc"
    BT_WIRELESS = "bt_wireless"

    @property
    def label(self) -> str:
        return {
            ModelFamily.ONE_JUNIOR_HERO: "One, Junior en Hero",
            ModelFamily.UNBREAKABLE_ANC: "Unbreakable en ANC",
            ModelFamily.BT_WIRELESS: "BT Wireless",
        }[self]


# "One, Junior en Hero" / "Unbreakable en ANC" / "BT Wireless"
_FAMILY_ALIASES: dict[str, ModelFamily] = {
    "one": ModelFamily.ONE_JUNIOR_HERO,
    "junior": ModelFamily.ONE_JUNIOR_HERO,
    "hero": ModelFamily.ONE_JUNIOR_HERO,
    "one junior hero": ModelFamily.ONE_JUNIOR_HERO,
    "one, junior en hero": ModelFamily.ONE_JUNIOR_HERO,
    "unbreakable": ModelFamily.UNBREAKABLE_ANC,
    "anc": ModelFamily.UNBREAKABLE_ANC,
    "kids anc": ModelFamily.UNBREAKABLE_ANC,
    "unbreakable en anc": ModelFamily.UNBREAKABLE_ANC,
    "bt wireless": ModelFamily.BT_WIRELESS,
    "bt": ModelFamily.BT_WIRELESS,
}


def resolve_model_family(text: str) -> Optional[ModelFamily]:
    """Map a model name to its family, or None when unknown."""
    if not text:
        return None
    hay = " ".join(text.strip().lower().split())
    best: Optional[tuple[int, ModelFamily]] = None
    for alias, family in _FAMILY_ALIASES.items():
        if alias in hay:
            if best is None or len(alias) > best[0]:
                best = (len(alias), family)
    return best[1] if best else None


@dataclass
class WarrantyDecision:
    """The policy outcome for one repair case.

    covered:        True when the business replaces under warranty.
    months_used:    age of the device at the time of the case.
    discount_pct:   the discount offered on a replacement when the case
                    is not covered (0 when covered).
    replace:        True when a replacement should be sent.
    reason:         a human-readable justification, in Dutch, quoting the
                    policy row that was applied.
    needs_approval: always True -- a repair decision is a human call and
                    this module only proposes.
    policy_source:  where the rule came from, so the output is auditable.

    NOTE: discount_pct is a REPLACEMENT DISCOUNT, not a price.  It is
    applied to the product price by the caller.  It is never a school
    discount and never a staffel price.
    """

    covered: bool
    months_used: int
    discount_pct: int
    replace: bool
    reason: str
    needs_approval: bool = True
    policy_source: str = "Handleiding_opzet.txt (wiselyq internal manual)"

    def as_dict(self) -> dict:
        return {
            "covered": self.covered,
            "months_used": self.months_used,
            "discount_pct": self.discount_pct,
            "replace": self.replace,
            "reason": self.reason,
            "needs_approval": self.needs_approval,
            "policy_source": self.policy_source,
        }


# --- the policy tables, transcribed from the manual --------------------
# (family, damage type, max months inclusive, covered, discount_pct)

_NO_BREAK_ROWS: list[tuple[int, bool, int]] = [
    # (months inclusive, covered, discount_pct)
    (24, True, 0),   # binnen 2 jaar: nieuwe opsturen
    (10**9, False, 30),  # buiten 2 jaar: 30% korting
]

_BREAK_ROWS: dict[ModelFamily, list[tuple[int, bool, int]]] = {
    ModelFamily.ONE_JUNIOR_HERO: [
        (6, True, 0),    # 0-6 maanden: garantie
        (12, False, 30),  # 6-12 maanden: 30% korting
        (10**9, False, 30),  # na 12 maanden: 30% korting
    ],
    ModelFamily.UNBREAKABLE_ANC: [
        (3, True, 0),    # 0-3 maanden: garantie
        (6, False, 50),  # 3-6 maanden: 50% korting
        (12, False, 30),  # 6-12 maanden: 30% korting
        (10**9, False, 30),  # na 12 maanden: 30% korting
    ],
}

_OWN_FAULT_ROWS: dict[ModelFamily, list[tuple[int, int]]] = {
    # (months inclusive, discount_pct)
    ModelFamily.ONE_JUNIOR_HERO: [
        (6, 50),   # 0-6 maanden: 50% korting
        (12, 30),  # 6-12 maanden: 30% korting
        (10**9, 30),  # na 12 maanden: 30% korting
    ],
    ModelFamily.UNBREAKABLE_ANC: [
        (10**9, 30),  # altijd 30% korting
    ],
}

# BT Wireless: "Nieuwe opsturen mits binnen 1 jaar anders buiten garantie"
_BT_WIRELESS_WARRANTY_MONTHS = 12


def _pick(rows: list[tuple[int, bool, int]], months: int) -> tuple[bool, int]:
    for max_months, covered, discount in rows:
        if months <= max_months:
            return covered, discount
    return rows[-1][1], rows[-1][2]


def decide_warranty(model: str, months_used: int, damage_type: DamageType,
                    customer_admitted_fault: bool = True) -> WarrantyDecision:
    """Classify a repair case and propose the commercial outcome.

    customer_admitted_fault: for OWN_FAULT this is the customer's own
    statement ("geven ze zelf aan").  It defaults to True because the
    manual's own-fault schedule only applies when the customer says so;
    when it is False the case is treated as a physical break without
    specific reason, which is the more customer-friendly reading.
    """
    if months_used < 0:
        raise ValueError("months_used cannot be negative")

    family = resolve_model_family(model)
    if family is None:
        return WarrantyDecision(
            covered=False, months_used=months_used, discount_pct=0,
            replace=False,
            reason=(
                "Modelfamilie niet herkend. De handleiding kent aparte "
                "regels voor One/Junior/Hero, Unbreakable/ANC en BT "
                "Wireless. Stel de juiste garantiebehandeling vast "
                "voordat je een antwoord stuurt."),
            needs_approval=True,
        )

    # Own fault only applies to physical breaks, and only when the
    # customer has admitted it.
    effective_damage = damage_type
    if damage_type is DamageType.OWN_FAULT and not customer_admitted_fault:
        effective_damage = DamageType.PHYSICAL_BREAK

    if family is ModelFamily.BT_WIRELESS:
        if months_used <= _BT_WIRELESS_WARRANTY_MONTHS:
            return WarrantyDecision(
                covered=True, months_used=months_used, discount_pct=0,
                replace=True,
                reason=(
                    "BT Wireless: nieuwe opsturen mits binnen 1 jaar "
                    f"(nu {months_used} maanden)."),
            )
        return WarrantyDecision(
            covered=False, months_used=months_used, discount_pct=0,
            replace=False,
            reason=(
                "BT Wireless: buiten 1 jaar garantie. De handleiding geeft "
                "hiervoor geen kortingregel; stel de behandeling vast."),
        )

    if effective_damage is DamageType.NO_PHYSICAL_BREAK:
        covered, discount = _pick(_NO_BREAK_ROWS, months_used)
        if covered:
            reason = ("Stuk maar geen fysieke breuk: binnen 2 jaar "
                      f"nieuwe opsturen (nu {months_used} maanden).")
        else:
            reason = ("Stuk maar geen fysieke breuk: buiten 2 jaar geen "
                      "garantie, 30% korting (nu "
                      f"{months_used} maanden).")
        return WarrantyDecision(covered=covered, months_used=months_used,
                                discount_pct=discount, replace=covered,
                                reason=reason)

    if effective_damage is DamageType.OWN_FAULT:
        rows = _OWN_FAULT_ROWS[family]
        for max_months, discount in rows:
            if months_used <= max_months:
                break
        if family is ModelFamily.UNBREAKABLE_ANC:
            reason = ("Breuk door eigen schuld (klant geeft zelf aan): "
                      "Unbreakable/ANC altijd 30% korting. Gaat de klant "
                      "niet akkoord, dan verhogen naar 50% korting.")
        else:
            reason = ("Breuk door eigen schuld (klant geeft zelf aan): "
                      f"{discount}% korting (nu {months_used} maanden).")
        return WarrantyDecision(covered=False, months_used=months_used,
                                discount_pct=discount, replace=False,
                                reason=reason)

    # PHYSICAL_BREAK without specific reason
    covered, discount = _pick(_BREAK_ROWS[family], months_used)
    if covered:
        reason = ("Fysieke breuk zonder specifieke reden: binnen de "
                  f"garantietermijn nieuwe opsturen (nu {months_used} "
                  f"maanden, {family.label}).")
    else:
        reason = ("Fysieke breuk zonder specifieke reden: geen garantie, "
                  f"{discount}% korting (nu {months_used} maanden, "
                  f"{family.label}).")
    return WarrantyDecision(covered=covered, months_used=months_used,
                            discount_pct=discount, replace=covered,
                            reason=reason)
