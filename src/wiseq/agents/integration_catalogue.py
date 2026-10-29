"""Integration catalogue: match researched OSS connectors to real gaps.

The client repository ships ``data/oss/*.json`` -- 31 curated searches of
open-source projects that could plug into WiseQ's operation (bol.com,
Shopify, EAN/GS1, invoicing, repricing, and so on).  Each file holds a
GitHub search result: ``query``, ``total_count`` and a list of candidate
repositories with stars, language and description.

Those files are research, not functionality.  This agent turns them into
an actionable, ranked integration backlog by matching each lane against
what the operating model actually needs, and by scoring candidates with
signals that can be checked without a network call:

  * language fit (Python first -- this system is Python),
  * MCP support in the description or name (the project's stated
    direction is agents/MCP, and an MCP server plugs in without writing
    a custom connector),
  * OpenAPI or "open source" markers,
  * popularity (stars, on a log scale so a 300-star project does not
    erase a 30-star one).

Every candidate keeps its provenance -- which research lane it came from
and the query that found it -- so nothing in the backlog is a bare
assertion.  Nothing is installed or executed: this is a BACKLOG for Rob
to decide on, and the ranking is a recommendation, not a verdict.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from ..db.db import Database
from .base import audit, request_approval


#: Which operating capability each research lane addresses.  Keys match the
#: file stem in ``data/oss/``.
LANE_PURPOSE: dict[str, str] = {
    "bol-com": "bol.com Retailer API: orders, offers, shipments, invoices",
    "marketplace-api": "generic marketplace APIs (Amazon, bol, Etsy style)",
    "marketplace-sync": "syncing listings and stock across marketplaces",
    "shopify-cli": "Shopify Admin CLI: the storefront WiseQ already runs on",
    "shopify-tooling": "Shopify tooling: metafields, bulk ops, storefront data",
    "product-feed": "product feed generation for shopping channels",
    "google-shopping-feed": "Google Shopping / Merchant Center feeds",
    "scraper-commerce": "scraping commerce sites for price and stock watch",
    "price-intelligence": "price intelligence and competitor price tracking",
    "repricer": "automated repricing",
    "product-matching": "matching products across catalogues",
    "ean-gs1": "EAN/GS1 barcodes: the identifiers WiseQ's items need",
    "barcodes-labels": "barcode label printing for shipping",
    "inventory-sync": "inventory synchronisation between systems",
    "warehouse": "warehouse and fulfilment",
    "order-to-cash": "order to cash: invoicing, payment, reconciliation",
    "invoice-parse": "parsing incoming invoices (SIFEN XML)",
    "accounting": "accounting and bookkeeping exports",
    "analytics-privacy": "analytics, cookies and privacy compliance",
    "helpdesk": "helpdesk and customer service",
    "email-automation": "transactional email and campaigns",
    "calendar-scheduling": "scheduling (shipments, pickups, appointments)",
    "workflow": "general workflow automation",
    "content-generation": "product content generation",
    "translations": "translation for catalogue and support content",
    "pdf-generation": "PDF generation for quotes, invoices and labels",
    "edtech": "education / school device management",
    "pim-open": "open-source product information management",
    "agentic-commerce": "agentic commerce protocols (UCP and similar)",
    "seo-audit": "SEO auditing of the storefront",
    "review-automation": "review collection and monitoring",
}

#: Lanes that map onto a capability the replica ALREADY implements.  These
#: are ranked lower for *building* but stay listed, because Rob may still
#: want a production-grade component.
ALREADY_COVERED: dict[str, str] = {
    "bol-com": "bol.com catalogue + orders modelled; strike monitor implemented",
    "shopify-cli": "Shopify catalogue + price sync implemented (public endpoint)",
    "agentic-commerce": "UCP/MCP connector implemented and verified against live",
    "price-intelligence": "price import + Shopify/UCP sync implemented",
    "invoice-parse": "SIFEN XML import noted as a future step, not built",
    "repricer": "stock-based price guard implemented as recommend-only",
    "product-matching": "SKU/title matching implemented in the school parser",
    "scraper-commerce": "public-site audit implemented; bol/Trustpilot remain blocked",
}


def _log_scale(stars: int) -> float:
    """Stars on a log scale so popularity informs but does not dominate."""
    try:
        return math.log10(max(int(stars or 0), 0) + 1)
    except (TypeError, ValueError):
        return 0.0


def _mcp_hint(item: dict) -> bool:
    blob = " ".join(str(item.get(k) or "") for k in
                    ("full_name", "desc", "description")).lower()
    return bool(re.search(r"\bmcp\b|model context protocol", blob))


def _openapi_hint(item: dict) -> bool:
    blob = " ".join(str(item.get(k) or "") for k in
                    ("full_name", "desc", "description")).lower()
    return "openapi" in blob or "open api" in blob


def score_candidate(item: dict) -> dict[str, Any]:
    """Score one repository candidate.  All signals are locally checkable."""
    stars = int(item.get("stars") or 0)
    lang = (item.get("lang") or "").strip()
    score = 0.0
    reasons: list[str] = []

    if lang.lower() == "python":
        score += 3.0
        reasons.append("Python: plugs into this system directly")
    elif lang:
        score += 0.5

    if _mcp_hint(item):
        score += 3.0
        reasons.append("exposes MCP: no custom connector needed")

    if _openapi_hint(item):
        score += 1.0
        reasons.append("OpenAPI client")

    score += _log_scale(stars)
    if stars >= 20:
        reasons.append(f"{stars} stars")

    return {
        "repo": item.get("full_name"),
        "url": item.get("url"),
        "stars": stars,
        "language": lang,
        "description": item.get("desc") or item.get("description") or "",
        "score": round(score, 2),
        "reasons": reasons,
    }


class IntegrationCatalogueAgent:
    """Ranks researched OSS connectors against the operating model's gaps."""

    name = "integration_catalogue"

    def __init__(self, db: Database, repo: Path | None = None):
        self.db = db
        self.repo = Path(repo) if repo else None

    def load_lanes(self) -> list[dict]:
        """Read every research lane from the client repository."""
        if not self.repo:
            return []
        oss_dir = self.repo / "data" / "oss"
        if not oss_dir.exists():
            return []
        lanes: list[dict] = []
        for path in sorted(oss_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            stem = path.stem
            lanes.append({
                "lane": stem,
                "query": payload.get("query", ""),
                "total_count": payload.get("total_count"),
                "purpose": LANE_PURPOSE.get(stem, "unclassified research lane"),
                "already_covered": ALREADY_COVERED.get(stem),
                "items": payload.get("items") or [],
            })
        return lanes

    def build_backlog(self, limit_per_lane: int = 5) -> dict[str, Any]:
        """Produce the ranked integration backlog."""
        lanes = self.load_lanes()
        backlog: list[dict[str, Any]] = []
        for lane in lanes:
            scored = []
            for item in lane["items"]:
                s = score_candidate(item)
                if not s["repo"]:
                    continue
                s["lane"] = lane["lane"]
                s["lane_purpose"] = lane["purpose"]
                s["provenance_query"] = lane["query"]
                s["already_covered"] = lane["already_covered"]
                scored.append(s)
            scored.sort(key=lambda x: x["score"], reverse=True)
            backlog.append({
                "lane": lane["lane"],
                "purpose": lane["purpose"],
                "query": lane["query"],
                "candidates_found": len(lane["items"]),
                "already_covered": lane["already_covered"],
                "top": scored[:limit_per_lane],
            })

        # Highest-value lanes first: uncovered capability beats a
        # well-covered one even at a similar score.
        backlog.sort(key=lambda b: (b["already_covered"] is not None,
                                    -max((c["score"] for c in b["top"]),
                                         default=0)))

        totals = {
            "lanes": len(lanes),
            "candidates": sum(len(l["items"]) for l in lanes),
            "uncovered_lanes": sum(1 for b in backlog
                                   if b["already_covered"] is None),
        }
        audit(self.db, self.name, "integration_backlog_built", None, None, totals)
        return {**totals, "backlog": backlog}

    def request_decision(self) -> str:
        """Ask Rob which integration to build first.

        Nothing is installed automatically -- an integration changes how
        WiseQ's live operation runs, so it needs an explicit choice.
        """
        built = self.build_backlog()
        uncovered = [b for b in built["backlog"] if b["already_covered"] is None]
        approval_id = request_approval(
            self.db, self.name, "integration_backlog_review",
            {
                "lanes": built["lanes"],
                "candidates": built["candidates"],
                "uncovered_lanes": built["uncovered_lanes"],
                "top_lanes": [
                    {"lane": b["lane"], "purpose": b["purpose"],
                     "best": b["top"][0] if b["top"] else None}
                    for b in uncovered[:8]
                ],
                "note": ("Ranked from the repository's own OSS research. "
                         "Nothing is installed without Rob's choice."),
            },
            risk="low")
        return approval_id
