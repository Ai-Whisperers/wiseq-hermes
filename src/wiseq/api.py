"""FastAPI surface for the WiseQ operations replica.

Read-mostly by design.  The write endpoints create *drafts* and *approval
requests*; nothing publishes to a live marketplace or sends an email without
a human decision.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .api_auth import auth_status, check_api_access
from .config import get_settings
from .db.db import Database
from .orchestrator import WiseQOrchestrator

app = FastAPI(title="WiseQ Hermes", version="0.1.0",
              dependencies=[Depends(check_api_access)])

_db: Database | None = None
_orch: WiseQOrchestrator | None = None


def get_orchestrator() -> WiseQOrchestrator:
    global _db, _orch
    if _orch is None:
        settings = get_settings()
        _db = Database(settings.database_url)
        _db.init_schema()
        repo = Path(settings.repo_dir) if settings.repo_dir else None
        _orch = WiseQOrchestrator(_db, repo=repo,
                                   discount_pct=settings.school_discount_pct)
    return _orch


class SchedulerRunIn(BaseModel):
    """Optional job name; omit to run every job once."""
    job: str | None = None


class StrikeIn(BaseModel):
    week_start: str
    cause: str = "unknown"
    carrier: str | None = None


class OrderIn(BaseModel):
    email: str
    body: str = Field(..., min_length=1)
    country: str = "NL"


class OfferIn(BaseModel):
    order_number: str


class ApprovalIn(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    decided_by: str = "human"


class PriceImportIn(BaseModel):
    """A sell-price export.

    ``csv`` is the raw content of the export (CSV or JSON -- the endpoint
    detects which).  ``path`` is an alternative that reads the file from
    the server's disk.  ``source_name`` is the label recorded in the audit
    trail, e.g. ``"FiveX export 2026-10-29"``.
    """

    csv: str | None = None
    path: str | None = None
    source_name: str | None = None


class ShopifySyncIn(BaseModel):
    """Parameters for a live Shopify catalogue sync.

    ``store`` defaults to the WiseQ storefront.  ``csv_out`` writes the
    mirrored price rows to disk so they can be reviewed before being
    committed.  ``load_into_db`` can be set to false to preview only.
    """

    store: str | None = None
    csv_out: str | None = None
    load_into_db: bool = True


class UCPSyncIn(BaseModel):
    """Parameters for a live UCP/MCP catalogue sync.

    ``skus`` restricts the sync to specific business SKUs.  When omitted,
    every catalogue SKU that still lacks a real price is resolved.
    ``load_into_db`` can be set to false to preview only.
    """

    skus: list[str] | None = None
    load_into_db: bool = True


class ClassSetSizingIn(BaseModel):
    """A class-set sizing request.

    Mirrors the sizing table WiseQ publishes for schools.  ``use_model``
    may be given as free text (Dutch or English) and is resolved by the
    agent; if it cannot be resolved the endpoint returns 422 rather than
    guessing a quantity.
    """

    pupils: int = Field(..., gt=0)
    use_model: str = Field(..., min_length=1)
    devices: int | None = Field(default=None, gt=0)
    largest_group: int | None = Field(default=None, gt=0)
    intensive_shared_use: bool = False
    attrition_pct: float = Field(default=15.0, ge=10.0, le=15.0)
    age_group: str | None = None


class WarrantyCaseIn(BaseModel):
    """A warranty / repair case.

    ``damage_type`` is one of no_physical_break, physical_break or
    own_fault.  ``customer_admitted_fault`` records whether the customer
    themselves said the break was their own fault -- the manual's
    own-fault schedule only applies then.
    """

    model: str = Field(..., min_length=1)
    months_used: int = Field(..., ge=0)
    damage_type: str = Field(..., pattern="^(no_physical_break|physical_break|own_fault)$")
    customer_admitted_fault: bool = True


@app.post("/school/class-set-sizing")
def class_set_sizing(payload: ClassSetSizingIn):
    """Propose a class-set quantity from WiseQ's published sizing table.

    Deterministic and price-free: it returns quantities only.  The
    staffel price still requires Rob's export, so no total is computed
    here.
    """
    from .agents.class_set_sizing import (SizingRequest, resolve_use_model,
                                          size_class_set,
                                          suggest_models_for_pupils)

    model = resolve_use_model(payload.use_model)
    if model is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Gebruiksmodel niet herkend. Kies een van: gedeelde set per "
                "lokaal, gedeelde set per bouw, eigen setje per leerling, "
                "alleen digitale toetsen, of individuele leerlingen met "
                "prikkelgevoeligheid."),
        )
    request = SizingRequest(
        pupils=payload.pupils,
        use_model=model,
        devices=payload.devices,
        largest_group=payload.largest_group,
        intensive_shared_use=payload.intensive_shared_use,
        attrition_pct=payload.attrition_pct,
    )
    result = size_class_set(request).as_dict()
    result["suggested_models"] = suggest_models_for_pupils(
        payload.pupils, payload.age_group or "")
    result["source"] = ("https://www.wiseq.nl/pages/"
                        "klassenset-koptelefoons-kopen-school")
    return result


@app.post("/school/warranty-decision")
def warranty_decision(payload: WarrantyCaseIn):
    """Classify a warranty case and propose the commercial outcome.

    Always ``needs_approval``: the module proposes, a human decides.
    The percentage it returns is a REPLACEMENT discount, not a school
    discount and not a staffel price.
    """
    from .agents.warranty_policy import DamageType, decide_warranty

    decision = decide_warranty(
        payload.model,
        payload.months_used,
        DamageType(payload.damage_type),
        customer_admitted_fault=payload.customer_admitted_fault,
    )
    return decision.as_dict()


@app.get("/health")
def health():
    """Liveness plus the configuration an operator must be able to see.

    ``school_discount_pct`` is reported together with
    ``school_discount_is_placeholder`` because the school discount is NOT
    a verified WiseQ rule: the live site publishes volume tiers that live
    inside WiseQ's own Shopify app and cannot be synced.  A health check
    that hides this would let a placeholder percentage pass as a confirmed
    business rule.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "service": "wiseq-hermes",
        "school_discount_pct": settings.school_discount_pct,
        "school_discount_is_placeholder": settings.school_discount_is_placeholder,
        "auth": auth_status(),
    }


@app.get("/metrics")
def metrics():
    orch = get_orchestrator()
    return orch.metrics()


@app.post("/ingest")
def ingest():
    orch = get_orchestrator()
    try:
        return orch.ingest()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/prices/import")
def import_prices(payload: PriceImportIn):
    """Import sell prices for the catalogue.

    The client repository contains master data but no sell prices, so a
    freshly ingested catalogue is priced at 0 and the school pipeline will
    (correctly) refuse to quote.  This endpoint is the way out: hand it a
    ``sku_text,price_eur`` export from FiveX or Mastersheet and the
    catalogue becomes quotable.

    Rows whose SKU is not in the catalogue are reported back, and rows
    whose price cannot be read are reported as unresolved -- nothing is
    ever written as a zero.
    """
    orch = get_orchestrator()
    source = payload.csv
    if source is None and payload.path:
        p = Path(payload.path)
        if not p.exists():
            raise HTTPException(status_code=404,
                                detail=f"price file not found: {payload.path}")
        source = p.read_text(encoding="utf-8", errors="replace")
    if source is None:
        raise HTTPException(
            status_code=422,
            detail="provide either 'csv' (raw export content) or 'path'")
    return orch.load_prices(source, source_name=payload.source_name)


@app.get("/prices/gaps")
def price_gaps():
    """Which catalogue products still have no real price.

    Every entry here has ``synthetic_price = 1`` (never a real number) or
    a price of 0.  This is the checklist Rob hands back to whoever owns
    the price list.
    """
    orch = get_orchestrator()
    rows = orch.db.query(
        "SELECT sku_text, title, product_type, price_eur, synthetic_price "
        "FROM products WHERE price_eur <= 0 OR synthetic_price = 1 "
        "ORDER BY product_type, sku_text")
    return {"missing": rows, "count": len(rows)}


@app.post("/prices/sync-shopify")
def sync_shopify_prices(payload: ShopifySyncIn):
    """Mirror the live Shopify storefront and load its sell prices.

    ``https://www.wiseq.nl/products.json`` is public, so this endpoint needs
    no credentials and never writes to the live store.  It is the fastest way
    to close the price gap: the storefront publishes the same catalogue the
    repository describes, keyed by the same business SKUs.

    Variants that cannot be matched to a catalogue SKU are returned in
    ``not_in_catalogue`` and variants without a price are returned in
    ``unresolved`` -- nothing is ever silently written as zero.
    """
    orch = get_orchestrator()
    csv_out = None
    if payload.csv_out:
        csv_out = payload.csv_out
        Path(csv_out).parent.mkdir(parents=True, exist_ok=True)
    try:
        return orch.sync_shopify(
            store=payload.store,
            csv_out=csv_out,
            load_into_db=payload.load_into_db,
        )
    except Exception as exc:  # network / parsing failure
        raise HTTPException(status_code=502, detail=f"shopify sync failed: {exc}")


@app.post("/prices/sync-ucp")
def sync_ucp_prices(payload: UCPSyncIn):
    """Pull prices from the storefront's live UCP/MCP catalogue.

    ``https://www.wiseq.nl/api/ucp/mcp`` is the storefront's own
    Universal Commerce Protocol endpoint.  It needs no credentials, and its
    catalogue tools are read-only.

    This is a second, independent view of the same catalogue.  Where it
    disagrees with the Shopify mirror the disagreement is reported in
    ``price_mismatches`` rather than silently resolved -- a price source
    that changes without anyone noticing is how a business quotes the wrong
    number to a school.

    Checkout and cart tools exist on that endpoint and are deliberately not
    exposed here: an agent must not be able to spend money on its own.
    """
    orch = get_orchestrator()
    try:
        return orch.sync_ucp(
            skus=payload.skus,
            load_into_db=payload.load_into_db,
        )
    except Exception as exc:  # network / parsing failure
        raise HTTPException(status_code=502, detail=f"ucp sync failed: {exc}")


@app.post("/school-orders")
def create_school_order(payload: OrderIn):
    orch = get_orchestrator()
    agent = orch.school_order_agent()
    order = agent.handle_email(payload.body, source_email=payload.email,
                               country=payload.country)
    return {
        "order_number": order.order_number,
        "status": order.status.value,
        "subtotal_eur": order.subtotal_eur,
        "discount_eur": order.discount_eur,
        "shipping_eur": order.shipping_eur,
        "total_eur": order.total_eur,
        "is_framed": order.is_framed,
        "lines": [{
            "sku": l.sku, "title": l.title, "quantity": l.quantity,
            "unit_price_eur": l.unit_price_eur,
            "shipping_eur": l.shipping_eur,
            "carrier": l.carrier,
            "framing_status": l.framing_status.value,
            "reason": l.framing_reason,
        } for l in order.lines],
    }


@app.post("/school-orders/offer")
def build_offer(payload: OfferIn):
    orch = get_orchestrator()
    try:
        return orch.school_order_agent().build_offer(payload.order_number)
    except KeyError:
        raise HTTPException(status_code=404, detail="order not found")


@app.get("/bundle-spine")
def bundle_spine():
    orch = get_orchestrator()
    return orch.bundle_agent().verify_spine()


@app.post("/purchase-intel")
def purchase_intel():
    orch = get_orchestrator()
    computed = orch.purchase_agent().compute()
    return {**computed, "suggestions": orch.purchase_agent().replenishment_suggestions()}


@app.get("/assortment")
def assortment():
    orch = get_orchestrator()
    agent = orch.assortment_agent()
    return {"scan": agent.scan(), "segments": agent.segment_scores()}


@app.post("/reviews/draft")
def draft_reviews():
    orch = get_orchestrator()
    return {"drafts": orch.review_agent().draft_due()}


@app.get("/strikes")
def strikes():
    """bol.com on-time norm and strike state for the current week."""
    orch = get_orchestrator()
    return orch.strike_agent().evaluate()


@app.post("/strikes/record")
def record_strike(payload: StrikeIn):
    """Record a strike bol.com issued, and see the consequences."""
    orch = get_orchestrator()
    return orch.strike_agent().record_strike(
        payload.week_start, cause=payload.cause, carrier=payload.carrier)


@app.get("/stock-price-guard")
def stock_price_guard():
    """Low-stock articles that should have their price raised."""
    orch = get_orchestrator()
    return orch.stock_price_agent().recommend()


@app.get("/integration-backlog")
def integration_backlog():
    """Ranked open-source connectors that could fill real gaps."""
    orch = get_orchestrator()
    return orch.integration_agent().build_backlog()


@app.post("/integration-backlog/request-decision")
def integration_decision():
    """Ask Rob which integration to build first. Installs nothing."""
    orch = get_orchestrator()
    approval_id = orch.integration_agent().request_decision()
    return {"approval_id": approval_id, "status": "pending"}


@app.get("/scheduler")
def scheduler_status():
    """The recurring jobs and how their last runs went."""
    orch = get_orchestrator()
    sched = orch.scheduler()
    return {"jobs": sched.status()["jobs"],
            "recent_runs": sched.recent_runs(10)}


@app.post("/scheduler/run")
def scheduler_run(payload: SchedulerRunIn | None = None):
    """Run the recurring jobs once, now.

    This is the entry point for an external cron job, and it is how the
    demo exercises the scheduler without starting a background thread.
    """
    orch = get_orchestrator()
    sched = orch.scheduler()
    only = payload.job if payload else None
    results = sched.run_once(only=only)
    return {"ran": len(results), "results": results}


@app.get("/approvals")
def approvals():
    orch = get_orchestrator()
    return orch.db.query(
        "SELECT approval_id, agent_name, action_type, risk, status, requested_at "
        "FROM approvals ORDER BY requested_at DESC")


@app.post("/approvals/{approval_id}")
def decide(approval_id: str, payload: ApprovalIn):
    orch = get_orchestrator()
    row = orch.db.query_one("SELECT * FROM approvals WHERE approval_id=?",
                            (approval_id,))
    if not row:
        raise HTTPException(status_code=404, detail="approval not found")
    orch.db.execute(
        "UPDATE approvals SET status=?, decided_by=?, decided_at=CURRENT_TIMESTAMP "
        "WHERE approval_id=?",
        (payload.decision, payload.decided_by, approval_id))
    return {"approval_id": approval_id, "status": payload.decision}


@app.get("/audit")
def audit():
    orch = get_orchestrator()
    return orch.db.query(
        "SELECT actor, action, entity_type, entity_id, detail, requires_human, "
        "created_at FROM audit_log ORDER BY created_at DESC LIMIT 200")
