"""School / B2B order pipeline.

Mirrors the manual's pipeline:

    catalog/sample request -> info mail + catalog
      -> follow-up
      -> offer request -> e-Boekhouden relation + offer
      -> accept -> invoice
      -> insured DHL via MyParcel (hand-in)
      -> invoice to customer + warehouse

The agent consumes the inbound school email, produces the order + offer
draft, and frames every line against the shipping rules.  Lines that cannot be
framed are the whole point of the exercise: they are escalated, not guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..db.db import Database, new_id
from ..domain.models import (FramingStatus, Order, OrderLine, OrderStatus,
                              ShippingRule, Tariff)
from ..domain.shipping import ShippingResolver, frame_order
from .base import audit, request_approval


@dataclass
class ParsedRequest:
    school_name: str
    email: str
    lines: list[tuple[str, int]]      # (sku or title fragment, qty)
    raw_text: str
    requested_delivery: str | None = None
    po_number: str | None = None


_QTY_RE = re.compile(r"(\d+)\s*x\s*", re.I)
_LINE_RE = re.compile(
    r"^\s*[-*]?\s*(?:(?:SKU|Artikel|Product)\s*[:\-]?\s*)?"
    r"(?P<sku>\d{2,4})\b[^\n]*?\b(?P<qty>\d{1,4})\s*(?:x|stuks|pcs)\.?\s*$",
    re.I | re.M)

# "SKU 234 x 10" -- the SKU first, then the quantity with the "x" before it.
_SKU_QTY_X_RE = re.compile(
    r"(?:SKU|Artikel|Product)\s*[:\-]?\s*(?P<sku>\d{2,4})\s*"
    r"(?:x|stuks|pcs)\s*(?P<qty>\d{1,4})",
    re.I)
_TITLE_QTY_RE = re.compile(
    r"^\s*[-*]\s*(?P<title>.{4,120}?)\s*[x-]\s*(?P<qty>\d{1,4})\s*$",
    re.I | re.M)

# Dutch school orders are usually written "10x MagSafe draadloze oplader",
# i.e. the quantity comes FIRST and the product title follows.  The original
# grammar only accepted the trailing "product x 10" form, which silently
# produced empty orders for the way schools actually write.
_QTY_FIRST_RE = re.compile(
    r"(?<![0-9A-Za-z])(?P<qty>\d{1,4})\s*(?:x|stuks|pcs)\s+"
    r"(?P<title>[A-Za-z0-9][^\n,;]{4,120}?)\s*"
    r"(?=$|[\n,;]|\d{1,4}\s*(?:x|stuks|pcs)\s)",
    re.I)

# The title captured by _QTY_FIRST_RE stops at the next "N x" phrase, so a
# sentence containing two products yields two lines rather than one long one.
_QTY_BREAK_RE = re.compile(
    r"\s+(?=\d{1,4}\s*(?:x|stuks|pcs)\s)", re.I)

# A title that is only a stop-word is not a product line.
_TITLE_STOPWORDS = {
    "de", "het", "een", "en", "van", "voor", "met", "op", "aan", "zijn",
    "ons", "onze", "wij", "we", "graag", "willen", "bestellen", "bestel",
    "deze", "dit", "product", "producten", "artikel", "artikelen", "stuks",
    "aantal", "st", "st.", "stuks", "x",
}


def _looks_like_a_title(text: str) -> bool:
    """Reject fragments that are not product descriptions."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).strip()
    if not cleaned:
        return False
    words = [w for w in cleaned.split() if w]
    if not words:
        return False
    meaningful = [w for w in words if w not in _TITLE_STOPWORDS]
    if not meaningful:
        return False
    # A real product description has at least two meaningful words.
    return len(meaningful) >= 2 or len(cleaned) >= 12


# Trailing clauses that are not part of the product description.
_TITLE_TAIL_RE = re.compile(
    r"\s+\b(?:bestellen|bestel|besteld|leveren|lever|sturen|reserveren)\b.*$",
    re.I)

# Trailing conjunctions left over when the title runs into the next product.
_TITLE_TAIL_CONJ_RE = re.compile(r"\s+(?:en|of|plus|ofwel)\s*$", re.I)

# Leading articles that carry no product information.
_TITLE_LEAD_RE = re.compile(
    r"^(?:de|het|een|ons|onze)\s+", re.I)


# Words too common to carry product identity.
_TOKEN_STOPWORDS = {
    "de", "het", "een", "en", "van", "voor", "met", "op", "aan", "zijn",
    "ons", "onze", "wij", "we", "geschikt", "zwart", "wit",
    "kleur", "meter", "cm", "mm", "type", "versie", "model",
    "nieuw", "nieuwe", "set", "stuks", "aantal", "product", "artikel",
    "universal", "universeel",
}


def _title_tokens(text: str) -> set[str]:
    """Significant lowercase words used for catalogue matching."""
    cleaned = re.sub(r"[^0-9A-Za-zÀ-ÿ\s-]", " ", (text or "").lower())
    tokens = set()
    for word in cleaned.split():
        word = word.strip("-")
        if len(word) < 3:
            continue
        if word in _TOKEN_STOPWORDS:
            continue
        tokens.add(word)
    return tokens


def _clean_title(text: str) -> str:
    """Trim a captured title down to the product description."""
    out = (text or "").strip(" .,-")
    out = _TITLE_TAIL_RE.sub("", out)
    out = out.strip(" .,-")
    out = _TITLE_TAIL_CONJ_RE.sub("", out)
    out = out.strip(" .,-")
    out = _TITLE_LEAD_RE.sub("", out)
    return out.strip(" .,-")


def parse_school_email(text: str, fallback_email: str = "") -> ParsedRequest:
    """Extract the requested lines from a school order email."""
    lines: list[tuple[str, int]] = []
    for m in _LINE_RE.finditer(text):
        lines.append((m.group("sku"), int(m.group("qty"))))
    if not lines:
        for m in _SKU_QTY_X_RE.finditer(text):
            lines.append((m.group("sku"), int(m.group("qty"))))
    if not lines:
        for m in _TITLE_QTY_RE.finditer(text):
            title = _clean_title(m.group("title"))
            if title:
                lines.append((title, int(m.group("qty"))))
    if not lines:
        for m in _QTY_FIRST_RE.finditer(text):
            title = m.group("title").strip(" .,-")
            # Only the part before the next "N x" belongs to this line.
            title = _QTY_BREAK_RE.split(title)[0]
            title = _clean_title(title)
            if _looks_like_a_title(title):
                lines.append((title, int(m.group("qty"))))

    po = None
    m = re.search(r"(?:inkooporder|bestelnummer|referentie|PO)\s*(?:nr\.?|nummer)?\s*[:#]?\s*([\w-]{3,20})",
                  text, re.I)
    if m:
        po = m.group(1)

    name = ""
    m = re.search(r"(?:school|basisschool)\s+([A-Z][\w'\- ]{2,40})", text)
    if m:
        name = m.group(1).strip()
    email = ""
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    if m:
        email = m.group(0)
    return ParsedRequest(name or "School (naam onbekend)", email or fallback_email,
                          lines, text, po_number=po)


class SchoolOrderAgent:
    """Turns an inbound school email into a framed order + offer draft."""

    name = "school_order"

    def __init__(self, db: Database, resolver: ShippingResolver,
                 discount_pct: float | None = None):
        # Same rule as the orchestrator: an unset discount is 0, never a
        # fabricated percentage.  See tests/test_no_default_discount.py.
        if discount_pct is None:
            from ..config import get_settings
            discount_pct = get_settings().school_discount_pct
        self.db = db
        self.resolver = resolver
        self.discount_pct = discount_pct

    # -- helpers -------------------------------------------------------
    def _resolve_line(self, sku_or_title: str, qty: int) -> OrderLine | None:
        row = self.db.query_one(
            "SELECT sku_text, title, product_type, ean, price_eur, weight_gram "
            "FROM products WHERE sku_text = ?", (sku_or_title,))
        if row is None:
            row = self.db.query_one(
                "SELECT sku_text, title, product_type, ean, price_eur, weight_gram "
                "FROM products WHERE title LIKE ? ORDER BY product_type DESC LIMIT 1",
                (f"%{sku_or_title}%",))
        if row is None:
            row = self._resolve_by_tokens(sku_or_title)
        if row is None:
            return None
        bundle_row = self.db.query_one(
            "SELECT component_skus FROM bundles WHERE bundle_sku = ?",
            (row["sku_text"],))
        components = ()
        if bundle_row:
            import json
            components = tuple(json.loads(bundle_row["component_skus"] or "[]"))
        return OrderLine(
            sku=row["sku_text"], title=row["title"], quantity=qty,
            unit_price_eur=float(row["price_eur"] or 0),
            weight_gram=int(row["weight_gram"] or 0),
            product_type=row["product_type"], ean=row["ean"],
            bundle_components=components)

    def _resolve_by_tokens(self, text: str) -> dict | None:
        """Match a free-text product description against the catalogue.

        Schools write "de MagSafe draadloze oplader" while the catalogue
        title is "Draadloze Oplader - Geschikt Voor MagSafe - 1 Meter - Wit".
        A LIKE substring therefore never matches, so we fall back to scoring
        every product on shared significant words.
        """
        wanted = _title_tokens(text)
        if not wanted:
            return None
        rows = self.db.query(
            "SELECT sku_text, title, product_type, ean, price_eur, weight_gram "
            "FROM products")
        best = None
        best_score = 0
        for candidate in rows:
            have = set(_title_tokens(candidate["title"]))
            if not have:
                continue
            shared = wanted & have
            if not shared:
                continue
            # Prefer the candidate that covers the most of the request and is
            # not a superset of many extra words.
            score = len(shared) / (len(wanted) + 0.15 * (len(have) - len(shared)))
            if score > best_score:
                best_score = score
                best = candidate
        if best is None or best_score < 0.34:
            return None
        return best

    def _upsert_school(self, request: ParsedRequest) -> str:
        row = self.db.query_one("SELECT school_id FROM schools WHERE email = ?",
                                (request.email,))
        if row:
            return row["school_id"]
        school_id = new_id()
        self.db.execute(
            """INSERT INTO schools (school_id, name, email, contact_person, city,
                                   country, segment)
               VALUES (?,?,?,?,?,?,?)""",
            (school_id, request.school_name, request.email, None, None, "NL", "school"))
        return school_id

    # -- main ----------------------------------------------------------
    def handle_email(self, text: str, source_email: str = "",
                     country: str = "NL") -> Order:
        request = parse_school_email(text, source_email)
        customer_id = self._upsert_school(request)

        lines: list[OrderLine] = []
        for fragment, qty in request.lines:
            line = self._resolve_line(fragment, qty)
            if line is None:
                audit(self.db, self.name, "line_unresolved", "order_line", None,
                      {"fragment": fragment, "qty": qty}, requires_human=True)
                continue
            lines.append(line)

        frame_order(lines, self.resolver, country=country)

        order = Order(
            order_number=f"B2B-{datetime.utcnow():%Y%m%d}-{new_id()[:6].upper()}",
            customer_id=customer_id, lines=lines, discount_pct=self.discount_pct,
            source_email=request.email)

        order_id = new_id()
        self.db.execute(
            """INSERT INTO orders (order_id, order_number, customer_id, channel, status,
                                   total_eur, shipping_eur, discount_pct, source_email)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (order_id, order.order_number, customer_id, order.channel,
             OrderStatus.RECEIVED.value, order.total_eur, order.shipping_eur,
             order.discount_pct, request.email))

        for line in order.lines:
            self.db.execute(
                """INSERT INTO order_lines (line_id, order_id, sku, title, quantity,
                        unit_price_eur, line_total_eur, rule_key, carrier, tariff_key,
                        shipping_eur, framing_status, is_bundle)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id(), order_id, line.sku, line.title, line.quantity,
                 line.unit_price_eur, line.line_total_eur, line.rule_key,
                 line.carrier, line.tariff_key, line.shipping_eur,
                 line.framing_status.value, 1 if line.bundle_components else 0))

        unframed = [l for l in order.lines if l.framing_status is not FramingStatus.FRAMED]
        if unframed:
            request_approval(self.db, self.name, "shipping_rule_unresolved", {
                "order_number": order.order_number,
                "lines": [{"sku": l.sku, "title": l.title,
                           "status": l.framing_status.value, "reason": l.framing_reason}
                          for l in unframed],
            }, risk="high")

        # A line priced at zero must never leave the building silently: the
        # catalogue in this repository carries no sell prices (they live in
        # FiveX / Mastersheet.xlsx), so an offer built from it would quote a
        # school EUR 0 for goods. Such an order needs a human to fill in the
        # price before an offer may be sent.
        unpriced = [l for l in order.lines if float(l.unit_price_eur or 0) <= 0]
        if unpriced:
            request_approval(self.db, self.name, "price_missing", {
                "order_number": order.order_number,
                "reason": "catalogue has no sell price for these SKUs",
                "lines": [{"sku": l.sku, "title": l.title, "quantity": l.quantity}
                          for l in unpriced],
            }, risk="high")

        status = OrderStatus.RECEIVED if not unframed else OrderStatus.NEEDS_REVIEW
        if unpriced:
            status = OrderStatus.NEEDS_REVIEW
        self.db.execute("UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP "
                        "WHERE order_id=?", (status.value, order_id))

        audit(self.db, self.name, "order_created", "order", order_id, {
            "order_number": order.order_number,
            "lines": len(order.lines),
            "unframed": len(unframed),
            "total_eur": order.total_eur,
        })
        return order

    # -- offer draft ---------------------------------------------------
    def build_offer(self, order_number: str) -> dict:
        order = self.db.query_one("SELECT * FROM orders WHERE order_number=?",
                                  (order_number,))
        if not order:
            raise KeyError(order_number)
        lines = self.db.query(
            "SELECT * FROM order_lines WHERE order_id=?", (order["order_id"],))
        school = self.db.query_one("SELECT * FROM schools WHERE school_id=?",
                                   (order["customer_id"],))

        # An offer may only be queued for sending once every line carries a
        # real price. This catalogue has no sell prices (they live in FiveX /
        # Mastersheet.xlsx), so without this guard an offer would quote a
        # school EUR 0 for the goods and only ask for shipping money.
        unpriced = [l for l in lines if float(l["unit_price_eur"] or 0) <= 0]
        blocked = bool(unpriced)

        offer = {
            "offer_number": f"OFF-{order['order_number']}",
            "customer": school,
            "lines": [{
                "sku": l["sku"], "title": l["title"], "quantity": l["quantity"],
                "unit_price_eur": float(l["unit_price_eur"]),
                "line_total_eur": float(l["line_total_eur"]),
                "framing_status": l["framing_status"],
            } for l in lines],
            "subtotal_eur": float(order["total_eur"]),
            "shipping_eur": float(order["shipping_eur"]),
            "discount_pct": float(order["discount_pct"]),
            "total_eur": float(order["total_eur"]),
            "warranty_years": 2,
            "status": "draft" if not blocked else "blocked_missing_price",
            "requires_human_send": True,
        }
        if blocked:
            offer["blocked_reason"] = (
                "catalogue has no sell price for these SKUs; a human must "
                "fill in the prices before this offer can be sent")
            offer["unpriced_lines"] = [
                {"sku": l["sku"], "title": l["title"], "quantity": l["quantity"]}
                for l in unpriced]
            # The order step already raised a price_missing approval for this
            # order; only raise one here when none is still open, so the
            # human queue never fills up with duplicates of the same issue.
            existing = self.db.query(
                "SELECT approval_id FROM approvals "
                "WHERE action_type='price_missing' AND status='pending' "
                "AND payload LIKE ?", (f'%{order_number}%',))
            if not existing:
                request_approval(self.db, self.name, "price_missing", {
                    "order_number": order_number,
                    "offer_number": offer["offer_number"],
                    "reason": offer["blocked_reason"],
                    "lines": offer["unpriced_lines"],
                }, risk="high")
            audit(self.db, self.name, "offer_blocked_missing_price", "order",
                  order["order_id"],
                  {"offer_number": offer["offer_number"],
                   "unpriced": len(unpriced)})
            return offer

        request_approval(self.db, self.name, "offer_send", offer, risk="medium")
        audit(self.db, self.name, "offer_drafted", "order", order["order_id"],
              {"offer_number": offer["offer_number"]})
        return offer
