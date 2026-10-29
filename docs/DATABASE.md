# Database model

18 tables. Portable SQL — the same DDL runs on SQLite (local/test) and
PostgreSQL (Supabase/production). The data layer picks the backend from the
DSN; no query in the codebase is dialect-specific.

---

## Entity relationship diagram

```
                        ┌──────────────┐
                        │   schools    │
                        │ school_id PK │
                        │ name, email  │
                        │ city, size   │
                        └──────┬───────┘
                               │ 1
                               │
                 ┌─────────────┴──────────────┐
                 │ N                          │
        ┌────────▼────────┐          ┌────────▼────────┐
        │     orders      │          │     reviews     │
        │ order_id PK     │          │  review_id PK   │
        │ order_number UQ │──1──N──▶│  order_id FK    │
        │ customer_id FK  │          │  channel        │
        │ channel         │          │  status         │
        │ status          │          │  due_at         │
        │ total_eur       │          │  draft_body     │
        │ shipping_eur    │          └─────────────────┘
        │ discount_pct    │
        └────────┬────────┘
                 │ 1
                 │
        ┌────────▼────────┐
        │   order_lines   │
        │  line_id PK     │
        │  order_id FK    │
        │  sku            │
        │  quantity       │
        │  rule_key       │
        │  carrier        │
        │  tariff_key     │
        │  shipping_eur   │
        │  framing_status │◀── the core operational field
        │  is_bundle      │
        └────────┬────────┘
                 │ N
                 │
   ┌─────────────┼──────────────┐
   │             │              │
┌──▼──────────┐ ┌▼───────────┐ ┌▼──────────────┐
│  components │ │  bundles  │ │    products   │
│ sku_text PK │ │ bundle_id │ │ sku PK        │
│ title       │ │  bundle   │ │ title         │
│ product_type│ │  name     │ │ ean           │
└──┬──────────┘ │  ...      │ │ price_eur     │
   │            └─┬─────────┘ │ product_type  │
   │              │           └──┬───────────┘
   │              │ 1            │
   │        ┌─────▼─────────┐   │
   │        │ bundle_items  │   │
   │        │ bundle_id FK  │   │
   │        │ sku FK        │   │
   │        │ qty           │   │
   │        └───────────────┘   │
   │                            │
┌──▼───────────┐   ┌────────────▼─────┐   ┌────────────────┐
│ ean_registry │   │ shipping_rules   │   │ search_keywords│
│ sku PK       │   │ rule_key PK      │   │ keyword PK     │
│ ean          │   │ category         │   │ volume         │
│ status       │   │ carrier          │   │ intent         │
│ gs1_ref      │   │ country          │   │ position       │
│ source       │   │ article_kind     │   │ cpc            │
└──────────────┘   │ validation_status│   │ competition    │
                   │ confidence       │   └────────────────┘
                   └────────┬─────────┘
                            │ 1
                            │ N
                   ┌────────▼─────────┐
                   │ shipping_tariffs │
                   │ tariff_key PK    │
                   │ carrier          │
                   │ shipment_type    │
                   │ article_kind     │
                   │ country          │
                   │ weight_band      │
                   │ cost_eur         │
                   │ discount_eur     │
                   │ lvb_storage_eur  │
                   └──────────────────┘

  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐
  │   stock      │  │purchase_intel│  │   assortment   │
  │ sku PK       │  │  sku         │  │ listing_id PK  │
  │ qty          │  │  avg_qty_6m  │  │ account        │
  │ reserved     │  │  stock_qty   │  │ title_len      │
  └──────────────┘  │  suggested   │  │ desc_len       │
                    │  bracket     │  │ image_px       │
                    └──────────────┘  │ keyword_score  │
                                     │ content_score  │
  ┌──────────────┐  ┌──────────────┐  │ online         │
  │   outbox     │  │  audit_log   │  │ issues         │
  │ sent_to      │  │  audit_id    │  └────────────────┘
  │ intended_to  │  │  actor       │
  │ subject      │  │  action      │  ┌────────────────┐
  │ delivered    │  │  entity_type │  │  agent_runs    │
  └──────────────┘  │  requires_   │  │  run_id PK     │
                    │    human      │  │  agent_name    │
  ┌──────────────┐  │  created_at  │  │  status        │
  │  approvals   │  └──────────────┘  │  started_at    │
  │ approval_id  │                    │  finished_at   │
  │ agent_name   │                    │  summary       │
  │ action_type  │                    └────────────────┘
  │ risk         │
  │ status       │  ← the human gate: nothing consequential
  │ decided_by   │    happens without a row here being approved
  └──────────────┘
```

---

## The fields that carry the business meaning

### The two kinds of SKU

The model keeps two identifiers apart, and mixing them is the easiest way to
break a join:

| Column | What it is | Example |
|---|---|---|
| `products.sku` | an internal UUID, generated on ingest | `9f3c…-…` |
| `products.sku_text` | the **business SKU** — what the client calls the product | `231`, `117` |

`sku_text` is the key everything joins on: `components.sku_text`,
`bundles.bundle_sku`, `order_lines.sku`, `stock.sku`,
`ean_registry.sku` and `purchase_intel.sku` are all the **business SKU**,
not the UUID.

> This was a real bug during the build. `stock.sku` and `ean_registry.sku`
> were originally `uuid` columns but were written and looked up with the
> business SKU (`"210"`), so the joins could never match. Both tables are
> now keyed on the business SKU.

### `order_lines.framing_status`

The single most important field in the model. It answers "can we actually
ship this line, and do we know what it costs?".

| Value | Meaning | What the system does |
|---|---|---|
| `framed` | a rule and a tariff were found; the cost is known | the line is priced and included |
| `needs_confirmation` | the client has no approved rule for this category | the line is held; **never guessed** |
| `unframed` | no category could be derived from the title | the line is held |
| `case_by_case` | the client marked this category as per-shipment | the line is held |

A held line does not silently disappear — it stays on the order and appears
in the approval queue. That is the fix for "ungefrankeerde zendingen": the
system refuses to ship blind, and says so.

### `shipping_rules.validation_status`

Same idea, one level up. The client's own master sheet marks five
categories as unconfirmed:

| Category | Status in the data |
|---|---|
| `2x Adapter ?` | `NEEDS_CONFIRMATION` |
| `Koptelefooncase` | `NEEDS_CONFIRMATION` |
| `USB HUBS` | `CASE_BY_CASE` |
| `Smartwatch` | `CASE_BY_CASE` |
| `Tag` | `CASE_BY_CASE` |

Those five are the exact decision list for Rob (see `HANDOVER.md`).

### `shipping_tariffs`

One row per (carrier, shipment type, article kind, country, weight band).
The client's sheet uses the `Type` column for two different things depending
on the carrier: for LVB it is a **size class**, for PostNL/DHL/Bpost it is a
**shipment type**. The schema keeps both as separate columns
(`shipment_type` and `size_class`) so the same table serves both.

### `approvals`

The human gate. An agent that wants to send a message, issue an order,
change a price or apply a bulk content fix writes a row here first with a
`risk` level. Nothing proceeds until a row moves to `approved`. Rows that
stay `pending` are the visible work queue.

### `audit_log`

Every agent action, with `requires_human` flagging the ones that needed a
human to have acted. This is what makes "the agent did it" vs "the agent
prepared it and a human did it" distinguishable after the fact.

### `outbox`

Every message produced, with **both** `sent_to` (where it actually went)
and `intended_to` (the real customer, kept as a reference). During testing
`sent_to` is always `weissvanderpol@gmail.com`.

---

## Tables at a glance

| Table | Rows after ingest + seed | Source |
|---|---|---|
| `components` | 114 | `wiseq-component-registry.csv` |
| `bundles` | 25 | `wiseq-bundle-spine.csv` |
| `products` | 139 | 114 components + 25 bundles |
| `bundle_items` | bundle composition | bundle spine |
| `ean_registry` | 8 (5.8% coverage) | component registry |
| `shipping_rules` | 15 | `verzendregels-templates.csv` |
| `shipping_tariffs` | 30 | `verzendtarieven.csv` |
| `search_keywords` | 80 | `zoekvolume-google-filtered.csv` |
| `schools` | 6 | synthetic |
| `orders` | 25 | 24 synthetic + 1 from the demo |
| `order_lines` | 65 | synthetic + demo |
| `reviews` | 1 | demo |
| `assortment` | 40 | synthetic (mirrors bol.com fields) |
| `purchase_intel` | computed on demand | from order history |
| `stock` | computed on demand | |
| `outbox` | grows per message | |
| `audit_log` | grows per action | |
| `agent_runs` | grows per run | |
| `approvals` | grows per gated action | |

**EAN coverage is 5.8%** — that is real, not a defect of the loader. The
component registry only carries EANs for a fraction of SKUs. Filling it is
on Rob's list.
