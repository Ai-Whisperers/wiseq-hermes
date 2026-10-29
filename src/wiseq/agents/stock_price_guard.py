"""Stock-based price guard.

From ``data/client/Handleiding_opzet.txt``:

    "Tot slot maken wij gebruik van prijsverhogingen om artikelen met een
     lage voorraad te remmen. FiveX verhoogt automatisch de prijs wanneer
     de voorraad van een artikel 10 stuks of lager is. Ik geloof dat die
     prijsstijging 10% is."

So the business rule is: **when available stock drops to 10 units or
fewer, the sell price is raised to slow demand.** The stated percentage
(10%) is explicitly hedged in the source ("ik geloof"), so it is treated
as a PLACEHOLDER default that Rob confirms -- exactly like the school
discount, and for the same reason.

Two important constraints, both from the manual:

  * the raise must be in place BEFORE the new delivery arrives, and
    reverted to the old price afterwards;
  * the raise has to be applied to BOTH selling accounts, or stock gets
    bought through the cheap account.

This agent DETECTS and RECOMMENDS.  It never changes a live price:
``auto_price_change_enabled`` is a detect-and-recommend switch, and the
price write itself is a high-impact action that waits for a human.
"""
from __future__ import annotations

from typing import Any

from ..db.db import Database
from .base import audit, request_approval


class StockPriceGuardAgent:
    """Recommends a price raise for low-stock articles."""

    name = "stock_price_guard"

    #: "de voorraad van een artikel 10 stuks of lager" -- 10 units or fewer.
    LOW_STOCK_THRESHOLD = 10

    #: The source hedges this ("ik geloof dat die prijsstijging 10% is"),
    #: so it stays a placeholder until Rob confirms it.
    DEFAULT_RAISE_PCT = 10.0

    #: Days of cover below which the stock gap is imminent.  The manual
    #: says a 10-unit threshold is already late for items selling 10 a
    #: day, so cover is the more honest signal than the raw threshold.
    URGENT_COVER_DAYS = 3.0

    def __init__(self, db: Database, threshold: int | None = None,
                 raise_pct: float | None = None):
        from ..config import get_settings
        settings = get_settings()
        self.db = db
        self.threshold = threshold if threshold is not None \
            else self.LOW_STOCK_THRESHOLD
        configured = raise_pct if raise_pct is not None \
            else settings.stock_price_raise_pct
        self.raise_pct = configured
        self.is_placeholder = configured in (0.0, 10.0)

    def daily_velocity(self, days: int = 30) -> dict[str, float]:
        """Average units sold per day per SKU over the recent window.

        The manual makes the point that a fixed threshold of 10 is often
        ALREADY TOO LATE: "wij verkopen van sommige artikelen 10 stuks
        per dag en zien wij het voorraadgat al eerder aankomen" -- some
        items sell 10 units a day, so the stock gap arrives sooner than
        the threshold assumes.

        So the guard also reports how many days of cover the stock
        represents.  A SKU with 12 units left but a daily velocity of 10
        has roughly one day of cover and needs attention far sooner than
        a SKU with 12 units left selling one a week.
        """
        rows = self.db.query(
            """SELECT ol.sku, SUM(ol.quantity) AS sold, ? AS window_days
               FROM order_lines ol
               WHERE ol.created_at >= DATE('now', '-' || ? || ' day')
               GROUP BY ol.sku""",
            (days, days))
        return {r["sku"]: (float(r["sold"] or 0) / float(days))
                for r in rows if r.get("sku")}

    def low_stock_skus(self, velocity: dict[str, float] | None = None) -> list[dict]:
        """SKUs whose AVAILABLE stock is at or below the threshold.

        Available = on_hand minus reserved.  Reserved units are already
        spoken for, so a SKU with 10 on hand and 8 reserved is not low
        on stock.

        The manual's threshold is inclusive ("10 stuks of lager" -- 10
        units or fewer), so 10 available IS low stock.
        """
        rows = self.db.query(
            """SELECT s.sku, s.on_hand, s.reserved,
                      (s.on_hand - s.reserved) AS available,
                      p.price_eur, p.title, p.ean
               FROM stock s
               LEFT JOIN products p ON p.sku_text = s.sku
               WHERE (s.on_hand - s.reserved) <= ?
               ORDER BY available ASC, s.sku""",
            (self.threshold,))
        if velocity is None:
            velocity = self.daily_velocity()
        for r in rows:
            per_day = velocity.get(r["sku"], 0.0)
            r["daily_velocity"] = round(per_day, 2)
            # Reserved can exceed on_hand in dirty data.  Clamp at zero:
            # "available" below zero is not a stock level, it is a bug in
            # the source data, and it must not make a SKU look emptier
            # than it is.
            available = max(int(r["available"] or 0), 0)
            r["available"] = available
            r["days_of_cover"] = (round(available / per_day, 1)
                                  if per_day > 0 else None)
        return rows

    def recommend(self, limit: int = 100) -> dict[str, Any]:
        """Produce the recommendation list and request approval."""
        rows = self.low_stock_skus()
        recommendations: list[dict[str, Any]] = []
        for r in rows:
            available = int(r["available"] or 0)
            price = float(r["price_eur"] or 0)
            if price <= 0:
                # no sell price -> raising is impossible; flag separately
                recommendations.append({
                    "sku": r["sku"], "title": r["title"], "available": available,
                    "current_price_eur": price, "recommended_price_eur": None,
                    "status": "price_missing",
                    "note": "No sell price on file -- cannot compute a raise.",
                })
                continue
            recommended = round(price * (1 + self.raise_pct / 100.0), 2)
            cover = r.get("days_of_cover")
            velocity = r.get("daily_velocity") or 0.0
            if cover is not None and cover <= self.URGENT_COVER_DAYS:
                urgency = "stockout_imminent"
                note = (f"Only ~{cover} day(s) of cover left at "
                        f"{velocity}/day. The manual warns the 10-unit "
                        f"threshold arrives too late for fast sellers -- "
                        f"act now.")
            elif velocity > 0:
                urgency = "low_stock_normal_pace"
                note = ("Raise BEFORE the new delivery arrives; revert to the "
                        "old price afterwards.")
            else:
                urgency = "low_stock_no_sales_history"
                note = ("Raise BEFORE the new delivery arrives; revert to the "
                        "old price afterwards. No sales history, so cover is "
                        "unknown.")
            recommendations.append({
                "sku": r["sku"], "title": r["title"], "available": available,
                "current_price_eur": round(price, 2),
                "recommended_price_eur": recommended,
                "raise_eur": round(recommended - price, 2),
                "raise_pct": self.raise_pct,
                "status": "recommend_raise",
                "urgency": urgency,
                "daily_velocity": velocity,
                "days_of_cover": cover,
                "note": note,
                "must_apply_to_both_selling_accounts": True,
            })

        actionable = [x for x in recommendations
                      if x["status"] == "recommend_raise"]
        if actionable:
            request_approval(
                self.db, self.name, "stock_price_raise",
                {
                    "recommendations": actionable[:limit],
                    "threshold": self.threshold,
                    "raise_pct": self.raise_pct,
                    "raise_pct_is_placeholder": self.is_placeholder,
                    "note": ("Detect-and-recommend only. Applying a live price "
                             "change needs a human, and the raise must be set on "
                             "both selling accounts."),
                },
                risk="high")

        audit(self.db, self.name, "stock_price_scanned", "stock", None,
              {"low_stock": len(rows), "actionable": len(actionable),
               "threshold": self.threshold, "raise_pct": self.raise_pct})
        return {
            "threshold": self.threshold,
            "raise_pct": self.raise_pct,
            "raise_pct_is_placeholder": self.is_placeholder,
            "low_stock": len(rows),
            "actionable": len(actionable),
            "recommendations": recommendations[:limit],
        }
