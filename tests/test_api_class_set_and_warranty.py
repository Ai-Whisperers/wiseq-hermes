"""API surface for class-set sizing and warranty decisions.

These two endpoints turn rules that WiseQ publishes (the sizing table)
and rules that live in the client's operating manual (the repair price
list) into a deterministic, approval-gated API.

The properties that matter for a school quote:

  * a quantity is never guessed -- an unrecognised use model is a 422,
    not a default;
  * the attrition allowance never exceeds the published 10-15% band;
  * the warranty decision always requires human approval;
  * no price is computed, because the staffel ladder is not public.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def client(api_client):
    """The API requires a token for writes; the shared fixture sends one."""
    return api_client


# ------------------------------------------------------------------
# class-set sizing
# ------------------------------------------------------------------

def test_class_set_sizing_shared_per_building(client):
    r = client.post("/school/class-set-sizing", json={
        "pupils": 200,
        "use_model": "Gedeelde set per bouw (roulerend)",
        "largest_group": 120,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["use_model"] == "shared_per_building"
    assert body["base_quantity"] == 120
    assert body["total_quantity"] == 132   # largest group + 10%
    assert body["source"].endswith("klassenset-koptelefoons-kopen-school")


def test_class_set_sizing_never_guesses_the_use_model(client):
    """An unrecognised model must be an explicit error, not a default."""
    r = client.post("/school/class-set-sizing", json={
        "pupils": 30, "use_model": "gewoon een paar koptelefoons"})
    assert r.status_code == 422
    assert "niet herkend" in r.json()["detail"]


def test_class_set_sizing_rejects_a_non_positive_pupil_count(client):
    r = client.post("/school/class-set-sizing", json={
        "pupils": 0, "use_model": "Gedeelde set per lokaal"})
    assert r.status_code == 422


def test_class_set_sizing_rejects_an_out_of_range_attrition(client):
    """Only the published 10-15% band is accepted."""
    r = client.post("/school/class-set-sizing", json={
        "pupils": 30, "use_model": "Gedeelde set per lokaal",
        "attrition_pct": 40})
    assert r.status_code == 422


def test_class_set_sizing_returns_no_price(client):
    """The staffel ladder is not public, so no total may be quoted."""
    r = client.post("/school/class-set-sizing", json={
        "pupils": 100, "use_model": "Eigen setje per leerling"})
    body = r.json()
    assert "total_price" not in body
    assert "price" not in body
    assert "total_eur" not in body


def test_class_set_sizing_flags_a_missing_device_count(client):
    r = client.post("/school/class-set-sizing", json={
        "pupils": 30, "use_model": "Gedeelde set per lokaal"})
    assert r.status_code == 200
    notes = " ".join(r.json()["notes"])
    assert "Device count not given" in notes


def test_class_set_sizing_suggests_models_for_an_age_group(client):
    r = client.post("/school/class-set-sizing", json={
        "pupils": 25, "use_model": "Gedeelde set per lokaal",
        "devices": 25, "age_group": "Groep 1 t/m 3"})
    assert "Junior" in " ".join(r.json()["suggested_models"])


# ------------------------------------------------------------------
# warranty
# ------------------------------------------------------------------

def test_warranty_decision_returns_a_policy_justification(client):
    r = client.post("/school/warranty-decision", json={
        "model": "WiseQ Unbreakable", "months_used": 4,
        "damage_type": "physical_break"})
    assert r.status_code == 200
    body = r.json()
    assert body["covered"] is False
    assert body["discount_pct"] == 50
    assert "Unbreakable" in body["reason"]
    assert body["policy_source"]


def test_warranty_decision_always_needs_approval(client):
    r = client.post("/school/warranty-decision", json={
        "model": "WiseQ One", "months_used": 2,
        "damage_type": "physical_break"})
    assert r.json()["needs_approval"] is True


def test_warranty_decision_rejects_an_unknown_damage_type(client):
    r = client.post("/school/warranty-decision", json={
        "model": "WiseQ One", "months_used": 2,
        "damage_type": "vibes"})
    assert r.status_code == 422


def test_warranty_decision_rejects_a_negative_age(client):
    r = client.post("/school/warranty-decision", json={
        "model": "WiseQ One", "months_used": -1,
        "damage_type": "physical_break"})
    assert r.status_code == 422


def test_warranty_discount_is_not_a_school_discount(client):
    """The repair percentage must not be presented as a school rule."""
    r = client.post("/school/warranty-decision", json={
        "model": "WiseQ One", "months_used": 30,
        "damage_type": "no_physical_break"})
    body = r.json()
    assert "school" not in body["reason"].lower()
