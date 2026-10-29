"""Shipping-rule resolution -- the unfranked-shipment guard."""
import pytest

from wiseq.domain.models import FramingStatus, OrderLine, ValidationStatus
from wiseq.domain.shipping import ShippingResolver, infer_category


def _resolver(loaded):
    from wiseq.orchestrator import build_resolver
    return build_resolver(loaded)


def test_light_cable_resolves_to_a_framed_rule(loaded):
    resolver = _resolver(loaded)
    line = OrderLine(sku="207", title="USB-C naar USB-C Oplaadkabel - 1 Meter", quantity=10,
                     weight_gram=60)
    decision = resolver.resolve(line, country="NL")
    assert decision.framing_status is FramingStatus.FRAMED, decision.reason
    assert decision.carrier
    assert decision.shipping_eur > 0


def test_adapters_over_50g_resolve(loaded):
    resolver = _resolver(loaded)
    line = OrderLine(sku="106", title="USB Adapter Snellader 25W", quantity=25,
                     weight_gram=120)
    decision = resolver.resolve(line, country="NL")
    assert decision.framing_status is FramingStatus.FRAMED, decision.reason


def test_unvalidated_rule_never_claims_framed(loaded):
    """USB HUBS is CASE_BY_CASE -- it must never be auto-applied."""
    resolver = _resolver(loaded)
    line = OrderLine(sku="900", title="USB Hub 7 poorts", quantity=2, weight_gram=300)
    decision = resolver.resolve(line, country="NL")
    assert decision.framing_status is not FramingStatus.FRAMED
    assert decision.framing_status is FramingStatus.NEEDS_CONFIRMATION
    assert "CASE_BY_CASE" in decision.reason


def test_smartwatch_and_tag_are_not_auto_framed(loaded):
    resolver = _resolver(loaded)
    for title in ("Kids Smartwatch S5", "GPS Tag voor kinderen"):
        decision = resolver.resolve(
            OrderLine(sku="x", title=title, quantity=1, weight_gram=50))
        assert decision.framing_status is not FramingStatus.FRAMED, title


def test_headphone_case_rule_needs_confirmation(loaded):
    """'Koptelefooncase' has a blank template EAN -> NEEDS_CONFIRMATION."""
    resolver = _resolver(loaded)
    rule = resolver.rule_for_category("Koptelefooncase")
    assert rule is not None
    assert rule.validation_status is not ValidationStatus.OK


def test_unknown_title_is_unfranked_not_guessed(loaded):
    resolver = _resolver(loaded)
    decision = resolver.resolve(
        OrderLine(sku="zzz", title="Raketmodel Schuim", quantity=1, weight_gram=100))
    assert decision.framing_status is FramingStatus.UNFRANKED


def test_belgium_shipment_gets_be_tariff(loaded):
    resolver = _resolver(loaded)
    line = OrderLine(sku="207", title="USB-C Oplaadkabel 1 Meter", quantity=5,
                     weight_gram=60)
    be = resolver.resolve(line, country="BE")
    nl = resolver.resolve(line, country="NL")
    assert be.shipping_eur != nl.shipping_eur, "BE must use the BE tariff"


def test_category_inference():
    assert infer_category("WiseQ 25W Magnetische Draadloze MagSafe Adapter") == "MagSafe"
    assert infer_category("MagSafe Combinatie Snellader") == "MagSafe Combinatie"
    assert infer_category("USB-C naar USB-C Oplaadkabel 3 Meter") == "Zware kabels"
