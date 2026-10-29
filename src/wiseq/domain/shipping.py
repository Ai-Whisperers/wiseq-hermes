"""Shipping-rule resolution -- the "ungefrankeerde zendingen" (unfranked shipment) guard.

WiseQ ships through four carriers (LVB, VVB, QLS, PostNL) with a rule per
article category.  The client mastersheet supplies 15 category templates, but
three of them are still flagged ``NEEDS_CONFIRMATION`` / ``CASE_BY_CASE`` or
carry a blank template EAN.  Anything the resolver cannot bind to a *validated*
rule is exactly what would leave the warehouse guessing -- and what generates
unfranked shipments.

This module resolves an order line to (rule, carrier, tariff) and reports
``framed`` / ``needs_confirmation`` / ``unfranked`` accordingly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Carrier, FramingStatus, OrderLine, ShippingRule, Tariff, ValidationStatus

# Category keyword -> rule category, ordered by specificity.
CATEGORY_MATCHERS: list[tuple[str, str]] = [
    (r"mag ?safe", "MagSafe"),
    (r"mag ?safe combinatie", "MagSafe Combinatie"),
    (r"koptelefoon", "Koptelefoons"),
    (r"unbreakable|hero|junior|kids anc", "Koptelefoons"),
    (r"bt wireless|hardcase", "Koptelefoons"),
    (r"oortjes", "Koptelefoons"),
    (r"case", "Koptelefooncase"),
    (r"usb hub", "USB HUBS"),
    (r"smartwatch", "Smartwatch"),
    (r"\btag\b", "Tag"),
    (r"adapter", "Adapters > 50gr"),
    (r"kabel", "Zware kabels"),
    (r"oplaadcombinatie", "Oplaadcombinatie"),
]

# Heavier-first ordering matters: "MagSafe Combinatie" must win over "MagSafe".
_ORDERED_MATCHERS = sorted(CATEGORY_MATCHERS, key=lambda p: -len(p[0]))


def infer_category(title: str, product_type: str = "component") -> str:
    """Best-effort mapping from a product title to a shipping-rule category."""
    low = (title or "").lower()
    for pattern, category in _ORDERED_MATCHERS:
        if re.search(pattern, low):
            return category
    if "combinatie" in low:
        return "Oplaadcombinatie"
    if product_type == "bundle":
        return "Oplaadcombinatie"
    return ""


def refine_cable_category(category: str, title: str,
                           weight_gram: int | None) -> str:
    """Split the cable family into the client's light / heavy variants.

    ``Lichte kabels`` ships on PostNL partijenpost under 50 gram (EUR 1.85);
    ``Zware kabels`` ships on the 50-100 gram band (EUR 2.32).  Picking the
    wrong band is a real cost error on every school shipment, so the split
    is explicit rather than title-only.
    """
    if category not in ("Zware kabels", "Lichte kabels"):
        return category
    low = (title or "").lower()
    if "2x kabel" in low:
        return "2x kabel"
    if "3x kabel" in low:
        return "3x kabel"
    if weight_gram is not None and weight_gram < 50:
        return "Lichte kabels"
    if weight_gram is not None and weight_gram <= 100:
        return "Zware kabels"
    return category


@dataclass(frozen=True)
class CarrierPlan:
    """Which carrier + shipment type applies to a shipping-rule category.

    Derived from the client's own tariff sheet, where every row pairs a
    carrier with a shipment type and an article family:

        PostNL  Partijenpost onder 50 gram  losse kabels en lichte adapters
        PostNL  Partijenpost 50-100 gram     zware kabels / adapters / combi
        LVB     LVB (3XS/2XS/XS/S/M)         opladers, magsafes, oortjes, koptelefoons
        VVB     Brievenbus doosjes / Pakket  opladers, koptelefoons
        QLS     Brievenbus envelop/doosjes, Pakket, Europlus

    ``size_class`` only applies to LVB rows; elsewhere the tariff is matched
    on carrier + shipment type + country.
    """
    carrier: Carrier
    shipment_type: str
    size_class: str | None = None
    # alternative shipment types, tried in order (e.g. a parcel for a bulk order)
    fallbacks: tuple[str, ...] = ()


# category -> plan.  Categories absent from this map have no automatic carrier.
CATEGORY_PLANS: dict[str, CarrierPlan] = {
    "Lichte kabels": CarrierPlan(Carrier.POSTNL, "Partijenpost onder 50 gram"),
    "2x kabel": CarrierPlan(Carrier.POSTNL, "Partijenpost 50-100 gram"),
    "3x kabel": CarrierPlan(Carrier.POSTNL, "Partijenpost 50-100 gram"),
    "Zware kabels": CarrierPlan(Carrier.POSTNL, "Partijenpost 50-100 gram"),
    "Adapters < 50gr": CarrierPlan(Carrier.POSTNL, "Partijenpost onder 50 gram"),
    "Adapters > 50gr": CarrierPlan(Carrier.POSTNL, "Partijenpost 50-100 gram"),
    "Oplaadcombinatie": CarrierPlan(
        Carrier.POSTNL, "Partijenpost 50-100 gram",
        fallbacks=("Partijenpost 100-200 gram", "Partijenpost 200-350 gram")),
    "MagSafe": CarrierPlan(Carrier.LVB, "LVB", size_class="2XS"),
    "MagSafe Combinatie": CarrierPlan(Carrier.LVB, "LVB", size_class="2XS"),
    "Koptelefoons": CarrierPlan(Carrier.VVB, "Pakket NL",
                                fallbacks=("Pakket", "Brievenbus doosjes")),
    "Koptelefooncase": CarrierPlan(Carrier.VVB, "Pakket NL",
                                   fallbacks=("Pakket", "Brievenbus doosjes")),
}


@dataclass(frozen=True)
class ShippingDecision:
    framing_status: FramingStatus
    rule_key: str | None
    carrier: str | None
    tariff_key: str | None
    shipping_eur: float
    reason: str


class ShippingResolver:
    """Resolves order lines against the validated shipping rules + tariffs."""

    def __init__(self, rules: list[ShippingRule], tariffs: list[Tariff]):
        self.rules = {r.rule_key: r for r in rules}
        self._by_category = {r.category.upper(): r for r in rules}
        self.tariffs = list(tariffs)

    # -- lookup --------------------------------------------------------
    def rule_for_category(self, category: str) -> ShippingRule | None:
        return self._by_category.get(category.upper())

    def find_tariff(self, carrier: Carrier, country: str,
                    shipment_type: str, size_class: str | None = None) -> Tariff | None:
        """Match a tariff on carrier + country + shipment type + size class.

        For LVB the size class is the discriminating dimension (several
        article families share the LVB shipment method but not the price),
        so it must match.  For the other carriers the size class is not used.
        """
        candidates = [
            t for t in self.tariffs
            if t.carrier is carrier
            and t.country.upper() == country.upper()
            and t.shipment_type.lower() == shipment_type.lower()
        ]
        if not candidates:
            return None
        if size_class:
            exact = [t for t in candidates if t.size_class == size_class]
            if exact:
                return exact[0]
        return candidates[0]

    # -- resolution ----------------------------------------------------
    def resolve(self, line: OrderLine, country: str = "NL",
                shipment_type: str | None = None,
                is_bulk: bool = False) -> ShippingDecision:
        category = infer_category(line.title, line.product_type)
        if not category:
            return ShippingDecision(
                FramingStatus.UNFRANKED, None, None, None, 0.0,
                "no shipping-rule category could be derived from the title")
        category = refine_cable_category(category, line.title, line.weight_gram)

        rule = self.rule_for_category(category)
        if rule is None:
            return ShippingDecision(
                FramingStatus.UNFRANKED, None, None, None, 0.0,
                f"category '{category}' has no shipping rule")

        if rule.validation_status is not ValidationStatus.OK:
            return ShippingDecision(
                FramingStatus.NEEDS_CONFIRMATION, rule.rule_key, None, None, 0.0,
                f"rule '{category}' is {rule.validation_status.value} "
                f"and cannot be applied automatically")

        if not rule.template_ean:
            return ShippingDecision(
                FramingStatus.NEEDS_CONFIRMATION, rule.rule_key, None, None, 0.0,
                f"rule '{category}' has no template EAN")

        plan = CATEGORY_PLANS.get(category)
        if plan is None:
            return ShippingDecision(
                FramingStatus.NEEDS_CONFIRMATION, rule.rule_key, None, None, 0.0,
                f"no carrier plan defined for category '{category}'")

        candidates: list[str] = []
        if shipment_type:
            candidates.append(shipment_type)
        candidates.append(plan.shipment_type)
        candidates.extend(plan.fallbacks)

        country = country.upper()
        for st in candidates:
            tariff = self.find_tariff(plan.carrier, country, st, plan.size_class)
            if tariff is not None:
                cost = float(tariff.cost_eur or 0.0)
                return ShippingDecision(
                    FramingStatus.FRAMED, rule.rule_key, plan.carrier.value,
                    tariff.tariff_key, cost,
                    f"rule '{category}' -> {plan.carrier.value}/{st} @ EUR {cost:.2f}")

        return ShippingDecision(
            FramingStatus.NEEDS_CONFIRMATION, rule.rule_key, plan.carrier.value, None, 0.0,
            f"no {plan.carrier.value}/{country} tariff on file for '{category}'")


def frame_order(lines: list[OrderLine], resolver: ShippingResolver,
                country: str = "NL") -> list[OrderLine]:
    """Apply resolution to each line in place and return the lines."""
    for line in lines:
        decision = resolver.resolve(line, country=country)
        line.framing_status = decision.framing_status
        line.rule_key = decision.rule_key
        line.carrier = decision.carrier
        line.tariff_key = decision.tariff_key
        line.shipping_eur = decision.shipping_eur
        line.framing_reason = decision.reason
    return lines