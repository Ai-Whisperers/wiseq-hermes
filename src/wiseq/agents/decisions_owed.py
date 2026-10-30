"""Everything Rob still has to decide, in one place.

Why this exists
---------------
The replica works, but it works *around* a set of gaps that only Rob can
close.  Those gaps are scattered across a shipping-rule CSV, a
master-sheet index, a live storefront and a few policy documents.  A
handover note that lists them is a handover note that gets read once
and then goes stale.

This agent turns the gaps into a live, ordered, reviewable surface.  It
does not guess and it does not resolve anything -- it reports, and it
refuses to let the system act on a decision that has not been made.

The five kinds of decision it collects
--------------------------------------
``shipping_rule``
    A shipping category exists but is not validated, so orders that
    need it are blocked rather than mis-framed.

``master_sheet``
    A sheet of the master workbook was never exported, so a capability
    that depends on it cannot be built yet.

``catalogue``
    A product is sellable on the storefront but is not in the master
    catalogue, or is a sample.  Selling it is a business decision.

``policy``
    Two public sources disagree, and the disagreement is visible to
    customers.

``price``
    A product has no sell price, so no offer can be made for it.

The blocking rule
-----------------
An unresolved decision of a blocking kind raises an approval.  That is
the point: the system must not be able to quietly proceed past a
decision nobody made.  The approval is what makes the gap visible in
the approval queue rather than only in this report.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..db.db import Database

#: Decision kinds that block a consequential action until a human
#: answers them.  A price gap blocks an offer; a catalogue question
#: blocks selling that product; a shipping rule blocks framing an
#: order; a policy contradiction blocks a customer-facing statement.
BLOCKING_KINDS = frozenset({
    "shipping_rule",
    "catalogue",
    "policy",
    "price",
})

#: Kinds that only record information.  A missing master sheet does
#: not block today's orders -- it blocks a future capability.
NON_BLOCKING_KINDS = frozenset({
    "master_sheet",
})


class DecisionsAgent:
    """Aggregates the decisions a human still owes."""

    name = "decisions_owed"

    def __init__(self, db: Database, repo: str | Path | None = None,
                 repo_dir: str | Path | None = None):
        self.db = db
        # 'repo' matches the other agents' signature; 'repo_dir' is
        # accepted as an alias so callers can be explicit about which
        # directory is meant.
        chosen = repo if repo is not None else repo_dir
        self.repo_dir = Path(chosen) if chosen else None

    # -- shipping ---------------------------------------------------
    def shipping_rule_decisions(self) -> list[dict]:
        """Categories whose shipping rule cannot be applied automatically."""
        rows = self.db.query(
            """SELECT rule_key, category, validation_status, template_ean, notes
               FROM shipping_rules
               WHERE validation_status IS NOT NULL
                 AND validation_status <> 'OK'
               ORDER BY category"""
        )
        decisions = []
        for row in rows:
            status = row["validation_status"]
            decisions.append({
                "kind": "shipping_rule",
                "id": row["rule_key"],
                "subject": row["category"],
                "status": status,
                "blocking": True,
                "question": self._shipping_question(row),
                "detail": row["notes"] or "",
                "evidence": row["template_ean"] or "",
                "blocks": f"framing any order containing '{row['category']}'",
                "owner": "Rob (WiseQ)",
            })
        return decisions

    @staticmethod
    def _shipping_question(row) -> str:
        status = (row["validation_status"] or "").upper()
        if status == "CASE_BY_CASE":
            return (
                f"Does '{row['category']}' ship on its own tariff, or does each "
                "product in the category get its own shipping rule?"
            )
        if not row["template_ean"]:
            return (
                f"Which EAN does '{row['category']}' ship under? The template "
                "EAN is blank, so no tariff can be looked up."
            )
        return (
            f"Confirm the shipping rule for '{row['category']}': the category "
            "is still marked as needing confirmation."
        )

    # -- master sheets ----------------------------------------------
    def master_sheet_decisions(self) -> list[dict]:
        """Sheets of the master workbook that were never exported."""
        if not self.repo_dir:
            return []
        index = self.repo_dir / "data" / "client" / "mastersheet" / "INDEX.json"
        if not index.exists():
            return []
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []

        exported = set(data.get("exported_public") or [])
        sheets = list(data.get("sheets") or [])
        reasons = data.get("not_exported_reason") or {}

        decisions = []
        for sheet in sheets:
            # A sheet counts as missing only if none of the exported files
            # obviously carries it.  The exported set is a list of CSV
            # names, not sheet names, so match on the significant word.
            if self._sheet_is_exported(sheet, exported):
                continue
            decisions.append({
                "kind": "master_sheet",
                "id": sheet,
                "subject": sheet,
                "status": "NOT_EXPORTED",
                "blocking": False,
                "question": (
                    f"Can '{sheet}' be exported without the sensitive columns? "
                    "The replica cannot build on a sheet it has never seen."
                ),
                "detail": reasons.get(sheet, ""),
                "evidence": "",
                "blocks": f"any capability that depends on '{sheet}'",
                "owner": "Rob (WiseQ)",
            })
        return decisions

    @staticmethod
    def _sheet_is_exported(sheet: str, exported: set[str]) -> bool:
        """True when an exported CSV plausibly carries this sheet."""
        words = [w for w in sheet.lower().replace("&", " ").split() if len(w) > 3]
        for name in exported:
            stem = name.lower().replace(".csv", "")
            for word in words:
                if word in stem:
                    return True
        return False

    # -- catalogue --------------------------------------------------
    def catalogue_decisions(self) -> list[dict]:
        """Storefront products the master catalogue does not describe.

        The master describes 139 products.  The storefront sells 227
        variants -- 88 of them are not in the master catalogue, and 5
        are sample units.

        Which of the extras WiseQ intends to sell is a business
        decision -- it is not a data problem, and it must not be
        resolved by a price being non-zero.

        The decision is reported per FAMILY, not per variant.  Eighty-
        eight individual products is not a question anyone can answer;
        "do we sell the Premium USB-C cable line?" is.  The variants
        stay listed underneath so nothing is hidden.
        """
        rows = self.db.query(
            """SELECT variant_sku, sku_text, title, price_eur, product_type,
                      is_sample, tags
               FROM storefront_catalogue
               WHERE in_catalogue = 0
               ORDER BY is_sample, title"""
        )
        families: dict[tuple[str, str], dict] = {}
        for row in rows:
            is_sample = bool(row["is_sample"])
            status = "SAMPLE" if is_sample else "OUTSIDE_MASTER"
            family = _catalogue_family(row["title"])
            key = (status, family)

            entry = families.get(key)
            if entry is None:
                entry = families[key] = {
                    "kind": "catalogue",
                    "id": f"{status}:{family}",
                    "subject": family,
                    "status": status,
                    "blocking": True,
                    "question": _family_question(status, family),
                    "detail": row["tags"] or "",
                    "evidence": "",
                    "blocks": _family_blocks(status, family),
                    "owner": "Rob (WiseQ)",
                    "variants": [],
                }
            entry["variants"].append({
                "variant_sku": row["variant_sku"],
                "sku_text": row["sku_text"],
                "title": row["title"],
                "price_eur": float(row["price_eur"] or 0.0),
            })

        result = []
        for entry in families.values():
            variants = entry["variants"]
            prices = [v["price_eur"] for v in variants]
            entry["variant_count"] = len(variants)
            entry["evidence"] = (
                f"{len(variants)} variant(s), EUR {min(prices):.2f} .. EUR {max(prices):.2f}"
                if prices else ""
            )
            result.append(entry)
        return result

    # -- policy -----------------------------------------------------
    def policy_decisions(self) -> list[dict]:
        """Contradictions between public sources that customers can see."""
        from .warranty_policy import public_warranty_contradiction

        contradiction = public_warranty_contradiction()
        if not contradiction["contradicted"]:
            return []

        conflicting = contradiction["pages_conflicting_with_manual"]
        agreeing = []
        for years, pages in contradiction["pages_by_years"].items():
            if int(years) == contradiction["internal_manual_years"]:
                agreeing = pages

        return [{
            "kind": "policy",
            "id": "warranty_years",
            "subject": "Warranty period",
            "status": "CONTRADICTED",
            "blocking": True,
            "question": (
                "How long is the warranty? The general terms say one year, "
                "the school-facing pages say two, and the operating manual "
                "says two."
            ),
            "detail": (
                f"{len(conflicting)} page(s) conflict with the manual; "
                f"{len(agreeing)} agree with it."
            ),
            "evidence": ", ".join(conflicting[:3]) + (" ..." if len(conflicting) > 3 else ""),
            "blocks": "any customer-facing statement about the warranty",
            "owner": "Rob (WiseQ)",
        }]

    # -- prices ------------------------------------------------------
    def price_decisions(self) -> list[dict]:
        """Catalogue products with no sell price, which blocks any offer.

        A product loaded from the master data carries ``price_eur = 0``
        and ``synthetic_price = 1`` until a real price import replaces
        it.  Zero is not a price, and the synthetic flag is not evidence
        of one -- so both mean the same thing here: the price is missing.

        A product that has a real price on the storefront but no price
        in the database is a different situation and is reported
        separately, because the storefront already answers the question.
        """
        rows = self.db.query(
            """SELECT sku_text, title, price_eur, synthetic_price
               FROM products
               WHERE (price_eur IS NULL OR price_eur <= 0)
                 AND sku_text IS NOT NULL
               ORDER BY product_type, sku_text"""
        )
        decisions = []
        for row in rows:
            # Does the storefront already tell us the price?
            live = self.db.query_one(
                "SELECT price_eur FROM storefront_catalogue "
                "WHERE sku_text = ? AND price_eur > 0", (row["sku_text"],))
            storefront_price = float(live["price_eur"]) if live else None

            if storefront_price is not None:
                decisions.append({
                    "kind": "price",
                    "id": row["sku_text"],
                    "subject": row["title"],
                    "status": "PRICE_NOT_IMPORTED",
                    "blocking": False,
                    "question": (
                        f"The storefront sells '{row['title']}' at "
                        f"EUR {storefront_price:.2f} but that price is not "
                        "imported. Import it?"
                    ),
                    "detail": "",
                    "evidence": f"storefront EUR {storefront_price:.2f}",
                    "blocks": "",
                    "owner": "Rob (WiseQ)",
                })
            else:
                decisions.append({
                    "kind": "price",
                    "id": row["sku_text"],
                    "subject": row["title"],
                    "status": "MISSING_PRICE",
                    "blocking": True,
                    "question": (
                        f"What is the sell price for '{row['title']}' "
                        f"({row['sku_text']})? Without a price no offer can "
                        "be made for it."
                    ),
                    "detail": "",
                    "evidence": "",
                    "blocks": f"any offer that includes '{row['title']}'",
                    "owner": "Rob (WiseQ)",
                })
        return decisions

    # -- the report --------------------------------------------------
    def collect(self) -> dict:
        """Gather every open decision, blocking ones first."""
        decisions: list[dict] = []
        decisions.extend(self.shipping_rule_decisions())
        decisions.extend(self.catalogue_decisions())
        decisions.extend(self.policy_decisions())
        decisions.extend(self.price_decisions())
        decisions.extend(self.master_sheet_decisions())

        by_kind: dict[str, int] = {}
        for d in decisions:
            by_kind[d["kind"]] = by_kind.get(d["kind"], 0) + 1

        blocking = [d for d in decisions if d["blocking"]]
        return {
            "total": len(decisions),
            "blocking": len(blocking),
            "by_kind": by_kind,
            "decisions": sorted(decisions, key=lambda d: (not d["blocking"], d["kind"], d["id"])),
        }

    def raise_blocking_approval(self) -> dict | None:
        """Raise an approval listing the blocking decisions, if any.

        This is what keeps the gap in the approval queue rather than only
        in a report that nobody opens.  It is raised once per distinct
        set of blocking decisions -- re-running with the same open
        decisions does not pile up duplicate approvals.
        """
        from .base import audit, request_approval

        report = self.collect()
        blocking = [d for d in report["decisions"] if d["blocking"]]
        if not blocking:
            return None

        fingerprint = json.dumps(
            sorted(f"{d['kind']}:{d['id']}" for d in blocking), sort_keys=True
        )
        existing = self.db.query(
            "SELECT payload FROM approvals "
            "WHERE action_type='decisions_owed' AND status='pending'"
        )
        for row in existing:
            try:
                if json.loads(row["payload"]).get("fingerprint") == fingerprint:
                    return None
            except (ValueError, TypeError):
                continue

        approval_id = request_approval(
            self.db, self.name, "decisions_owed",
            {
                "fingerprint": fingerprint,
                "count": len(blocking),
                "decisions": [
                    {"kind": d["kind"], "id": d["id"], "question": d["question"],
                     "blocks": d["blocks"]}
                    for d in blocking
                ],
            },
            risk="high",
        )
        audit(self.db, self.name, "decisions_owed_raised", "approvals", approval_id,
              {"blocking": len(blocking)})
        return {"approval_id": approval_id, "blocking": len(blocking)}


# --------------------------------------------------------------------------
# catalogue families
# --------------------------------------------------------------------------
#: Words that name a product line rather than a variant.  "Premium
#: USB-C Kabel - 60W - 1 Meter - Wit" and the 2- and 3-metre versions
#: are one line with three lengths; the colours are variants of the
#: same line.  Grouping on these keeps the decision to a handful.
_FAMILY_MARKERS = (
    "Premium USB-C Kabel",
    "USB Hub",
    "GPS Tracker",
    "Koptelefoon Case",
    "Koptelefoonhouder",
    "Sample",
)


def _catalogue_family(title: str) -> str:
    """The product line a storefront title belongs to."""
    text = (title or "").strip()
    for marker in _FAMILY_MARKERS:
        if text.lower().startswith(marker.lower()):
            return marker
    # Fall back to the words before the first separator, which is where
    # Shopify titles put the product name.
    for separator in (" - ", " – ", " | "):
        if separator in text:
            head = text.split(separator, 1)[0].strip()
            if head:
                return head
    return text or "unclassified"


def _family_question(status: str, family: str) -> str:
    if status == "SAMPLE":
        return (
            f"The '{family}' samples are demonstration units on the "
            "storefront. Sell them, or keep them as samples only?"
        )
    return (
        f"The '{family}' line sells on the storefront but is not in the "
        "master catalogue. Sell it, or take it off?"
    )


def _family_blocks(status: str, family: str) -> str:
    if status == "SAMPLE":
        return f"any offer that includes a {family} sample"
    return f"any offer that includes a {family} product"
