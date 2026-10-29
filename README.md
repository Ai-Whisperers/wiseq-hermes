# WiseQ × Hermes — agentic operations replica

A working, portable replica of WiseQ's daily operations, built so that the
**business behaviour lives in Hermes agents and tools**, not in a bespoke
application. The Python package here is deliberately thin: it holds the
deterministic rules (shipping thresholds, bundle composition, discount
maths) and exposes them as an API that agents, MCP servers and cron jobs
drive.

Everything is open source, everything is code, and the whole directory can be
copied, moved, started and deleted without touching the host.

---

## What it does today (verified working)

| Capability | Where | Verified |
|---|---|---|
| Load the client's **real** master data (114 components → 25 bundles, 15 shipping rules, 30 tariffs, 80 SEO keywords) | `wiseq.ingest.loaders` | yes |
| Turn an inbound school email into a priced, **framed** order (school discount defaults to a flagged 0% placeholder) | `wiseq.agents.school_orders` | yes |
| Read the way Dutch schools actually write ("10x MagSafe draadloze oplader"), not just "product x 10" | `wiseq.agents.school_orders` | yes |
| Match a school's loose description to the catalogue title ("MagSafe draadloze oplader" → "Draadloze Oplader - Geschikt Voor MagSafe - 1 Meter - Wit") | `wiseq.agents.school_orders` | yes |
| Decide shipping per line: carrier, rate, and cost — with an explicit *needs-confirmation* state when the client has no approved rule | `wiseq.domain.shipping` | yes |
| Verify the bundle spine (every bundle resolvable from components) | `wiseq.agents.bundles` | yes |
| Detect the "we forgot to add the cables" failure mode before it reaches the customer | `wiseq.agents.bundles` | yes |
| 6-month rolling purchase intelligence with reorder suggestions | `wiseq.agents.purchasing` | yes |
| Draft Dutch review requests for bol.com — **draft only, a human sends** | `wiseq.agents.reviews` | yes |
| Scan bol.com listings for content-quality problems, per account segment | `wiseq.agents.assortment` | yes |
| Approval gate: every consequential action waits for a human decision | `wiseq.agents.base` | yes |
| **Refuse to quote a school EUR 0 for goods** — an offer with unpriced lines is blocked and a human is asked for the prices | `wiseq.agents.school_orders` | yes |
| **Import sell prices** from a FiveX/Mastersheet export (CSV or JSON, Dutch or English headers) — the repo ships master data but no prices | `wiseq.ingest.prices` | yes |
| Audit trail of every agent action | `audit_log` table | yes |
| Test email that **only ever** goes to `weissvanderpol@gmail.com` | `wiseq.connectors.mail` | yes |
| Same code running on **PostgreSQL 18** (the Supabase backend) and SQLite | `wiseq.db` | yes |

**Test results: 70 unit tests on SQLite (+4 PostgreSQL tests = 74). 18 API acceptance checks pass.**

---

## Showing it to Rob

There is a purpose-built script for the client-facing walkthrough. It needs
no credentials, no Docker and no network:

```bash
WISEQ_REPO_DIR=./data/wiseq-repo .venv/bin/python scripts/demo_for_rob.py
```

It tells the story in seven steps with the real numbers on screen: your
catalogue loaded (114 components → 25 bundles), a school email read the way
schools actually write it, the order priced against your own tariffs, the
price import that makes a quote possible, the human approval that stops
anything being sent, Dutch review drafts, and 6-month purchase intelligence.

The same script runs as verification step 4b, so it can never silently rot.

---

## Quick start — three ways

### 1. Docker (what Rob will actually use)

```bash
cp -r wiseq-hermes wiseq
cd wiseq
cp .env.example .env          # edit: set Supabase DSN if you want PostgreSQL
docker compose up -d
curl http://localhost:8000/health
```

Compose starts three services:

| Service | Purpose | Port |
|---|---|---|
| `wiseq` | the Hermes agent API | 8000 |
| `mailhog` | local SMTP sink — **no real email is ever sent** (web UI on 8025) | 8025 |
| `postgres` | optional local PostgreSQL (`--profile localdb`) | 5432 |

To delete everything: `docker compose down -v`. That removes the image's
volumes too. Nothing is left behind.

### 2. Local Python (no Docker)

```bash
./scripts/run_local.sh --demo
```

Creates a venv, installs the package, runs the test suite, runs the full
end-to-end demo, then serves the API.

### 3. Just the demo, no server

```bash
.venv/bin/python scripts/demo_end_to_end.py /path/to/wiseq-repo
```

Prints an 11-step report of the whole operating model against the real
client data. This is the fastest way to see what the system does.

> **If you install by hand, use `pip install -e ".[dev]"`, not
> `pip install ".[dev]"`.** A plain install copies the package into
> site-packages, so later edits to `src/wiseq/` are invisible to anything
> that imports it -- new API routes will keep answering 404 while the
> unit tests pass, because the tests read `src/` directly. `scripts/run_local.sh`
> already installs editable; this note is for manual installs.

> **If the install prints `bash: id: command not found`, it is harmless --
> ignore it.** It comes from the shell wrapper that launches the install
> probing the current user where the `id` utility is not on `PATH` -- not
> from this project, which never calls `id` or `whoami`. The install
> completes normally and every verification step passes afterwards. Add
> `coreutils` to `PATH`, or install with `--no-build-isolation`, if you
> want it gone.

---

## Getting the client data

The system reads the WiseQ client data repository. Point `WISEQ_REPO_DIR` at
your copy:

```bash
git clone --depth 1 https://github.com/Ai-Whisperers/wiseq-ai-onboarding.git data/wiseq-repo
```

The loaders read:

```
data/wiseq-component-registry.csv              -> components
data/wiseq-bundle-spine.csv                    -> bundles
data/client/mastersheet/verzendregels-templates.csv  -> shipping rules
data/client/mastersheet/verzendtarieven.csv    -> shipping tariffs
data/client/mastersheet/zoekvolume-google-filtered.csv -> SEO keywords
```

Re-ingesting is idempotent (`ON CONFLICT DO UPDATE`), so you can point it at
an updated export and re-run `POST /ingest` without duplicating anything.

---

## Configuration

Copy `.env.example` to `.env`. Every secret is `[REDACTED]` in the template
on purpose — Rob fills in his own values.

| Variable | Purpose | Default |
|---|---|---|
| `WISEQ_DATABASE_URL` | Supabase/Postgres DSN, or `sqlite:///./wiseq.db` | sqlite |
| `WISEQ_REPO_DIR` | root of the client data repo | — |
| `WISEQ_TEST_RECIPIENT` | **every** outbound mail goes here | `weissvanderpol@gmail.com` |
| `WISEQ_TEST_SENDER` | dummy sender identity | `wiseq-agent@example.invalid` |
| `SMTP_HOST` / `SMTP_PORT` | local mail sink | `mailhog` / `1025` |
| `WISEQ_SCHOOL_DISCOUNT_PCT` | school discount — **placeholder until confirmed** | `0` |
| `WISEQ_SCHOOL_DISCOUNT_CONFIRMED` | set `true` only once Rob supplies the real staffel ladder | `false` |
| `WISEQ_REVIEW_DELAY_DAYS` | review-request delay | `7` |
| `WISEQ_STRIKE_ESCALATION` | strike escalation threshold | `3` |

The business constants live in configuration, not in code, so changing the
school discount changes every agent's behaviour without a code change.

**The school discount is not a verified WiseQ rule.** The live site
publishes *staffelprijzen* (volume tiers) whose prices live inside WiseQ's
own Shopify app and are visible only after a buyer registers — so they are
in neither the public catalogue, nor the repository, nor the UCP/MCP feed,
and cannot be synced. The system therefore ships `0` with the placeholder
flagged, and `/health` reports `school_discount_is_placeholder: true` so
the state is visible to an operator rather than hidden. Both `0` and `15`
are treated as unverified and can never be confirmed.

---

## The API

`GET /openapi.json` is the contract; `/docs` is the browser UI.

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/metrics` | counts + quality KPIs |
| POST | `/ingest` | load the client's master data |
| POST | `/school-orders` | email → priced order |
| POST | `/school-orders/offer` | order → offer draft (queues an approval) |
| GET | `/bundle-spine` | bundle integrity report |
| POST | `/purchase-intel` | 6-month rolling purchase intelligence |
| GET | `/assortment` | bol.com content-quality scan + segment scores |
| POST | `/prices/import` | import sell prices (CSV/JSON export from FiveX) |
| GET | `/prices/gaps` | which products still have no real price |
| POST | `/school/class-set-sizing` | class-set quantity from WiseQ's published sizing table |
| POST | `/school/warranty-decision` | classify a repair case from the manual's price list |
| POST | `/reviews/draft` | Dutch review drafts (human sends) |
| GET | `/approvals` | the human approval queue |
| POST | `/approvals/{id}` | approve or reject |
| GET | `/audit` | full agent audit trail |

Acceptance test: `./scripts/api_smoke.sh http://localhost:8000`

### The two school rules that are now computable

**Class-set sizing** (`POST /school/class-set-sizing`) applies the sizing
table WiseQ publishes for schools:

| Use model | Quantity |
|---|---|
| Shared set per room | number of devices + 2 |
| Shared set per building (rotating) | largest group + 10% |
| Own pair per pupil | number of pupils + 10% |
| Digital exams only | largest exam group + 3 |
| Individual pupils with sensory needs | one per pupil |

Where a school declares **intensive shared use**, the published
**10–15% attrition allowance** ("10 tot 15% uitval per schooljaar")
*replaces* the table's own buffer rather than being added to it — the two
describe the same spares, and stacking them would quote a number WiseQ
does not publish. An unrecognised use model is refused with 422; the
system never guesses a quantity. No price is returned, because the
staffel ladder is not public.

**Warranty decisions** (`POST /school/warranty-decision`) apply the
repair-and-discount schedule from the client's internal manual
(`Handleiding_opzet.txt`), which distinguishes damage type, model family
and device age. Every outcome is marked `needs_approval: true` — the
module proposes, a human decides. The percentage it returns is a
*replacement* discount, not a school discount and not a staffel price.

**One thing is still open and the code cannot close it:** WiseQ's public
surfaces state three different warranty positions (1 year on the legal
pages and in `agents.md`, 2 years on Amazon and in Rob's manual, and
2 years *including physical damage* on the school-ICT page). The repair
schedule follows the manual. Rob must decide which public promise is
operative before any of it goes into a customer-facing answer.

### What runs without you, and what still waits

**The scheduler** (`GET /scheduler`, `POST /scheduler/run`, and
`scripts/run_scheduler.py`) turns the manual's cadence into recurring
jobs:

| Job | Cadence | What it does |
|---|---|---|
| `sync_shopify` | hourly | Mirrors the live storefront catalogue and prices |
| `strike_check` | hourly | bol.com on-time norm; escalates at 3 strikes |
| `price_gaps` | every 6h | Catalogue items still without a sell price |
| `stock_guard` | daily | Low-stock price-raise recommendations |
| `review_drafts` | daily | Review invitations that have come due |

Every job is **detect-and-recommend**. The scheduler never sends an
email, never changes a live price and never contacts bol.com -- it
writes approvals for a human to decide on. A job that raises an
exception is logged with its traceback and the loop continues; every
run is recorded in `job_runs`. Run it from cron with
`python scripts/run_scheduler.py once`, or in the foreground with
`serve`.

### Authentication -- and why remote access fails closed

The API can raise approvals, draft offers and trigger a live price
sync, so it is not left open. The rules:

- `/health` and `/metrics` stay open (liveness probes need them);
- reads from `127.0.0.1` need no token (local dev, the smoke test);
- **every write needs the token, from anywhere** -- a local process
  cannot quietly change a price either;
- remote reads need the token;
- **with no token configured, remote access is refused**, not allowed.
  "Nobody set it up yet" is the common case, and failing open would be
  the dangerous default.

Set `WISEQ_API_TOKEN` in `.env` and send it as `X-WiseQ-Token: <token>`
or `Authorization: Bearer <token>`. `/health` reports the current
posture under `auth`.

### The two rules that protect the operating week

**Strike watch** (`GET /strikes`, `POST /strikes/record`) implements the
protocol from the operating manual: bol.com evaluates a **93% on-time
norm** every Wednesday, **3 strikes** means Rob is involved and a plan of
action is executed, and **5 strikes** means the whole assortment switches
to VVB. The system computes the on-time rate, tracks the strike count and
raises one escalation approval when the threshold is crossed. It never
contacts bol.com, never emails the carrier and never switches an
account. When a strike is carrier-caused, the response carries the
72-hour follow-up rule and the QLS contact address.

**Low-stock price guard** (`GET /stock-price-guard`) implements the
pricing rule from the setup guide: raise the price when available stock
falls to **10 units or fewer**, so demand slows before the new delivery
arrives, and revert afterwards. "Available" means `on_hand - reserved`, so
units already spoken for do not count. The guide hedges the *size* of the
raise ("I believe it is 10%"), so **10% ships as a labelled placeholder**
and the threshold of 10 units is treated as fact. The agent only
recommends: a live price change waits for a human, and the
recommendation reminds the operator that the raise has to be set on
**both** selling accounts.

The guide also warns that a fixed threshold of 10 is often **already
too late** -- "some articles sell 10 units a day, and we see the stock
gap arrive sooner". So the guard also computes **days of cover** (stock
left, divided by the recent sales rate) and flags anything within three
days as `stockout_imminent`. In the demo, SKU 231 -- a live bestseller
with real sales history -- is flagged urgent while items with no sales
history show cover as unknown rather than pretending to be safe.

**Integration backlog** (`GET /integration-backlog`) does something the
previous version forgot to do: the client repository contains **31
curated open-source research lanes (428 candidate projects)** that
nothing in the system ever read. They were research, not a plan. The
agent now turns them into a ranked backlog, scoring each candidate on
language fit, MCP support, OpenAPI markers and popularity (on a log
scale), marking which lanes this replica already covers, and keeping the
originating query as provenance. Nothing is installed -- the endpoint
only reads the repository's own files. `POST
/integration-backlog/request-decision` raises an approval asking Rob
which one to build first.

---

## The human-in-the-loop rule

This system **never sends a message to a real customer, never issues an
order, and never changes a price** on its own. It prepares the work and
queues an approval:

1. An agent prepares the action and writes an `approvals` row.
2. A human opens `/approvals`, sees what would happen, and approves or rejects.
3. Only then is anything sent — and even then, outbound mail is addressed to
   `WISEQ_TEST_RECIPIENT` until Rob deliberately changes that.

Mail that is produced is stored in the `outbox` table with both the real
intended recipient (as a reference) and the address it was actually sent to,
so it is always auditable.

---

## Verification status — read this before trusting it

Everything in the table under "What it does today" was **executed** in this
environment and produced the stated result. Specifically:

- `340 passed, 4 skipped` — unit test suite on SQLite (`pytest -q`); the 4 skips are the PostgreSQL-only tests
- `344 passed, 0 skipped` — same suite plus the PostgreSQL backend tests
  (`WISEQ_TEST_PG_URL=... pytest -q`)
- `passed: 37  failed: 0` — API acceptance script against a live server
- End-to-end demo: 11 steps, real client data, 100% order-line framing rate,
  identical metrics on SQLite and on PostgreSQL 18.6
- PostgreSQL: a real server (18.6) was started here, the schema was created,
  the full ingestion and order flow ran, and the results were read back out
  of the database to confirm they persisted
- SMTP delivery confirmed against a live local SMTP server: message
  addressed `To: weissvanderpol@gmail.com`, `delivered: True`

**Not** verified here, and why:

| Item | Status | Reason |
|---|---|---|
| `docker build` / `docker compose up` | **not run** | this container has the Docker CLI but no daemon, no compose plugin and no `podman`. The image was validated by reproducing its install step in a clean venv and running the full acceptance suite against that clean install with the exact environment compose sets. Rob must run `docker compose up -d` once on a host with Docker. |
| Hosted Supabase | **not run** | Supabase is managed PostgreSQL. The full PostgreSQL pipeline (schema creation, boolean handling, placeholders, row types, the real order flow) was verified against a real PostgreSQL 18.6 server here, so the engine is proven — but Rob's actual Supabase project, its connection string and its network access still need one live run. |
| Production MCP connectors (bol.com, PostNL, Klaviyo, Exact Online) | **not run** | these need Rob's real accounts and API keys. See `docs/MCP-CONNECTORS.md`. |
| Real customer data | **not loaded** | the client data repository contains master data, not a customer/order export. The synthetic seed stands in until Rob provides his export — the loaders already upsert, so his data replaces the seed in place. |
| Real sell prices | **not available** | the catalogue in the repository has no prices (they live in FiveX / `Mastersheet.xlsx`). Orders therefore carry `price_eur = 0` and the system **refuses to queue an offer** for such an order — it raises a high-risk `price_missing` approval instead. This is a deliberate safety stop, not a defect. |

---

## Layout

```
wiseq-hermes/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── src/wiseq/
│   ├── config.py          # env-driven settings, no hardcoded secrets
│   ├── db/
│   │   ├── schema.py      # 18 tables, portable SQL
│   │   └── db.py          # SQLite + PostgreSQL behind one DSN
│   ├── domain/
│   │   ├── models.py      # orders, tariffs, rules, statuses
│   │   └── shipping.py    # the deterministic shipping engine
│   ├── ingest/
│   │   ├── loaders.py     # real client CSV -> DB
│   │   └── prices.py      # sell-price import (FiveX / Mastersheet)
│   ├── agents/            # school_orders, bundles, purchase_intel,
│   │                      # reviews, assortment, base (audit+approval)
│   ├── connectors/mail.py # test-mail-only dispatcher
│   ├── orchestrator.py    # one-call operations
│   ├── seed.py            # synthetic history
│   └── api.py             # FastAPI surface
├── scripts/
│   ├── demo_for_rob.py    # the client-facing walkthrough (7 steps)
│   ├── demo_end_to_end.py # 11-step operating demo
│   ├── api_smoke.sh       # 19-check acceptance suite
│   ├── verify_all.sh      # 11-step verification sweep
│   ├── audit_public_site.py # dated audit of the live storefront
│   ├── smtp_catcher.py    # local SMTP sink for testing
│   └── run_local.sh       # install + test + serve
├── tests/                 # 127 unit tests + 4 PostgreSQL tests
├── data/wiseq-repo/       # the client's own master data
├── data/public/           # dated snapshot of what the live shop says
└── docs/
    ├── HANDOVER.md        # the phased checklist for Rob
    ├── SHOW-ROB.md        # how to walk him through it
    ├── DATABASE.md        # the 18-table model
    ├── PUBLIC-DATA-FINDINGS.md # live site + public data, dated
    ├── MARKET-AND-PROCUREMENT-FINDINGS.md # competitors + Dutch school buying routes
    └── MCP-CONNECTORS.md  # every account and key needed
```

---

## The storefront is already agent-ready

WiseQ's own shop publishes a UCP/MCP endpoint at
`https://www.wiseq.nl/api/ucp/mcp` plus an agent brief at
`https://www.wiseq.nl/agents.md`. No credential needed.

This delivery already speaks to it: `src/wiseq/connectors/ucp.py` calls only
the read-only tools and blocks the write tools in code, so an agent can
never complete a payment unattended. Prices are cross-checked against the
public Shopify catalogue; the two independent sources agreed on every SKU
sampled. See `docs/PUBLIC-DATA-FINDINGS.md`.

---

## Where WiseQ actually sits

Measured against the Dutch market on 2026-10-29, from public sources only
(`docs/MARKET-AND-PROCUREMENT-FINDINGS.md` has the citations):

| | WiseQ | Nearest Dutch comparison |
|---|---|---|
| Wired school headset | EUR 18,95–19,95 | Rkop MAX from **EUR 9,89** at volume tier |
| Wireless school headset | EUR 27,95 | BuddyPhones POP Fun EUR 29,90 |
| Active noise cancelling | EUR 49,95 | BuddyPhones Cosmos+ EUR 79,90 |
| Warranty (website terms) | **1 year** | BuddyPhones 2 years (3 if registered) — but WiseQ's own Amazon listings and Rob's internal guide both say **2 years**, so the website is the stale one |

WiseQ is mid-market, and the school-grade wired segment is roughly half
its price. The differentiator therefore cannot be unit price — it is the
service package: staffel pricing, a free proefexemplaar, invoice terms,
delivery to the school address, and Dutch-language klassenset sizing.

Two findings worth correcting before they go into an offer:

- **There is no flat 15% school discount on the live site.** It publishes
  *staffelprijzen* (volume tiers), visible only after business registration.
  The only 10–15% figures on WiseQ pages are the attrition allowance for
  shared headsets, which is a sizing input, not a discount.
- **The Scamadviser "Very Likely Unsafe" flag is one flag, not two.**
  WebshopChecker's "1 external report" *is* that same Scamadviser entry.
  WebshopChecker's own data is reassuring (AI risk score 0/100, zero
  community reports, domain 7 years old), and the Scamadviser page itself
  says the data is over 30 days old. The fix is a fresh scan plus an
  answering `info@wiseq.nl` — not a reputation crisis.

---

## What Rob still has to do

See `docs/HANDOVER.md` for the full checklist. In short:

1. Run `docker compose up -d` on a host with Docker (one command).
2. Point `WISEQ_REPO_DIR` at his copy of the client data repo.
3. Create the Supabase project and paste the DSN into `.env`.
4. Provide the MCP credentials listed in `docs/MCP-CONNECTORS.md`.
5. Replace the synthetic seed with his real export via `POST /ingest`.
6. Decide the 5 unresolved shipping categories and the 88 live products
   that are not yet in the master catalogue.
7. Supply the **staffel price list** — it is the one price set the system
   genuinely cannot obtain, because the live site hides it behind B2B
   registration.
8. Confirm what the school discount actually is (staffel tiers, not a flat
   15%) and decide whether the warranty moves from 1 year to 2.
9. Change `WISEQ_TEST_RECIPIENT` away from the test mailbox only when he is
   ready for mail to leave the system.

---

## Licence

MIT. All components are open source.