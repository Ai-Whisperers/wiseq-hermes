"""Class-set sizing and warranty policy.

Both modules encode rules that were read from a real, dated, public or
client source.  The tests here pin the rules so that a future edit
cannot silently change a number a school would be quoted.
"""
from __future__ import annotations

import pytest

from wiseq.agents.class_set_sizing import (ATTRITION_MAX_PCT,
                                            ATTRITION_MIN_PCT, UseModel,
                                            resolve_use_model,
                                            size_class_set, SizingRequest,
                                            suggest_models_for_pupils)
from wiseq.agents.warranty_policy import (DamageType, ModelFamily,
                                          decide_warranty,
                                          resolve_model_family)


# ------------------------------------------------------------------
# use model resolution
# ------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Gedeelde set per lokaal", UseModel.SHARED_PER_ROOM),
    ("we willen een gedeelde set per lokaal", UseModel.SHARED_PER_ROOM),
    ("Gedeelde set per bouw (roulerend)", UseModel.SHARED_PER_BUILDING),
    ("Eigen setje per leerling", UseModel.OWN_PAIR_PER_PUPIL),
    ("Alleen digitale toetsen", UseModel.EXAMS_ONLY),
    ("alleen digitale toetsen, voor de Cito toets",
     UseModel.EXAMS_ONLY),
    ("Individuele leerlingen met prikkelgevoeligheid",
     UseModel.INDIVIDUAL_SENSITIVE),
    ("shared per room", UseModel.SHARED_PER_ROOM),
    ("exams only", UseModel.EXAMS_ONLY),
])
def test_resolve_use_model(text, expected):
    assert resolve_use_model(text) is expected


def test_longest_alias_wins():
    """'eigen setje per leerling' must not be matched as 'eigen setje'."""
    assert resolve_use_model("eigen setje per leerling") is \
        UseModel.OWN_PAIR_PER_PUPIL
    # 'gedeelde set per bouw' must beat the 'per bouw' alias
    assert resolve_use_model("gedeelde set per bouw") is \
        UseModel.SHARED_PER_BUILDING


def test_unknown_use_model_is_none_not_a_guess():
    assert resolve_use_model("we willen gewoon wat koptelefoons") is None
    assert resolve_use_model("") is None


# ------------------------------------------------------------------
# the published sizing table
# ------------------------------------------------------------------

def test_shared_per_room_is_devices_plus_two():
    """'Aantal devices + 2'."""
    r = size_class_set(SizingRequest(pupils=30, use_model=UseModel.SHARED_PER_ROOM,
                                      devices=28))
    assert r.base_quantity == 28
    assert r.table_quantity == 30
    assert r.total_quantity == 30


def test_shared_per_building_is_largest_group_plus_ten_percent():
    """'Grootste groep + 10%'."""
    r = size_class_set(SizingRequest(pupils=200, use_model=UseModel.SHARED_PER_BUILDING,
                                      largest_group=120))
    assert r.base_quantity == 120
    assert r.table_quantity == 132  # 120 * 1.10
    assert r.total_quantity == 132


def test_own_pair_per_pupil_is_pupils_plus_ten_percent():
    """'Leerlingaantal + 10%' -- the PUPIL count, not the largest group."""
    r = size_class_set(SizingRequest(pupils=100, use_model=UseModel.OWN_PAIR_PER_PUPIL))
    assert r.table_quantity == 110


def test_own_pair_ignores_the_largest_group():
    """The +10% is on the pupil count; the largest group is a different
    model's base and must not leak in."""
    r = size_class_set(SizingRequest(pupils=100, use_model=UseModel.OWN_PAIR_PER_PUPIL,
                                      largest_group=40))
    assert r.table_quantity == 110


def test_exams_only_is_largest_exam_group_plus_three():
    """'Grootste toetsgroep + 3'."""
    r = size_class_set(SizingRequest(pupils=120, use_model=UseModel.EXAMS_ONLY,
                                      largest_group=45))
    assert r.table_quantity == 48


def test_individual_sensitive_is_one_per_pupil():
    r = size_class_set(SizingRequest(pupils=8, use_model=UseModel.INDIVIDUAL_SENSITIVE))
    assert r.table_quantity == 8
    assert r.attrition_quantity == 0


def test_percentages_round_up():
    """A 10% buffer on 25 is 2.5 -> 3, never 2."""
    r = size_class_set(SizingRequest(pupils=25, use_model=UseModel.OWN_PAIR_PER_PUPIL))
    assert r.table_quantity == 28


def test_exact_arithmetic_no_float_drift():
    """100 * 1.10 is 110.00000000000001 in binary floating point.

    A naive ceil() would hand a 100-pupil class 111 spares.
    """
    r = size_class_set(SizingRequest(pupils=100, use_model=UseModel.OWN_PAIR_PER_PUPIL))
    assert r.table_quantity == 110
    r2 = size_class_set(SizingRequest(pupils=200,
                                       use_model=UseModel.SHARED_PER_BUILDING,
                                       largest_group=120))
    assert r2.table_quantity == 132


# ------------------------------------------------------------------
# the published attrition allowance
# ------------------------------------------------------------------

def test_attrition_allowance_only_applies_to_shared_use():
    """'10 tot 15% uitval per schooljaar bij intensief gedeeld gebruik'."""
    r = size_class_set(SizingRequest(pupils=30, use_model=UseModel.SHARED_PER_ROOM,
                                      devices=28,
                                      intensive_shared_use=True,
                                      attrition_pct=15))
    assert r.base_quantity == 28
    assert r.attrition_quantity == 5      # ceil(28 * 0.15)
    assert r.total_quantity == 33


def test_attrition_is_not_stacked_on_top_of_the_table_buffer():
    """The table's +10% and the published 10-15% attrition describe the
    SAME spares for shared models.  Stacking them would order ~25%
    spares where WiseQ publishes 10-15%, so the allowance REPLACES the
    table buffer instead."""
    r = size_class_set(SizingRequest(pupils=30, use_model=UseModel.SHARED_PER_ROOM,
                                      devices=28,
                                      intensive_shared_use=True,
                                      attrition_pct=15))
    # 28 devices -> 28 + ceil(28 * 0.15) = 28 + 5 = 33
    assert r.base_quantity == 28
    assert r.attrition_quantity == 5
    assert r.table_quantity == 33
    assert r.total_quantity == 33
    assert any("replaces" in n for n in r.notes)


def test_attrition_range_never_exceeds_the_published_maximum():
    """Whatever the model, the spares must stay within 10-15%."""
    r = size_class_set(SizingRequest(pupils=100, use_model=UseModel.SHARED_PER_ROOM,
                                      devices=100,
                                      intensive_shared_use=True,
                                      attrition_pct=15))
    spares = r.total_quantity - r.base_quantity
    assert spares <= 15 + 1  # ceil rounding may add one unit
    assert spares / r.base_quantity <= 0.16


def test_attrition_not_applied_to_non_shared_models():
    r = size_class_set(SizingRequest(pupils=20, use_model=UseModel.OWN_PAIR_PER_PUPIL,
                                      intensive_shared_use=True))
    assert r.attrition_quantity == 0
    assert any("not shared" in n for n in r.notes)


def test_attrition_pct_outside_the_published_range_is_rejected():
    """Only 10-15% is published; 40% must not be silently accepted."""
    with pytest.raises(ValueError):
        SizingRequest(pupils=10, use_model=UseModel.SHARED_PER_ROOM,
                      attrition_pct=40)
    with pytest.raises(ValueError):
        SizingRequest(pupils=10, use_model=UseModel.SHARED_PER_ROOM,
                      attrition_pct=5)


def test_attrition_defaults_to_the_conservative_end():
    r = size_class_set(SizingRequest(pupils=30, use_model=UseModel.SHARED_PER_ROOM,
                                      devices=28, intensive_shared_use=True))
    assert r.attrition_pct == ATTRITION_MAX_PCT == 15.0


def test_missing_inputs_are_flagged_for_the_operator():
    """A guess must never be silent."""
    r = size_class_set(SizingRequest(pupils=30, use_model=UseModel.SHARED_PER_ROOM))
    assert any("Device count not given" in n for n in r.notes)

    r2 = size_class_set(SizingRequest(pupils=200,
                                       use_model=UseModel.SHARED_PER_BUILDING))
    assert any("Largest group not given" in n for n in r2.notes)


def test_non_positive_pupils_rejected():
    with pytest.raises(ValueError):
        SizingRequest(pupils=0, use_model=UseModel.SHARED_PER_ROOM)


# ------------------------------------------------------------------
# model guidance by age group
# ------------------------------------------------------------------

def test_age_group_model_guidance():
    assert "Junior" in " ".join(suggest_models_for_pupils(25, "Groep 1 t/m 3"))
    assert "One" in " ".join(suggest_models_for_pupils(25, "Groep 4 t/m 8"))
    assert "zwart-blauw" in " ".join(suggest_models_for_pupils(60,
                                                              "Voortgezet onderwijs"))


def test_no_age_group_no_guess():
    assert suggest_models_for_pupils(25, "") == []


# ------------------------------------------------------------------
# warranty policy
# ------------------------------------------------------------------

@pytest.mark.parametrize("model,expected", [
    ("WiseQ One", ModelFamily.ONE_JUNIOR_HERO),
    ("WiseQ Junior", ModelFamily.ONE_JUNIOR_HERO),
    ("WiseQ Hero", ModelFamily.ONE_JUNIOR_HERO),
    ("WiseQ Unbreakable", ModelFamily.UNBREAKABLE_ANC),
    ("WiseQ Kids ANC", ModelFamily.UNBREAKABLE_ANC),
    ("BT Wireless", ModelFamily.BT_WIRELESS),
])
def test_resolve_model_family(model, expected):
    assert resolve_model_family(model) is expected


def test_no_physical_break_within_two_years_is_covered():
    """'Binnen 2 jaar: nieuwe opsturen'."""
    d = decide_warranty("WiseQ One", months_used=18,
                        damage_type=DamageType.NO_PHYSICAL_BREAK)
    assert d.covered is True
    assert d.replace is True
    assert d.discount_pct == 0


def test_no_physical_break_outside_two_years_gets_30_percent():
    """'Buiten 2 jaar: buiten garantie - 30% korting'."""
    d = decide_warranty("WiseQ One", months_used=30,
                        damage_type=DamageType.NO_PHYSICAL_BREAK)
    assert d.covered is False
    assert d.discount_pct == 30


def test_physical_break_one_junior_hero_zero_to_six_months_is_covered():
    d = decide_warranty("WiseQ Hero", months_used=4,
                        damage_type=DamageType.PHYSICAL_BREAK)
    assert d.covered is True
    assert d.discount_pct == 0


def test_physical_break_one_junior_hero_six_to_twelve_months_is_30():
    d = decide_warranty("WiseQ One", months_used=9,
                        damage_type=DamageType.PHYSICAL_BREAK)
    assert d.covered is False
    assert d.discount_pct == 30


def test_physical_break_unbreakable_three_to_six_months_is_50():
    """'3-6 maanden - Geen garantie - 50% korting'."""
    d = decide_warranty("WiseQ Unbreakable", months_used=4,
                        damage_type=DamageType.PHYSICAL_BREAK)
    assert d.covered is False
    assert d.discount_pct == 50


def test_physical_break_unbreakable_zero_to_three_months_is_covered():
    d = decide_warranty("WiseQ Unbreakable", months_used=2,
                        damage_type=DamageType.PHYSICAL_BREAK)
    assert d.covered is True
    assert d.discount_pct == 0


def test_own_fault_one_junior_hero_first_six_months_is_50():
    d = decide_warranty("WiseQ Junior", months_used=3,
                        damage_type=DamageType.OWN_FAULT,
                        customer_admitted_fault=True)
    assert d.covered is False
    assert d.discount_pct == 50


def test_own_fault_unbreakable_is_always_30():
    d = decide_warranty("WiseQ Unbreakable", months_used=40,
                        damage_type=DamageType.OWN_FAULT,
                        customer_admitted_fault=True)
    assert d.discount_pct == 30
    assert "50%" in d.reason  # the manual's escalation note


def test_own_fault_is_only_used_when_the_customer_admitted_it():
    """Without an admission the case is read as a break without
    specific reason, which is the more customer-friendly reading."""
    d = decide_warranty("WiseQ Junior", months_used=3,
                        damage_type=DamageType.OWN_FAULT,
                        customer_admitted_fault=False)
    # physical break, 0-6 months -> covered, not a 50% discount
    assert d.covered is True
    assert d.discount_pct == 0


def test_bt_wireless_within_one_year_is_covered():
    d = decide_warranty("BT Wireless", months_used=6,
                        damage_type=DamageType.NO_PHYSICAL_BREAK)
    assert d.covered is True


def test_bt_wireless_outside_one_year_has_no_published_discount():
    d = decide_warranty("BT Wireless", months_used=18,
                        damage_type=DamageType.NO_PHYSICAL_BREAK)
    assert d.covered is False
    assert d.discount_pct == 0
    assert "geen kortingregel" in d.reason


def test_unknown_model_is_not_guessed():
    d = decide_warranty("Sommig Ander Model", months_used=6,
                        damage_type=DamageType.PHYSICAL_BREAK)
    assert d.covered is False
    assert d.discount_pct == 0
    assert "niet herkend" in d.reason


def test_every_decision_requires_human_approval():
    d = decide_warranty("WiseQ One", months_used=3,
                        damage_type=DamageType.PHYSICAL_BREAK)
    assert d.needs_approval is True


def test_negative_age_rejected():
    with pytest.raises(ValueError):
        decide_warranty("WiseQ One", months_used=-1,
                        damage_type=DamageType.NO_PHYSICAL_BREAK)
