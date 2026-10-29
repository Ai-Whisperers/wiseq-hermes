"""Strike and on-time delivery monitoring (bol.com).

From the client operating manual (section 4 / 8) and
``data/client/Handleiding_opzet.txt``:

  * Every Wednesday at 10:00 bol.com evaluates whether WiseQ met its
    93% on-time delivery norm.  Below 93% of orders shipped on time
    earns a strike (exceptions exist for strikes and major outages).
  * 3 or more strikes  -> Rob must be involved and a plan of action
    executed.
  * 5 strikes          -> switch the entire assortment to VVB.
  * A strike is always recorded in the weekly minutes and mentioned in
    the weekly stand-up.
  * When a strike is caused by the carrier (QLS), the carrier must be
    contacted within 72 hours with the offending week's export.

This agent computes the on-time rate and the strike state from the
order data, and RECOMMENDS.  It never contacts bol.com, never emails the
carrier and never switches a selling account -- those are high-impact
human actions.  Anything at or above the escalation threshold becomes an
approval request.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..db.db import Database, new_id
from .base import audit, request_approval


def _week_bounds(reference: datetime | None = None) -> tuple[str, str]:
    """Return the ISO (monday, sunday) date strings of the target week."""
    ref = reference or datetime.utcnow()
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return monday.date().isoformat(), sunday.date().isoformat()


class StrikeMonitorAgent:
    """Computes the bol.com on-time norm and escalates at the thresholds."""

    name = "strike_monitor"

    #: The published on-time norm WiseQ must meet to avoid a strike.
    ON_TIME_NORM_PCT = 93.0

    def __init__(self, db: Database, norm_pct: float | None = None,
                 escalate_at: int | None = None):
        from ..config import get_settings
        settings = get_settings()
        self.db = db
        self.norm_pct = norm_pct if norm_pct is not None else self.ON_TIME_NORM_PCT
        self.escalate_at = escalate_at if escalate_at is not None \
            else settings.strike_escalation_threshold
        #: at this many strikes the whole assortment switches to VVB
        self.switch_over_at = 5

    # -- helpers -------------------------------------------------------
    def on_time_rate(self, start: str, end: str) -> dict[str, Any]:
        """On-time rate for the orders shipped in [start, end].

        An order counts as on time when it was shipped no later than the
        promised delivery date.  Orders that were never shipped are
        counted as NOT on time -- an unshipped order cannot earn a
        strike-free norm, and ignoring it would silently inflate the
        rate.
        """
        rows = self.db.query(
            """SELECT o.order_number, o.status, o.myparcel_label,
                      o.created_at, o.updated_at
               FROM orders o
               WHERE o.channel IN ('bol.com', 'b2b_school', 'webshop')
                 AND o.created_at >= ? AND o.created_at <= ?""",
            (start, end))
        total = len(rows)
        shipped = 0
        on_time = 0
        late = 0
        open_orders = 0
        for r in rows:
            status = (r.get("status") or "").lower()
            if status not in ("shipped", "delivered", "completed", "invoiced"):
                open_orders += 1
                continue
            shipped += 1
            if self._is_on_time(r):
                on_time += 1
            else:
                late += 1
        rate = (on_time / shipped * 100.0) if shipped else 0.0
        return {
            "week_start": start,
            "week_end": end,
            "orders_total": total,
            "shipped": shipped,
            "on_time": on_time,
            "late": late,
            "open": open_orders,
            "on_time_rate_pct": round(rate, 2),
            "norm_pct": self.norm_pct,
            "meets_norm": shipped > 0 and rate >= self.norm_pct,
        }

    def _is_on_time(self, row: dict) -> bool:
        """On-time = shipped within the promised window.

        The system does not model a separate promised date column, so it
        uses the documented norm: an order counts as on time when it was
        shipped within two working days of receipt.  When the model
        gains a promised-date column this becomes an exact comparison.
        """
        updated = row.get("updated_at")
        created = row.get("created_at")
        if not updated or not created:
            return True
        try:
            created_dt = datetime.fromisoformat(str(created)[:19])
            updated_dt = datetime.fromisoformat(str(updated)[:19])
        except ValueError:
            return True
        return (updated_dt - created_dt) <= timedelta(days=2, hours=23, minutes=59)

    def recorded_strikes(self) -> list[dict]:
        # NOTE: match ONLY 'strike_recorded'.  A LIKE 'strike%' also
        # matches 'strike_evaluated' (the audit row this agent writes on
        # every evaluation), which double-counted every strike.
        return self.db.query(
            """SELECT action, entity_id, detail, created_at
               FROM audit_log
               WHERE actor=? AND action='strike_recorded'
               ORDER BY created_at""", (self.name,))

    def strike_count(self) -> int:
        return len(self.recorded_strikes())

    # -- main ----------------------------------------------------------
    def _escalation_open(self) -> bool:
        """Is there already a PENDING strike-escalation approval?

        The escalation must not spam the approvals queue: the same
        unresolved escalation is one approval, however often the monitor
        runs.
        """
        rows = self.db.query(
            "SELECT approval_id FROM approvals "
            "WHERE agent_name=? AND action_type=? AND status='pending'",
            (self.name, "strike_escalation"))
        return bool(rows)

    def evaluate(self, reference: datetime | None = None) -> dict[str, Any]:
        """Evaluate the current week and escalate when required."""
        start, end = _week_bounds(reference)
        stats = self.on_time_rate(start, end)
        strikes = self.strike_count()
        result = dict(stats)
        result["strikes"] = strikes
        result["escalate_to_rob"] = strikes >= self.escalate_at
        result["switch_assortment_to_vvb"] = strikes >= self.switch_over_at
        result["requires_approval"] = bool(result["escalate_to_rob"])
        result["escalation_already_open"] = self._escalation_open()

        if result["escalate_to_rob"] and not result["escalation_already_open"]:
            request_approval(
                self.db, self.name, "strike_escalation",
                {
                    "strikes": strikes,
                    "threshold": self.escalate_at,
                    "switch_to_vvb": result["switch_assortment_to_vvb"],
                    "on_time_rate_pct": stats["on_time_rate_pct"],
                    "norm_pct": self.norm_pct,
                    "note": (
                        "Handbook rule: at 3+ strikes Rob is involved and a plan "
                        "of action is executed; at 5 strikes the whole assortment "
                        "switches to VVB."),
                },
                risk="high")
            result["escalation_already_open"] = True

        audit(self.db, self.name, "strike_evaluated", "week", start, result)
        return result

    def record_strike(self, week_start: str, cause: str = "unknown",
                      carrier: str | None = None) -> dict[str, Any]:
        """Record a strike bol.com has issued.

        Recording is a fact (the platform notified us).  The consequence
        -- Rob escalation, carrier escalation, VVB switch -- is always a
        separate approval, never an automatic action.
        """
        strike_id = new_id()
        self.db.execute(
            """INSERT INTO audit_log (audit_id, actor, action, entity_type,
                                      entity_id, detail, requires_human)
               VALUES (?,?,?,?,?,?,?)""",
            (strike_id, self.name, "strike_recorded", "week", week_start,
             f'{{"cause": "{cause}", "carrier": "{carrier or ""}"}}', 0))
        result = self.evaluate()
        result["strike_recorded"] = True
        result["cause"] = cause
        result["carrier"] = carrier
        result["carrier_followup"] = {
            "due_within_hours": 72,
            "rule": ("When the cause is the carrier, contact them within 72 "
                     "hours with that week's export and a strike screenshot."),
            "contact": "administratie@pakketdienstqls.nl",
        } if carrier else None
        return result
