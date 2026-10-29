"""Bundle decomposition + "bijmaken" detection.

From the operating manual (section 4):

  * Incoming sea freight: oplaadcombinaties must book as bundles or
    purchase/stock data breaks (300-series).
  * "Bijmaken" of 300-series from loose adapter + cable is treated as a
    failure mode -- stock pollution plus extra warehouse load.

So the agent does two things:
  1. verify every bundle still decomposes into components that exist;
  2. flag any order line whose bundle components are missing from stock,
     i.e. the bundle would have to be assembled from loose stock.
"""
from __future__ import annotations

import json

from ..db.db import Database
from .base import audit, request_approval


class BundleAgent:
    name = "bundle_integrity"

    def __init__(self, db: Database):
        self.db = db

    # -- integrity -----------------------------------------------------
    def verify_spine(self) -> dict:
        bundles = self.db.query("SELECT * FROM bundles ORDER BY bundle_key")
        known = {r["sku_text"] for r in self.db.query("SELECT sku_text FROM components")}
        broken, ok = [], 0
        for b in bundles:
            comps = json.loads(b["component_skus"] or "[]")
            missing = [c for c in comps if c not in known]
            if missing:
                broken.append({"bundle": b["bundle_key"], "missing": missing,
                               "needs_format_fix": bool(b["needs_format_fix"])})
            else:
                ok += 1
        if broken:
            request_approval(self.db, self.name, "bundle_spine_broken",
                             {"broken": broken}, risk="high")
        audit(self.db, self.name, "spine_verified", "bundles", None,
              {"ok": ok, "broken": len(broken)})
        return {"bundles": len(bundles), "resolved": ok, "broken": broken}

    # -- bijmaken detection --------------------------------------------
    def detect_assembly(self, order_number: str) -> dict:
        """Flag bundle lines that would need loose components assembled."""
        order = self.db.query_one("SELECT * FROM orders WHERE order_number=?",
                                  (order_number,))
        if not order:
            raise KeyError(order_number)
        lines = self.db.query(
            """SELECT l.* FROM order_lines l WHERE l.order_id=? AND l.is_bundle=1""",
            (order["order_id"],))
        findings = []
        for line in lines:
            bundle = self.db.query_one(
                "SELECT component_skus FROM bundles WHERE bundle_sku=?", (line["sku"],))
            if not bundle:
                continue
            comps = json.loads(bundle["component_skus"] or "[]")
            shortages = []
            for comp in comps:
                stock = self.db.query_one(
                    "SELECT on_hand FROM stock WHERE sku=?", (comp,))
                have = int(stock["on_hand"]) if stock else 0
                if have < line["quantity"]:
                    shortages.append({"component": comp, "on_hand": have,
                                       "needed": line["quantity"]})
            if shortages:
                findings.append({"line": line["sku"], "shortages": shortages})
        if findings:
            request_approval(self.db, self.name, "bundle_assembly_required",
                             {"order_number": order_number, "findings": findings},
                             risk="high")
        audit(self.db, self.name, "assembly_checked", "order", order["order_id"],
              {"findings": len(findings)})
        return {"order_number": order_number, "assembly_required": findings}
