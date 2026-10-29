"""Purchase intelligence: 6-month rolling averages + LVB replenishment.

Replaces the hand-maintained Excel "Mastersheet" purchase trail.  For each SKU
we compute the average monthly quantity and unit cost over the trailing six
months, compare against stock, and produce a *replenishment suggestion*.

Per the manual (section 8), FiveX-style automatic price changes are
"detect + recommend only" -- so this agent never writes a price.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..db.db import Database, new_id
from .base import audit


class PurchaseIntelligenceAgent:
    name = "purchase_intelligence"

    def __init__(self, db: Database, reorder_point: int = 10,
                 safety_days: int = 7, lead_time_days: int = 30):
        self.db = db
        self.reorder_point = reorder_point
        self.safety_days = safety_days
        self.lead_time_days = lead_time_days

    def compute(self) -> dict:
        cutoff = datetime.utcnow() - timedelta(days=183)   # ~6 months
        rows = self.db.query(
            """SELECT sku, SUM(quantity) AS qty, AVG(unit_price_eur) AS avg_cost,
                      MAX(created_at) AS last_at
               FROM order_lines
               WHERE created_at >= ? AND is_bundle = 0
               GROUP BY sku""", (cutoff.isoformat(),))
        computed = 0
        for r in rows:
            monthly = (int(r["qty"] or 0)) / 6.0
            stock_row = self.db.query_one(
                "SELECT on_hand FROM stock WHERE sku=?", (r["sku"],))
            on_hand = int(stock_row["on_hand"]) if stock_row else 0
            lead_months = self.lead_time_days / 30.0
            suggested = int(round(monthly * lead_months)) - on_hand
            suggested = max(suggested, 0)
            product = self.db.query_one(
                "SELECT ean FROM products WHERE sku_text=?", (r["sku"],))
            ean = product["ean"] if product else None
            bracket = self._price_bracket(float(r["avg_cost"] or 0))
            self.db.execute(
                """INSERT INTO purchase_intel (sku, ean, avg_qty_6m, avg_unit_cost_eur,
                        last_purchase_at, stock_qty, reorder_point, suggested_qty,
                        price_bracket, computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(sku) DO UPDATE SET
                     avg_qty_6m=excluded.avg_qty_6m,
                     avg_unit_cost_eur=excluded.avg_unit_cost_eur,
                     last_purchase_at=excluded.last_purchase_at,
                     stock_qty=excluded.stock_qty,
                     suggested_qty=excluded.suggested_qty,
                     price_bracket=excluded.price_bracket,
                     computed_at=excluded.computed_at""",
                (r["sku"], ean, round(monthly, 2), float(r["avg_cost"] or 0),
                 r["last_at"], on_hand, self.reorder_point, suggested, bracket))
            computed += 1
        audit(self.db, self.name, "purchase_intel_computed", None, None,
              {"skus": computed})
        return {"skus": computed, "window_days": 183}

    @staticmethod
    def _price_bracket(cost: float) -> str:
        if cost < 5:
            return "<EUR 5"
        if cost < 15:
            return "EUR 5-15"
        if cost < 30:
            return "EUR 15-30"
        return ">EUR 30"

    def replenishment_suggestions(self, limit: int = 25) -> list[dict]:
        return self.db.query(
            """SELECT sku, ean, avg_qty_6m, stock_qty, suggested_qty, price_bracket
               FROM purchase_intel WHERE suggested_qty > 0
               ORDER BY suggested_qty DESC LIMIT ?""", (limit,))
