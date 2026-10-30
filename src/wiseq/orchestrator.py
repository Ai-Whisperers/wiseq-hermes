"""One-call orchestration: load data, run every agent, report.

This is the entry point Hermes (or the API, or cron) calls.  It runs the
whole operating model end to end and returns a single structured report:

    from wiseq.orchestrator import WiseQOrchestrator
    orch = WiseQOrchestrator(db)
    report = orch.run_all()
"""
from __future__ import annotations

from pathlib import Path

from .agents.assortment import AssortmentAgent
from .agents.bundles import BundleAgent
from .agents.integration_catalogue import IntegrationCatalogueAgent
from .agents.decisions_owed import DecisionsAgent
from .agents.purchase_intel import PurchaseIntelligenceAgent
from .agents.reviews import ReviewAgent
from .agents.school_orders import SchoolOrderAgent
from .agents.stock_price_guard import StockPriceGuardAgent
from .agents.strike_monitor import StrikeMonitorAgent
from .connectors.mail import MailDispatcher
from .scheduler import Scheduler
from .db.db import Database
from .domain.models import Carrier, ShippingRule, Tariff, ValidationStatus
from .domain.shipping import ShippingResolver
from .ingest.loaders import load_all
from .ingest.prices import load_prices
from .agents.base import audit


def build_resolver(db: Database) -> ShippingResolver:
    rules = [ShippingRule(
        rule_key=r["rule_key"], category=r["category"], clone_note=r["clone_note"],
        template_ean=r["template_ean"], notes=r["notes"],
        validation_status=ValidationStatus(r["validation_status"]))
        for r in db.query("SELECT * FROM shipping_rules")]
    tariffs = []
    for t in db.query("SELECT * FROM shipping_tariffs"):
        try:
            carrier = Carrier(t["carrier"])
        except ValueError:
            # An unknown carrier must not take the whole shipping resolver
            # down.  Skip the row and let it surface as a missing tariff,
            # which is a business problem a human can see -- unlike a crash.
            audit(db, actor="orchestrator", action="skip_unknown_carrier",
                  entity_type="tariff", entity_id=t.get("tariff_key"),
                  detail={"carrier": t["carrier"]}, requires_human=False)
            continue
        tariffs.append(Tariff(
            tariff_key=t["tariff_key"], carrier=carrier,
            shipment_type=t["shipment_type"],
            article_kind=t["article_kind"], country=t["country"], weight_band=t["weight_band"],
            cost_eur=t["cost_eur"], discount_eur=t["discount_eur"],
            lvb_storage_eur=t["lvb_storage_eur"], notes=t["notes"],
            size_class=t["size_class"]))
    return ShippingResolver(rules, tariffs)


class WiseQOrchestrator:
    """Runs the full WiseQ operations replica."""

    def __init__(self, db: Database, repo: Path | None = None,
                 discount_pct: float | None = None):
        # NOTE: the default was 15.0 until 2026-10-29.  That silently
        # applied a 15% school discount to every quote built by a caller
        # that did not pass one explicitly -- and 15% is NOT a WiseQ rule
        # (the live 10-15% figure is per-year ATTRITION, not a discount;
        # real pricing is the staffel ladder behind the Sami B2B app).
        #
        # The default is now read from settings, which defaults to 0, so
        # an unset discount can never become a fabricated discount.
        # Callers that want a real value must pass it explicitly.
        if discount_pct is None:
            from .config import get_settings
            discount_pct = get_settings().school_discount_pct
        self.db = db
        self.repo = Path(repo) if repo else None
        self.discount_pct = discount_pct

    # -- ingest --------------------------------------------------------
    def ingest(self) -> dict:
        if not self.repo:
            raise RuntimeError("no repo directory configured for ingest")
        return load_all(self.db, self.repo)

    # -- prices --------------------------------------------------------
    def load_prices(self, source, source_name: str | None = None) -> dict:
        """Import sell prices for the catalogue.

        The client repository ships master data but not sell prices, so
        after ``ingest()`` every product is priced at 0 and the school
        pipeline correctly refuses to quote.  This closes that gap: give it
        a CSV/JSON export and the catalogue becomes quotable.

        See :mod:`wiseq.ingest.prices` for the accepted formats.
        """
        result = load_prices(self.db, source, source_name=source_name)
        audit(self.db, actor="price_importer", action="import_prices",
              entity_type="product",
              detail=result.as_dict(), requires_human=False)
        return result.as_dict()

    def sync_shopify(self, store: str | None = None, registry=None,
                     csv_out: str | None = None, load_into_db: bool = True) -> dict:
        """Mirror the live Shopify storefront and load its sell prices.

        The storefront publishes ``/products.json`` publicly, so this needs
        no credentials and performs no writes to the live store.  It is the
        fastest way to close the price gap for the catalogue.
        """
        from .ingest.shopify import DEFAULT_STORE, sync_shopify as _sync

        repo = Path(self.repo) if self.repo else None
        if registry is None and repo is not None:
            candidate = repo / "data" / "wiseq-component-registry.csv"
            registry = candidate if candidate.exists() else None
        report = _sync(
            db=self.db,
            store=store or DEFAULT_STORE,
            registry=registry,
            csv_out=csv_out,
            load_into_db=load_into_db,
        )
        audit(self.db, actor="shopify_sync", action="sync_shopify",
              entity_type="catalogue",
              detail={k: v for k, v in report.items()
                      if k not in ("unresolved", "not_in_catalogue")},
              requires_human=False)
        return report

    def sync_ucp(self, skus: list[str] | None = None,
                load_into_db: bool = True) -> dict:
        """Pull prices from the storefront's live UCP/MCP catalogue.

        The storefront publishes a Universal Commerce Protocol endpoint with
        read-only catalogue tools and no credentials required.  This is the
        counterpart to :meth:`sync_shopify`: the Shopify mirror reads the
        whole catalogue in one request, UCP resolves prices per SKU and
        reports any disagreement between the two sources instead of silently
        picking one.

        The write tools (checkout, cart) are blocked inside the connector --
        an agent never completes a purchase on its own.
        """
        from .connectors.ucp import UCPClient, sync_ucp_catalog

        client = UCPClient()
        report = sync_ucp_catalog(
            db=self.db, client=client, skus=skus, load_into_db=load_into_db
        )
        audit(self.db, actor="ucp_sync", action="sync_ucp",
              entity_type="catalogue",
              detail={k: v for k, v in report.items()
                      if k not in ("not_found", "price_mismatches")},
              requires_human=False)
        return report

    # -- agents --------------------------------------------------------
    def resolver(self) -> ShippingResolver:
        return build_resolver(self.db)

    def school_order_agent(self) -> SchoolOrderAgent:
        return SchoolOrderAgent(self.db, self.resolver(), self.discount_pct)

    def bundle_agent(self) -> BundleAgent:
        return BundleAgent(self.db)

    def purchase_agent(self) -> PurchaseIntelligenceAgent:
        return PurchaseIntelligenceAgent(self.db)

    def review_agent(self) -> ReviewAgent:
        # use the configured delay rather than the agent's literal default,
        # so WISEQ_REVIEW_DELAY_DAYS actually takes effect
        from .config import get_settings
        return ReviewAgent(self.db, delay_days=get_settings().review_invitation_delay_days)

    def assortment_agent(self) -> AssortmentAgent:
        return AssortmentAgent(self.db)

    def strike_agent(self) -> StrikeMonitorAgent:
        return StrikeMonitorAgent(self.db)

    def stock_price_agent(self) -> StockPriceGuardAgent:
        return StockPriceGuardAgent(self.db)

    def integration_agent(self) -> IntegrationCatalogueAgent:
        return IntegrationCatalogueAgent(self.db, repo=self.repo)

    def decisions_agent(self) -> DecisionsAgent:
        return DecisionsAgent(self.db, repo=self.repo)

    def mailer(self) -> MailDispatcher:
        return MailDispatcher(self.db)

    # -- scheduler ------------------------------------------------------
    def scheduler(self) -> Scheduler:
        """Build the recurring job loop with the manual's own cadence.

        The cadences come from the client's own documentation:

        * bol.com evaluates the on-time norm every Wednesday at 10:00 --
          so the strike check runs hourly and reports when the weekly
          evaluation window is open;
        * the storefront catalogue drifts, so the sync runs on a short
          interval;
        * stock changes with every order, so the guard runs daily;
        * review invitations follow delivery by a configured delay.

        Every job is detect-and-recommend: none of them sends an email,
        changes a live price, or contacts bol.com.
        """
        from .scheduler import Scheduler

        sched = Scheduler(self.db)

        def _sync_shopify():
            result = self.sync_shopify()
            return {"priced": result.get("priced_rows"),
                    "unresolved": len(result.get("unresolved") or []),
                    "seen": result.get("seen_products")}

        def _strike_check():
            report = self.strike_agent().evaluate()
            return {"on_time_rate_pct": report.get("on_time_rate_pct"),
                    "strikes": report.get("strikes"),
                    "escalate_to_rob": report.get("escalate_to_rob")}

        def _stock_guard():
            report = self.stock_price_agent().recommend()
            return {"low_stock": report.get("low_stock"),
                    "actionable": report.get("actionable")}

        def _review_drafts():
            drafts = self.review_agent().draft_due()
            return {"drafts": len(drafts)}

        def _price_gaps():
            gaps = self.db.query(
                "SELECT sku_text FROM products WHERE price_eur IS NULL "
                "OR price_eur <= 0")
            return {"unpriced_skus": len(gaps)}

        def _decisions_owed():
            # Raises an approval when a blocking decision is still open,
            # so the gap shows up in the approval queue and not only in a
            # report somebody has to remember to open.
            raised = self.decisions_agent().raise_blocking_approval()
            report = self.decisions_agent().collect()
            return {"total": report["total"], "blocking": report["blocking"],
                    "raised": bool(raised)}

        sched.every("sync_shopify", 3600, _sync_shopify,
                    description="Mirror the live storefront catalogue and prices.")
        sched.every("strike_check", 3600, _strike_check,
                    description="bol.com on-time norm; escalate at 3 strikes.")
        sched.every("stock_guard", 86400, _stock_guard,
                    description="Low-stock price raise recommendations.")
        sched.every("review_drafts", 86400, _review_drafts,
                    description="Draft review invitations that are due.")
        sched.every("price_gaps", 21600, _price_gaps,
                    description="Catalogue items still without a sell price.")
        sched.every("decisions_owed", 21600, _decisions_owed,
                    description="Human decisions still open; raises an approval.")
        return sched

    # -- full run ------------------------------------------------------
    def run_all(self) -> dict:
        report: dict = {}
        report["bundle_spine"] = self.bundle_agent().verify_spine()
        report["purchase_intel"] = self.purchase_agent().compute()
        report["assortment"] = self.assortment_agent().scan()
        report["strike"] = self.strike_agent().evaluate()
        report["stock_price_guard"] = self.stock_price_agent().recommend()
        report["pending_approvals"] = self.db.query(
            "SELECT agent_name, action_type, risk, status FROM approvals "
            "WHERE status='pending' ORDER BY requested_at")
        report["audit_entries"] = self.db.scalar(
            "SELECT COUNT(*) FROM audit_log") or 0
        return report

    # -- metrics -------------------------------------------------------
    def metrics(self) -> dict:
        q = self.db.query_one
        products = q("SELECT COUNT(*) AS n FROM products")["n"]
        with_ean = q("SELECT COUNT(*) AS n FROM products WHERE has_ean=1")["n"]
        bundles = q("SELECT COUNT(*) AS n FROM bundles")["n"]
        rules = q("SELECT COUNT(*) AS n FROM shipping_rules")["n"]
        ok_rules = q("SELECT COUNT(*) AS n FROM shipping_rules "
                     "WHERE validation_status='OK'")["n"]
        tariffs = q("SELECT COUNT(*) AS n FROM shipping_tariffs")["n"]
        orders = q("SELECT COUNT(*) AS n FROM orders")["n"]
        unframed = q("SELECT COUNT(*) AS n FROM order_lines "
                     "WHERE framing_status!='framed'")["n"]
        lines = q("SELECT COUNT(*) AS n FROM order_lines")["n"]
        reviews = q("SELECT COUNT(*) AS n FROM reviews")["n"]
        pending = q("SELECT COUNT(*) AS n FROM approvals WHERE status='pending'")["n"]
        return {
            "products": products,
            "products_with_ean": with_ean,
            "ean_coverage_pct": round(with_ean * 100.0 / products, 1) if products else 0,
            "bundles": bundles,
            "shipping_rules": rules,
            "shipping_rules_validated_ok": ok_rules,
            "shipping_rules_needing_confirmation": rules - ok_rules,
            "tariffs": tariffs,
            "orders": orders,
            "order_lines": lines,
            "unframed_lines": unframed,
            "framing_rate_pct": round((lines - unframed) * 100.0 / lines, 1) if lines else 0,
            "reviews": reviews,
            "pending_approvals": pending,
        }