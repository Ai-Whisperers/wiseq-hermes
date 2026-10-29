"""Review invitation drafting -- draft first, human sends.

The client operating manual is explicit (section 6 + 8):

  * The primary scoreboard is bol.com seller/product reviews, not Trustpilot.
  * Customer-service resolution must stay separate from influencing a review.
  * Requests to remove or change negative feedback must NOT be automated.
  * Phase 0-1: draft recommendations only, human sends.
  * Non-response is not consent; a suppression list and audit trail are
    required before any send path exists.

So this agent produces Dutch draft texts and never sends anything.  Sending
requires a human to approve; the SMTP path only ever delivers to the
configured test mailbox.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..db.db import Database, new_id
from ..domain.models import ReviewStatus
from .base import audit, request_approval

_TEMPLATE = """Beste {name},

Bedankt voor uw vertrouwen in WiseQ. Uw bestelling {order_number} is goed
aangekomen, en we hopen dat u dagelijks plezier hebt aan de producten.

Als u een moment heeft: uw beoordeling helpt ons om onze service en ons
assortiment verder te verbeteren. U kunt uw ervaring delen via de link in
onze e-mail.

Met vriendelijke groet,
Team WiseQ
https://www.wiseq.nl
"""


class ReviewAgent:
    name = "review_drafter"

    def __init__(self, db: Database, delay_days: int | None = None):
        if delay_days is None:
            from ..config import get_settings
            delay_days = get_settings().review_invitation_delay_days
        self.db = db
        self.delay_days = delay_days

    def schedule(self, order_number: str, channel: str = "bol.com") -> dict:
        order = self.db.query_one("SELECT * FROM orders WHERE order_number=?",
                                  (order_number,))
        if not order:
            raise KeyError(order_number)
        school = self.db.query_one("SELECT * FROM schools WHERE school_id=?",
                                   (order["customer_id"],))
        email = school["email"] if school else ""
        due = datetime.utcnow() + timedelta(days=self.delay_days)
        review_id = new_id()
        self.db.execute(
            """INSERT INTO reviews (review_id, order_id, channel, customer_email,
                                    order_number, status, created_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (review_id, order["order_id"], channel, email, order_number,
             ReviewStatus.DRAFTED.value))
        self.db.execute("UPDATE orders SET review_due_at=?, "
                        "updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                        (due.isoformat(), order["order_id"]))
        audit(self.db, self.name, "review_scheduled", "order", order["order_id"],
              {"channel": channel, "due": due.isoformat()})
        return {"review_id": review_id, "order_number": order_number,
                "channel": channel, "due": due.isoformat()}

    def draft_due(self, limit: int = 50) -> list[dict]:
        """Produce the Dutch draft body for every review that is due."""
        due = self.db.query(
            """SELECT * FROM reviews WHERE status=? AND suppression=0
               ORDER BY created_at LIMIT ?""",
            (ReviewStatus.DRAFTED.value, limit))
        drafted = []
        for r in due:
            order = self.db.query_one(
                "SELECT o.*, s.name AS school_name FROM orders o "
                "LEFT JOIN schools s ON s.school_id = o.customer_id "
                "WHERE o.order_number=?", (r["order_number"],))
            name = (order or {}).get("school_name") or "klant"
            body = _TEMPLATE.format(name=name, order_number=r["order_number"])
            self.db.execute("UPDATE reviews SET drafted_body=? WHERE review_id=?",
                            (body, r["review_id"]))
            drafted.append({"review_id": r["review_id"],
                            "order_number": r["order_number"],
                            "channel": r["channel"],
                            "to": r["customer_email"],
                            "body": body,
                            "requires_human_send": True})
        if drafted:
            request_approval(self.db, self.name, "review_send", drafted, risk="high")
            audit(self.db, self.name, "reviews_drafted", "reviews", None,
                  {"count": len(drafted)})
        return drafted

    def suppress(self, email: str, reason: str) -> dict:
        """Suppress an address (opt-out / negative-feedback / legal basis)."""
        self.db.execute(
            "UPDATE reviews SET suppression=1, status=? WHERE customer_email=?",
            (ReviewStatus.SUPPRESSED.value, email))
        audit(self.db, self.name, "review_suppressed", "reviews", email,
              {"reason": reason})
        return {"email": email, "status": "suppressed", "reason": reason}
