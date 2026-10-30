# WiseQ × Hermes — everything built so far

**Repository:** `https://github.com/Ai-Whisperers/wiseq-hermes` (public, MIT)
**Final SHA:** `7eeae4e` — clean tree, local and remote identical, CI + Gitleaks green
**Verified:** 2026-10-30
**Prepared for:** Iván — to show Rob Nyari

---

## 1. What this actually is

A **portable, open-source operations replica** for WiseQ, built to demonstrate
what Hermes agents, MCP connectors and tools can automate in a real Dutch
e-commerce business.

It is **not** a production system and it is **not** a clone of WiseQ's
back office. It is a working proof: the business rules come from WiseQ's own
operating manual, the data comes from WiseQ's own master files and live
storefront, and every number in the demo is reproducible from those sources.

Three rules shaped every decision:

1. **Never invent a business rule.** If the manual is silent, the agent returns
   `NEEDS_CONFIRMATION` or `CASE_BY_CASE`. It never guesses.
2. **Never write a missing price as zero.** A missing price blocks the offer and
   asks a human.
3. **Never let a consequential action happen without a human approval.**

---

## 2. The shape of the system

```
                         ┌──────────────────────────────────┐
                         │        Hermes Agent Layer        │
                         │  one agent per business decision │
                         └──────────────────────────────────┘
   school_orders  bundles  class_set_sizing  warranty_policy
   stock_price_guard  strike_monitor  reviews  purchase_intel
   assortment  decisions_owed  integration_catalogue
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼─────┐   ┌──────▼──────┐   ┌─────▼──────┐
   │ Ingest   │   │  Connectors │   │    API     │
   │ loaders  │   │ Shopify UCP │   │ FastAPI +  │
   │ prices   │   │ mail        │   │ RBAC       │
   └────┬─────┘   └──────┬──────┘   └─────┬──────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
              ┌──────────▼───────────┐
              │   Data layer (db/)  │
              │  SQLite + PostgreSQL │
              └──────────────────────┘
```

**11 agents.** Each owns one business decision and returns a typed result plus
the evidence behind it. `decisions_owed` is the special one: it aggregates
everything that only a human can settle.

**35 source modules, 38 test modules, 19,585 lines** of Python across
`src/`, `tests/` and `scripts/`.

### Why agents and not services

The business logic lives in agent classes with a shared base, so the same
decision can be reached from the API, a cron job, a script or a test without
duplication. Connectors are thin adapters over live HTTP. There is no separate
"business logic service" to deploy — the whole thing is one package.

---

## 3. The data — what is real and what is verified

### From WiseQ's own files (never committed; mounted at `data/wiseq-repo/`)

| Source | What it produced |
| :--- | :--- |
| Master catalogue | **114 components**, **25 bundles** → **139 modelled products** |
| Bundle spine | **25/25 bundles fully resolved**, 0 broken |
| EAN registry | 8 EANs (5.8% coverage — the rest is missing from the export) |
| Shipping rules | 15 (10 validated, **5 need confirmation**) |
| Tariffs | 30 |
| SEO keywords | 80 |
| Operating manual + transcripts | the business rules, quoted in the agents |

### From the live storefront (Shopify)

| Fact | Value |
| :--- | :--- |
| Live product records | **230** |
| Priced + skued variants | **227** |
| Variants outside the master model | **88** (grouped into **29 product-family decisions**) |
| Sample variants (EUR 10–20) | **5** (blocked from every offer) |
| EAN barcodes exposed | **none** — the storefront has no barcode field |

### From the live Universal Commerce Protocol endpoint

| Fact | Value |
| :--- | :--- |
| Profile | `https://www.wiseq.nl/.well-known/ucp` (byte-identical to `/.well-known/ucp.json`) |
| UCP version | `2026-08-25` |
| MCP protocol version | `2025-06-18` — accepted by the live server |
| Published tools | 6 read tools covered by the connector, 7 write tools intentionally blocked |
| Capability drift status | **ALIGNED** (automatic detection, `scripts/discover_ucp.py`) |
| SKUs scanned | **139 resolved, 0 not found, 0 failed** |
| Price parity vs Shopify | **139 MATCH, 0 MISMATCH, 0 UNUSABLE** |

That last row is the strongest verification in the project: every one of the
139 sell prices the live commerce endpoint reports was independently compared
against the catalogue price and matched exactly — including all **23 genuine
bundle SKUs** such as `111+216`. It is a permanent gate
(`scripts/check_ucp_parity.py`), wired into `scripts/verify_all.sh` as step 10
and into CI with committed snapshots so it runs offline too.

### The public-site audit

**95 live pages** crawled, including **45 policy/content pages**. The audit
finds **11 minor technical issues across 11 pages** — and every issue type
now carries concrete remediation text, so the report is actionable rather than
a list of complaints.

---

## 4. What the agents actually do

### `school_orders` — the headline capability
Reads a Dutch school order email the way schools actually write it
("Wij willen graag 10x de MagSafe draadloze oplader en 2x de 45W GaN
snellader…"), extracts quantities and SKUs, matches them against the catalogue
and the tariffs, and produces a priced offer. Nothing is sent — the offer
becomes an **approval**.

### `class_set_sizing`
Computes how many units a class needs, with **exact arithmetic** (no float
multiplication, so `100 * 1.10` is `110`, not `110.00000000000001`), and
applies **one** non-overlapping allowance — a table buffer and an attrition
allowance are never stacked.

### `warranty_policy`
Distinguishes replacement from paid physical-damage repair. It also detects
the **live warranty contradiction** (see §6) and refuses to guess.

### `stock_price_guard`
The manual says "ik geloof" — "I believe" — about a 10% stock-price raise.
That is not a confirmed rule, so it ships as a **labelled placeholder**: the
guard recommends, a human approves, no live price is touched.

### `strike_monitor`
Watches the live WiseQ strike feed and escalates to a human rather than
acting on it.

### `decisions_owed` — everything only Rob can decide
One consolidated surface. Currently **51 decisions**, **35 of them blocking**:

| Kind | Count | Blocks |
| :--- | ---: | :--- |
| Catalogue families | 29 | any offer touching those product lines |
| Missing master sheets | 16 | the affected SKUs |
| Shipping rules | 5 | quotes for those categories |
| Warranty policy | 1 | every warranty answer |

Exposed at `GET /decisions-owed`, in the demo, and in the handover.

---

## 5. The safety model

### RBAC with rotating tokens

`src/wiseq/api_rbac.py` implements roles (`readonly`, `operator`,
`integrator`, `admin`) with explicit scopes. Tokens are stored **hashed**,
with issuance, rotation, revocation and expiry. Revocation is immediate.

### Fail-closed remote access

| Caller | Read | Write |
| :--- | :--- | :--- |
| loopback | allowed | needs a token |
| remote | needs a token | always needs a token |
| remote, no token configured | **refused** | **refused** |

"No token configured" most often means "nobody set it up yet", so the default
is refusal rather than openness. Verified live: unauthenticated remote read →
**HTTP 401**, unauthenticated remote write → **HTTP 401**.

### The approval gate

Orders, invoices, refunds, external messages, accounting writes, strike
escalation and price changes all go through the `approvals` table and are
idempotent — re-running an agent never creates a duplicate approval.

> **A real regression was found and fixed here.** RBAC commit `4f3cb65`
> accidentally moved `decided_by` off the `ApprovalIn` model onto a different
> model, which broke `POST /approvals/<id>` with HTTP 500 — the central
> human gate, for every caller. It is fixed (`74718e1`), the decision reason is
> now persisted to `audit_log`, and `tests/test_api_approval_decision.py`
> covers it with 8 tests. The regression test was **proven to catch the
> original defect** by reintroducing it (5 failures) before the fix was
> restored.

### Other invariants
- Test mail goes **only** to `weissvanderpol@gmail.com`.
- No credential is in source, docs or any commit. The pre-commit hook scans
  staged files; Gitleaks scans the full history in CI.
- The whole test suite is **hermetic** — a fix made this session means the
  result no longer depends on whether the operator happened to export a
  `WISEQ_API_TOKEN`. Proven by running the suite with a deliberately hostile
  ambient token.

---

## 6. What is NOT settled — the honest part

These are real and unresolved. None of them is hidden in the demo.

### The warranty contradiction (three sources, two answers)
- General terms: **one year**
- Nine school-facing and collection pages: **two years** (one of them even
  includes physical damage)
- Amazon/internal material: **two years**

WiseQ's own site currently contradicts itself. The agent reads the rule from
the manual, surfaces the conflict through `GET /policy/warranty` and the demo,
and never picks a side silently. **Rob must decide.**

### Reputation claims (not verified, not repeated as fact)
- ScamAdviser: score 0, "Very Likely Unsafe" — but that signal comes from
  WebshopChecker, and WebshopChecker's only external report is that same
  ScamAdviser signal. It is one source, not two.
- Trustpilot: 25 reviews, displayed 4.4/5, embedded TrustScore 4.5. One review
  mentions address errors and an unanswered `info@wiseq.nl`. Direct access is
  HTTP 403 from a datacentre IP, so the fetch is classified `UNREACHABLE`
  rather than "agreed".
- The claims ledger holds 60 claims including stale entries.

### Deliberately not implemented
- **No flat 15% school discount.** The claim was false. 10–15% is annual
  breakage/attrition. The discount field is 0, flagged as a placeholder, and
  a nonzero value additionally requires `WISEQ_SCHOOL_DISCOUNT_CONFIRMED=true`.
- **Staffel (volume) pricing** — not public; must come from Sami B2B.
- **Bol.com counts, Thuiswinkel status, Edu-V register** — bot-walled or
  cookie-walled; unverified, so not asserted.
- **The EUR 2.95 / EUR 3.57 order fee** — the storefront encodes it as an
  ordinary product, and the threshold explanation differs between pages. Held
  as an order-level rule, never as a product.

---

## 7. What Rob must supply

| # | Item | Blocks |
| ---: | :--- | :--- |
| 1 | Staffel price ladder from Sami B2B | volume quotes |
| 2 | EAN barcode export | barcode-fulfilment flows |
| 3 | The 16 missing master sheets of 21 | 16 SKUs |
| 4 | Final warranty-policy decision | every warranty answer |
| 5 | 5 shipping-category rulings | quotes for those categories |
| 6 | 29 catalogue-family decisions | offers touching those lines |
| 7 | Ruling on the 5 sample variants | whether they can ever be sold |
| 8 | Supabase project + credentials | hosted production DB |
| 9 | Production MCP credentials/accounts | live MCP integrations |
| 10 | SMTP production settings | real outbound mail |

---

## 8. Deployment shape

### Docker (the delivery boundary)
`docker-compose.yml` runs the API, the scheduler, MailHog and an optional
PostgreSQL. `Dockerfile` installs non-editable on purpose.

> **Honest limitation:** the Docker path is **YAML-validated and CI-simulated
> only**. This environment has the Docker CLI but **no daemon or socket**, no
> Compose plugin and no Podman. It has never been executed. The local Python
> path is what was actually exercised, on both Linux and Windows.

### Database
One dialect-aware data layer (`src/wiseq/db/`) — SQLite for tests and local
runs, PostgreSQL for production (Supabase). No SQLite `PRAGMA`, no hardcoded
DSNs. The schema and ERD are in `docs/DATABASE.md`.

### Scheduler
Durable recurring jobs with **heartbeats, persistent per-job state and stale-job
detection** — a stopped worker is reported as stopped, not presented as
healthy stale status. 23 dedicated tests.

---

## 9. Verification — what was actually run

| Environment | Result |
| :--- | :--- |
| Linux + PostgreSQL 18.6 | **586 passed, 0 skipped** |
| Linux + SQLite only | 582 passed, 4 skipped (PostgreSQL-only tests) |
| **Windows 11 (ivan-desktop)** | **581 passed, 5 skipped, 0 failed** |
| `scripts/verify_all.sh` | **all 14 steps green** |
| Clean-room install from the archive | 586 passed, 0 skipped |
| CI (pinned SHAs) | green on `7eeae4e` |
| Gitleaks (full history) | green on `7eeae4e` |

Two portability bugs were found by actually running on Windows rather than
by inspection:

1. **The install-warning test** invoked a POSIX `bash` probe and failed on
   Windows. Now platform-guarded with a stated reason.
2. **The handover-figure tests** skipped on a fresh clone because the page
   audit JSON was gitignored. A **trimmed snapshot is now committed**
   (`data/public/public-page-audit-snapshot.json`, 111 KB for 95 pages), and
   the handover's "11 affected pages" figure is now *verified against live
   data by a test* rather than being a number in prose that could drift.

A third defect was found by the fresh-clone rehearsal itself: the test suite
was **not hermetic** — an inherited `WISEQ_API_TOKEN` made 11 write tests
fail with 401. Fixed, and pinned by `tests/test_suite_hermeticity.py`.

---

## 10. How to show it to Rob — right now

### On ivan-desktop (Windows 11) — already set up and running

| What | Where |
| :--- | :--- |
| Repositories | `C:\hermes\work\wiseq-hermes` (at `7eeae4e`) |
| Client master data | `C:\hermes\work\wiseq-hermes\data\wiseq-repo` |
| Virtualenv | `C:\hermes\work\wiseq-hermes\.venv` |
| **Live API** | `http://100.105.54.119:8010/docs` — running as the scheduled task `WiseQHermesAPI` |
| Token | `C:\hermes\work\wiseq-hermes\.wiseq-token` (paste into **Authorize**) |
| Demo output | `C:\hermes\work\demo.txt` (431 lines, exit code 0) |
| Operator guide | `docs/WINDOWS-RUN.md` |

**Two double-click launchers:**

- `scripts\demo_windows.bat` — installs, runs the tests, then runs the full
  demo. **This is the main thing to show Rob.**
- `scripts\start_api_windows.bat` — starts the API on the Tailscale address so
  the interactive docs can be clicked through.

The API is bound to the Tailscale address only (`100.105.54.119`), not
`0.0.0.0`, so it is reachable across the tailnet and not from the internet.

> **Note on the port:** WiseQ uses **8010** because port 8000 on that machine
> is already used by Ivan's Sazon app. The Sazon process was left running and
> untouched.

### The demo's seven steps
1. Your catalogue, loaded from your own files (114 components → 25 bundles)
2. A school emails us — the real Dutch text
3. We understood it (no human needed to read the email)
4. We priced it against your own tariffs
5. And then we asked a human (nothing was sent)
6. Review requests, drafted in Dutch, for a human to send
7. Purchase intelligence (6-month rolling average)

Then the handover: the 8 decisions only Rob can make, each with what it
blocks.

---

## 11. Where the system actually stands with WiseQ

The honest assessment: **WiseQ's storefront is already agent-ready.**

- It exposes a **working Universal Commerce Protocol endpoint** with a
  published capability profile, and the connector negotiates with it cleanly.
- Every one of its 139 catalogue sell prices **matches** what the commerce
  endpoint reports, exactly.
- Its operating manual is detailed enough to drive a class-set-sizing agent,
  a warranty agent, a stock-price guard and a strike monitor without
  guessing.
- Its own website contradicts itself on warranty, and its public trust signals
  are thin — but **both of those are its own decision to make, not a
  technical blocker.**

What WiseQ does not have is the operational export layer: staffel pricing, EAN
barcodes, the 16 missing master sheets, and a settled warranty policy. Those
are the inputs this replica is designed to receive the moment they exist.

The replacement path is deterministic: when Rob's exports arrive, they replace
or augment the synthetic fixtures through the same ingest layer, and the same
tests and parity gate run against them. Nothing in the architecture needs to
change.

---

## 12. Repository map

```
src/wiseq/
  agents/          11 business-decision agents
  connectors/      Shopify, UCP/MCP, mail
  ingest/          master-sheet loaders, price import, storefront sync
  db/              dialect-aware schema + accessors
  domain/          models, shipping rules
  api.py           FastAPI surface (32 routes)
  api_rbac.py      roles, scopes, rotating token registry
  scheduler.py     durable jobs, heartbeats, stale detection
  orchestrator.py  wiring + recurring jobs
scripts/           setup, verification (14 steps), Rob demo, audits, parity
tests/             586 tests
docs/              HANDOVER, DATABASE, MCP-CONNECTORS, PUBLIC-DATA-FINDINGS,
                   MARKET-AND-PROCUREMENT-FINDINGS, SHOW-ROB, STATUS, WINDOWS-RUN
data/wiseq-repo/   MOUNTED, NEVER COMMITTED — WiseQ's own master data
```

---

## 13. The three sentences to say to Rob

1. **"This is your business, running on your own files."** Every number comes
   from WiseQ's master sheets and live storefront — 114 components, 25 bundles,
   139 products, all 139 prices matching your live commerce endpoint exactly.
2. **"It knows when to stop."** It reads a school order, prices it against
   your tariffs, and asks a human before anything is sent — because the
   decisions that matter are yours, and I've listed all 51 of them.
3. **"The open questions are business questions, not technical ones."**
   Warranty period, staffel pricing, EANs, 16 master sheets, five shipping
   categories, 29 product lines. The system is ready for them the moment you
   decide them.
