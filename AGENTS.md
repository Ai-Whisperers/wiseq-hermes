# AGENTS.md — WiseQ Hermes

Agent entry point for this repository. Read this before changing anything.

## What this repo is

A portable, open-source **operations replica** for WiseQ (Dutch kids'
technology e-commerce). It demonstrates what Hermes agents, MCP connectors
and tools can automate: school order parsing, class-set sizing, shipping
decisions, warranty handling, strike monitoring, stock-price guarding,
catalogue synchronisation and purchase intelligence.

It runs from a single directory, on Docker, against PostgreSQL (Supabase
in production, SQLite for local tests).

It is a **replica and a proof**, not a production system. The business
rules come from WiseQ's own operating manual; the production data comes
from Rob's exports.

## Layout

| Path | Role |
| :--- | :--- |
| `src/wiseq/` | The package. `agents/` holds one agent per business decision. |
| `src/wiseq/db/` | Dialect-aware data layer (SQLite + PostgreSQL). |
| `src/wiseq/ingest/` | Loaders for the client's master sheets and live prices. |
| `src/wiseq/connectors/` | Live public connectors (Shopify, UCP/MCP, mail). |
| `src/wiseq/api.py` | FastAPI surface. |
| `src/wiseq/scheduler.py` | Durable recurring jobs. |
| `scripts/` | Setup, verification, the Rob-facing demo, the public audit. |
| `tests/` | 344 tests. |
| `docs/` | Handover, database model, MCP guide, public-data findings, status. |
| `data/wiseq-repo/` | **Mounted, never committed.** The client's own master data. |

## Hard rules

These are not style preferences. Breaking one produces a wrong business
answer, and the test suite is written to catch it.

1. **Never invent a business rule.** If the manual is silent, the agent
   returns `NEEDS_CONFIRMATION` or `CASE_BY_CASE` — never a guess.
2. **Never write a missing price as zero.** A zero sell price blocks the
   offer and asks a human.
3. **Never treat the 10–15% breakage figure as a discount.** It is annual
   attrition. There is no flat 15% school discount. A nonzero discount
   needs `WISEQ_SCHOOL_DISCOUNT_CONFIRMED=true` *and* an explicit value.
4. **Never let a consequential action happen without approval.** Orders,
   invoices, refunds, external messages, accounting writes, strike
   escalation and price changes all go through the approvals table.
5. **Never send test mail anywhere except `weissvanderpol@gmail.com`.**
6. **Never treat a remote API request as trusted.** Without
   `WISEQ_API_TOKEN`, remote access fails closed.
7. **Never put a credential in source, docs or a commit.** The pre-commit
   hook scans staged files; do not bypass it with `--no-verify`.

## Conventions

- **Editable install for development.** A copied install makes new
  source invisible and produces false 404s. `scripts/run_local.sh` does
  the right thing. Docker images install non-editable on purpose.
- **Use exact arithmetic for quantities and ceilings.** Float
  multiplication turns `100 * 1.10` into `110.00000000000001`.
- **One non-overlapping allowance.** When a table buffer and an attrition
  allowance both apply, pick one — never stack them.
- **The data layer must stay dialect-aware.** No SQLite `PRAGMA`, no
  hardcoded DSNs, no SQLite-only row handling.
- **Approvals must be idempotent.** Re-running an agent must not create
  duplicate approvals.

## Running things

```bash
# setup
bash scripts/run_local.sh

# the whole verification (11 steps)
WISEQ_REPO_DIR=./data/wiseq-repo ./scripts/verify_all.sh

# the demo you show Rob
WISEQ_REPO_DIR=./data/wiseq-repo .venv/bin/python scripts/demo_for_rob.py

# the recurring jobs
WISEQ_REPO_DIR=./data/wiseq-repo .venv/bin/python scripts/run_scheduler.py status
```

## Before you claim something works

Run `scripts/verify_all.sh` and read the output. A skipped PostgreSQL
suite is a **failure**, not a pass — the verifier says so explicitly.

## Handover

`docs/HANDOVER.md` lists the decisions only a human can make, and what
each one blocks. `docs/STATUS-2026-10-29.md` records what is verified
versus what is not.
