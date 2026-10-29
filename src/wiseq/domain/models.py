"""Domain value objects for WiseQ operations.

Deliberately plain dataclasses: they carry validated business data between the
ingest layer, the agents and the API, and they never touch the database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any


class OrderStatus(str, Enum):
    RECEIVED = "received"
    OFFER_DRAFTED = "offer_drafted"
    INVOICED = "invoiced"
    LABEL_READY = "label_ready"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    NEEDS_REVIEW = "needs_review"


class FramingStatus(str, Enum):
    FRAMED = "framed"              # a shipping rule was resolved cleanly
    UNFRANKED = "unfranked"        # no rule matched -> would ship unfranked
    NEEDS_CONFIRMATION = "needs_confirmation"  # rule exists but is unvalidated


class ValidationStatus(str, Enum):
    OK = "OK"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    CASE_BY_CASE = "CASE_BY_CASE"
    HERZIEN = "HERZIEN"


class ReviewStatus(str, Enum):
    DRAFTED = "drafted"
    APPROVED = "approved"
    SENT = "sent"
    SUPPRESSED = "suppressed"
    SKIPPED = "skipped"


class Carrier(str, Enum):
    LVB = "LVB"
    VVB = "VVB"
    QLS = "QLS"
    POSTNL = "PostNL"
    DHL = "DHL"


_EAN_RE = re.compile(r"^\d{8,14}$")


@dataclass(frozen=True)
class Product:
    sku: str
    title: str
    product_type: str          # component | bundle
    ean: str | None = None
    price_eur: float = 0.0
    weight_gram: int = 0
    category: str | None = None

    @property
    def has_ean(self) -> bool:
        return bool(self.ean and _EAN_RE.match(self.ean))


@dataclass(frozen=True)
class Bundle:
    bundle_key: str
    bundle_sku: str
    title: str
    component_skus: tuple[str, ...]
    needs_format_fix: bool = False

    @property
    def component_count(self) -> int:
        return len(self.component_skus)


@dataclass(frozen=True)
class ShippingRule:
    rule_key: str
    category: str
    clone_note: str | None
    template_ean: str | None
    notes: str | None
    validation_status: ValidationStatus

    @property
    def is_trustworthy(self) -> bool:
        return self.validation_status is ValidationStatus.OK


@dataclass(frozen=True)
class Tariff:
    tariff_key: str
    carrier: Carrier
    shipment_type: str
    article_kind: str | None
    country: str
    weight_band: str | None
    cost_eur: float | None
    discount_eur: float | None
    lvb_storage_eur: float | None = None
    notes: str | None = None
    size_class: str | None = None


@dataclass(frozen=True)
class School:
    school_id: str
    name: str
    email: str
    contact_person: str | None = None
    city: str | None = None
    country: str = "NL"
    is_stichting: bool = False
    segment: str = "school"


@dataclass
class OrderLine:
    sku: str
    title: str
    quantity: int = 1
    unit_price_eur: float = 0.0
    weight_gram: int = 0
    product_type: str = "component"
    ean: str | None = None
    bundle_components: tuple[str, ...] = ()
    rule_key: str | None = None
    carrier: str | None = None
    tariff_key: str | None = None
    shipping_eur: float = 0.0
    framing_status: FramingStatus = FramingStatus.UNFRANKED
    framing_reason: str | None = None

    @property
    def line_total_eur(self) -> float:
        return round(self.quantity * self.unit_price_eur, 2)


@dataclass
class Order:
    order_number: str
    customer_id: str
    lines: list[OrderLine] = field(default_factory=list)
    channel: str = "b2b_school"
    status: OrderStatus = OrderStatus.RECEIVED
    discount_pct: float = 0.0
    source_email: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def subtotal_eur(self) -> float:
        return round(sum(l.line_total_eur for l in self.lines), 2)

    @property
    def discount_eur(self) -> float:
        return round(self.subtotal_eur * self.discount_pct / 100.0, 2)

    @property
    def shipping_eur(self) -> float:
        return round(sum(l.shipping_eur for l in self.lines), 2)

    @property
    def total_eur(self) -> float:
        return round(self.subtotal_eur - self.discount_eur + self.shipping_eur, 2)

    @property
    def is_framed(self) -> bool:
        return bool(self.lines) and all(
            l.framing_status is FramingStatus.FRAMED for l in self.lines)

    @property
    def has_unfranked_lines(self) -> bool:
        return any(l.framing_status is not FramingStatus.FRAMED for l in self.lines)


@dataclass
class PurchaseStat:
    sku: str
    ean: str | None
    avg_qty_6m: float
    avg_unit_cost_eur: float
    stock_qty: int
    reorder_point: int
    suggested_qty: int
    price_bracket: str | None = None


@dataclass
class DraftedReview:
    order_number: str
    channel: str
    customer_email: str
    body_nl: str
    order_total_eur: float


@dataclass
class ApprovalRequest:
    agent_name: str
    action_type: str
    payload: dict[str, Any]
    risk: str = "medium"


@dataclass
class AgentResult:
    agent_name: str
    processed: int = 0
    escalated: int = 0
    summary: dict[str, Any] = field(default_factory=dict)