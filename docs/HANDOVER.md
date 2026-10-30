# Handover checklist for Rob

Ordered by what blocks what. Everything in "AI Whisperers does" is already
built and tested. Everything else needs an account, a credential, or a human
decision that only you can make.

Legend: **[W]** = needs a human. **[A]** = we can automate once credentials exist.

---

## Phase 1 — Get it running (about 15 minutes)

**1.1 [W] Run the stack on a machine with Docker**

```bash
cd wiseq-hermes
cp .env.example .env
docker compose up -d
curl http://localhost:8000/health     # -> {"status":"ok","service":"wiseq-hermes"}
```

> We could not execute this ourselves: our build container has the Docker
> client but no Docker daemon. Everything else about the image was validated
> (clean-environment install reproduced, full acceptance suite re-run against
> that install), but the `docker build` and `docker compose up` themselves
> are unrun.

**1.2 [W] Check the MailHog UI**

Open `http://localhost:8025`. Every message the system produces appears
here, addressed to `weissvanderpol@gmail.com`. Nothing reaches a real
inbox while this is the only SMTP target.

**1.3 [W] Run the demo once**

```bash
docker compose exec wiseq python scripts/demo_end_to_end.py /data/wiseq-repo
```

You should see 11 steps: ingest (114 components / 25 bundles), bundle-spine
integrity (25/25 resolved), an inbound school email turned into a EUR
198.98 order with a flagged 0% discount placeholder (the staffel ladder
   is not publicly syncable) and 100% of lines shipping-framed, an
approval-gated offer, a purchase-intelligence report, a Dutch review
draft, and a bol.com content scan.

---

## Phase 2 — Point it at your own data

**2.1 [W] Put the client data repo where the container can read it**

```bash
git clone --depth 1 https://github.com/Ai-Whisperers/wiseq-ai-onboarding.git data/wiseq-repo
```

`docker-compose.yml` already mounts `./data/wiseq-repo` read-only at
`/data/wiseq-repo`.

**2.2 [W] Load it**

```bash
curl -X POST http://localhost:8000/ingest
```

Idempotent — run it every time you get a new export.

---

## Phase 3 — Real database (Supabase)

**3.1 [W] Create the project**

At <https://supabase.com/dashboard> → New project. Pick the region closest
to you (EU). The free tier is enough for this workload.

**3.2 [W] Collect two values**

| Where | What you get |
|---|---|
| Project → Settings → Database → Connection string → **Session pooler** | `postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-eu-central-1.pooler.supabase.com:5432/postgres` |
| Project → Settings → Database → **Reset password** | the same password, for direct migrations |

**3.3 [W] Put the DSN in `.env`**

```ini
WISEQ_DATABASE_URL=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

**3.4 [W] Apply the schema**

Either run `src/wiseq/db/schema.py`'s SQL in the Supabase SQL editor, or
start the stack with the DSN set — the app runs `init_schema()` on boot and
creates every table. Verify:

```bash
curl http://localhost:8000/metrics
```

**3.5 [W] Confirm persistence**

```bash
docker compose restart wiseq
curl http://localhost:8000/metrics    # counts must be unchanged
```

> **PostgreSQL is verified.** We started a real PostgreSQL 18.6 server in
> our build container and ran the whole pipeline against it: schema
> creation, ingestion of all client CSVs, the school-order flow, the
> approval gate, and the end-to-end demo. The demo produced *identical*
> metrics on PostgreSQL and SQLite (139 products, 25 bundles, 15 shipping
> rules, 30 tariffs, 25 orders, 65 order lines, 100% framing rate). We then
> read the rows back out of the database to confirm they persisted.
>
> That verification is reproducible on your machine:
>
> ```bash
> WISEQ_TEST_PG_URL=postgresql://postgres@127.0.0.1:5432/wiseq_test \
>   .venv/bin/python -m pytest tests/test_postgres.py -q
> ```
>
> What is still unverified is only the *hosted* part: your Supabase
> project's connection string, its network reachability, and its pooler
> behaviour. The engine underneath is proven.

---

## Phase 4 — MCP connectors (each needs your account)

The point of MCP here is to let agents reach the systems where the work
actually lives, without writing bespoke integration code. Each connector
below is what the agents need, and what only you can obtain.

### 4.1 bol.com — the shop

| Need | What for | Where to get it |
|---|---|---|
| Bol.com seller account | listing content, orders | you already have this |
| `BOL_CLIENT_ID` / `BOL_CLIENT_SECRET` | OAuth for the Selling API | bol.com → Selling API → app registration |
| Refresh token | long-lived access | same screen, after you authorise the app |

**Used by:** the assortment agent (read listings + scores, draft content
fixes), the school-order agent (read real order history to learn SKU
demand), the review agent (see which orders have not been reviewed).

**Status: not connected. Nothing in the demo depends on it** — the
assortment agent reads a seeded listing table that mirrors bol.com's
fields, so the behaviour is demonstrable before credentials exist.

### 4.2 PostNL — shipping

| Need | What for | Where to get it |
|---|---|---|
| `POSTNL_API_KEY` | label creation, shipment status | PostNL Customer Portal → API credentials |
| `POSTNL_ORGANISATION_NUMBER` | sender identification | on your account |

**Used by:** turning a framed order into real shipment labels.

**Status: not connected.** Shipping *rates* come from your own
`verzendtarieven.csv`, which is already loaded and working. Only label
creation needs the API.

### 4.3 Klaviyo — the newsletter (your ~7,000 subscribers)

| Need | What for | Where to get it |
|---|---|---|
| `KLAVIYO_PRIVATE_API_KEY` | list sync, segment pulls | Klaviyo → Settings → API → Create key |
| `KLAVIYO_REVISION` | API version header | currently `2024-10-15` |

**Used by:** segment-level purchase intelligence (your two bol.com accounts
behave differently — the content scan already scores them separately).

### 4.4 Exact Online — accounting

| Need | What for | Where to get it |
|---|---|---|
| `EXACT_ONLINE_APP_ID` / `EXACT_ONLINE_SECRET` | invoice creation | Exact Online → Apps → own app |
| Division number | which legal entity invoices | your accountant decides this |

**Used by:** invoicing schools instead of sending PDF offers.

**Status: not connected.** The offer agent currently produces a priced
document and stops there.

### 4.5 Google Ads / Search Console — SEO

| Need | What for | Where to get it |
|---|---|---|
| `GOOGLE_ADS_CUSTOMER_ID` | keyword bidding | Google Ads → Admin → linked accounts |
| OAuth service account JSON | Search Console | Google Cloud console → enable Search Console API |

**Used by:** turning the 80 loaded search-volume keywords into a ranked
content plan. The keyword data is already in the database.

### 4.6 Optional: MCP servers to install

If you want the agents to work through MCP rather than the built-in
connectors, these are the open-source servers worth adding:

| Server | Gives the agent | Notes |
|---|---|---|
| `mcp-server-postgres` | direct SQL against Supabase | lets an agent answer questions about the data without a bespoke API |
| `@modelcontextprotocol/server-filesystem` | read/write your exports folder | useful for importing new CSVs |
| `mcp-server-fetch` | fetch product pages | for content research |
| Playwright MCP | drive the bol.com back office | only if you want UI-level access |

Installing them is one command each in Hermes:

```
hermes mcp install <catalog-name>
```

We did not install these: each needs your decision about what the agents
should be allowed to touch.

---

## Phase 5 — Replace synthetic data with your real export

The seed data (6 schools, 24 historical orders, 40 bol.com listings) exists
so every flow has something to chew on. Your real data replaces it in place
because every loader upserts.

**5.1 [W] Export from bol.com and drop the CSVs into `data/exports/`.**

**5.2 [A] We write the importer.** We need to see the actual column headers
of your export to write the mapping. Either:

- attach the export and we map it, or
- give us the bol.com export schema and we write the loader blind.

**5.3 [W] Decide what stays synthetic.** We would keep the school list and
the review-request cadence synthetic until your data covers them.

**Also worth deciding:** the three shipping categories that are still
`NEEDS_CONFIRMATION` / `CASE_BY_CASE` with blank EANs — `2x Adapter ?`,
`Koptelefooncase`, `USB HUBS`, `Smartwatch`, `Tag`. These are the
"ungefrankeerde zendingen" problem in the operating manual: the system
correctly refuses to guess, so it needs a decision per category from you.

**5.4 [W] Supply the sell prices — this one blocks real offers.**

The catalogue in the repository has **no prices**; they live in FiveX and
`Mastersheet.xlsx`. So every ingested product currently has `price_eur = 0`,
and the system deliberately **refuses to queue an offer** for such an
order: the offer comes back as `status: "blocked_missing_price"` and a
high-risk `price_missing` approval is raised naming the affected SKUs.
That is a safety stop, not a bug — without it the system would happily
quote a school EUR 0 for the goods and only ask for shipping money.

Two ways to close it:

| Option | What you do | What happens |
|---|---|---|
| **A. Import the export** | export `sku_text, price_eur` from FiveX or the Mastersheet to CSV | `POST /prices/import` with the file — every matching SKU gets a real price and the `price_missing` block clears |
| **B. Paste into the DB** | nothing to build | `UPDATE products SET price_eur = 19.95, synthetic_price = 0 WHERE sku_text = '231';` |

**The import already exists** — you do not need us to build anything:

```bash
curl -X POST http://localhost:8000/prices/import \
  -H 'Content-Type: application/json' \
  -d "{\"path\": \"/data/exports/prices.csv\", \"source_name\": \"FiveX 2026-10-29\"}"
```

It accepts CSV or JSON, Dutch or English column names (`Artikelnummer` /
`Verkoopprijs` / `price_eur` / `prijs`), Dutch decimal commas (`19,95`),
currency prefixes (`EUR 19,95`) and headerless two-column files. SKUs that
are not in the catalogue come back in `not_in_catalogue`; rows whose price
cannot be read come back in `unresolved` — **nothing is ever written as
zero**, so a bad export can never silently produce a EUR 0 quote.

To see what is still missing:

```bash
curl http://localhost:8000/prices/gaps
```

That returns every product still carrying a synthetic price, which is the
checklist to hand back to whoever owns the price list.

Either way the `price_missing` approval clears and offers flow normally
through the approval gate.

---

## Phase 6 — Go live (only when you say so)

**6.1 [W] Change the test recipient**

```ini
WISEQ_TEST_RECIPIENT=your-real-operations-address
```

Until this changes, every message goes to `weissvanderpol@gmail.com`.

**6.2 [W] Set the real sender**

```ini
WISEQ_TEST_SENDER=orders@wiseq.nl
```

**6.3 [W] Real SMTP**

```ini
SMTP_HOST=smtp.your-provider.nl
SMTP_PORT=587
```

**6.4 [W] Point `SMTP_HOST` at a real relay.** MailHog is for testing only.

**6.5 [W] Flip the review-send switch.** `WISEQ_REVIEW_SEND_ENABLED` is
`false` in the code and the review agent only ever *drafts*. Changing this
is a deliberate decision, not a configuration accident.

**6.6 [W] Confirm the approval queue is being watched.** The `approvals`
table is the gate. If nobody reads `/approvals`, the system does nothing
that matters — which is exactly the intended behaviour, but it is not a
complete system on its own.

**6.7 Deciding an approval.** `POST /approvals/<id>` takes
`{"decision": "approved"|"rejected", "decided_by": "<name>",
"note": "<why>"}`. The `note` is written to the audit trail, so a
decision can be explained later; without it the decision is a status
with no reason attached. A second decision on an approval that was
already decided is refused with **409** — the first decision is the one
that counts, and it is not overwritten.

```bash
curl -X POST http://127.0.0.1:8099/approvals/<id> \
  -H "X-WiseQ-Token: $WISEQ_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"decision":"approved","decided_by":"rob","note":"price checked"}'
```

---

## Before anything goes live — read this

`docs/PUBLIC-DATA-FINDINGS.md` records what the live storefront and public
sources actually said on **2026-10-29**: the agent endpoints that already
work, the measured catalogue (230 live products, 88 of them not yet in the
master catalogue), the EUR 2.95 order rule, the sample-price discrepancy,
and the Scamadviser/Trustpilot signals that a prospect can see.

`docs/MARKET-AND-PROCUREMENT-FINDINGS.md` adds the competitive picture
(~57 KB, cited): where WiseQ sits against Rkop, JLab, BuddyPhones and JBL,
what Dutch school boards actually require, and which procurement portals
exist.

Six things there need a decision from you specifically:

1. **The five unresolved shipping categories** (`2x Adapter ?`,
   `Koptelefooncase`, `USB HUBS`, `Smartwatch`, `Tag`). A quote using them
   is not final until you decide how they ship.
2. **The 88 live sellable products** that are not in the master catalogue.
   They need master records, not just price rows.
3. **The sample-price inconsistency** — the catalogue prices four samples at
   EUR 10.00 while the page explains a EUR 7.05 product plus EUR 2.95
   shipping.
4. **Whether a school discount exists at all.** The site says staffel tiers
   visible after business registration. No 15% discount was found on any
   WiseQ page, and it is not in the 2026-10-28 transcript either. If 15% is
   real, it comes from an internal source we cannot see.
5. **Warranty length.** The site says 1 year; BuddyPhones gives 2 (3 if
   registered). Durability is WiseQ's headline claim, so a one-year
   warranty works against it.
6. **Whether to offer a verwerkersovereenkomst / DPA.** Dutch school
   boards ask for it as routine and it is not visible on the current pages.

---

## The fifteen things that are only yours to decide

1. Which of the five unresolved shipping categories get a rule, and what rate.
2. What the real school discount is — staffel tiers, and whether any flat
   percentage applies (see "Before anything goes live", item 4).
3. Which bol.com account (WiseQ NL / WiseQ Electronics) sets the tone for content.
4. Whether review requests are sent automatically after approval or batched.
5. Which school classes count as "same school" for discount purposes.
6. Whether invoices go through Exact Online or stay as PDF offers.
7. When the switch from the test mailbox to real sending happens.
8. Which real customer data fields are allowed into the agents' prompts.
9. **The warranty — now three conflicting public positions, not two.**
   Your general terms say **1 year** excluding accident and external
   damage. Your Amazon.nl listings and your own `Handleiding_opzet.txt`
   say **2 years**, excluding physical breakage. But your own school-ICT
   page now says **"2 jaar garantie, ook bij fysieke schade"** — two
   years *including* a chewed cable or a broken headband — and sells
   exactly that to schools. These cannot all be true. The school page is
   the one a school buyer reads, so it is the one most likely to be
   treated as operative. Please state one policy: term length, and
   whether physical damage is covered. Then align the terms page, the
   school page, the Amazon listings and the agent behaviour to it.
   (`docs/MARKET-AND-PROCUREMENT-FINDINGS.md` §2f.)
10. Whether to publish a verwerkersovereenkomst / DPA, and whether to
    register with Onderwijs Inkoop Groep / DAS.
11. Whether to chase the Scamadviser "Very Likely Unsafe" flag. It is a
    single stale flag (2026-08-21) that WebshopChecker simply echoes back,
    and WebshopChecker's own data showed no community reports — but the
    badge is visible to every first-time visitor. Confirming the
    Thuiswinkel Waarborg certificate is still current is the cheapest
    first step; it could not be checked from this environment.
12. Whether seller **1428598** (KvK 71702830) is still one of yours.
13. **What the school discount actually is, and where the ladder lives.**
    Correction to earlier notes: **"SamitaWS" is not a Dutch school
    procurement registry.** It is *your own* Shopify app — "Sami B2B
    Wholesale Pricing" by Samita — embedded on your B2B page as
    `{SamitaWSRegistrationForm:MTA0NTY=}`. Your staffelprijzen are
    configured inside that app, so they are visible only after a buyer
    registers, and they are **not** in the public Shopify catalogue, the
    repository, or the UCP/MCP feed. The system therefore cannot sync
    them and must treat the ladder as an operator-supplied table (it is
    currently a 0% placeholder with an explicit flag). Please export the
    real tiers from the app so they can be loaded, and confirm the tier
    boundaries and which models they combine across — your own class-set
    page says the staffels "gelden ook als je meerdere modellen in één
    order combineert", which the current model does not represent.
    (`docs/MARKET-AND-PROCUREMENT-FINDINGS.md` §2e.)

    **How to load them, once you have them.** Put the value in
    `WISEQ_SCHOOL_DISCOUNT_PCT` and set `WISEQ_SCHOOL_DISCOUNT_CONFIRMED=true`.
    Both are needed: the confirmation flag is separate on purpose, so that
    "someone typed a number into an env file" is never mistaken for "this
    number came from WiseQ". Until the confirmation flag is set, `/health`
    reports `school_discount_is_placeholder: true` and the demo labels the
    line as a placeholder. Note that `0` and `15` can never be confirmed —
    neither is a verified WiseQ rule.
14. **The 13 dB / 85 dB / 93 dB figures.** WiseQ's own agent brief says the
    Unbreakable attenuates ~13 dB **passively** and that the Kids ANC is
    the only ANC model, while several product listings and image
    filenames say "13dB noise cancelling". Also: the Unbreakable's volume
    limiter is 93 dB switchable to 85 dB, and the One/Junior limit at
    85 dB. Please confirm the intended positioning, because an agent
    that calls 13 dB a volume limit would repeat a wrong safe-listening
    claim to a school.
15. **Edu-V.** The Edu-V keurmerk needs a signed **intent declaration**
    plus a qualifying product, so it cannot simply be joined. Your status
    in the `edu-v.org/keurmerkregister` could not be retrieved from here
    (the register returned only a cookie shell) — so it is *unverified*,
    not absent. The live question is the **WiseTab**: if it is meant to
    carry the keurmerk, confirm it and the entry should be quotable; if
    not, no school-facing material should imply Edu-V coverage. Note also
    that SIVON's "Devices Ronde 11" specification is a **Chromebook** spec
    and covers none of your products, so it is not your qualification
    target. (`docs/MARKET-AND-PROCUREMENT-FINDINGS.md` §2h.) It
    trades as "WISEQ NL" with the same correspondence address, but it is
    a **different legal entity** from Wiseq B.V. (KvK 84801964), which
    owns seller 1357877. The public archive shows 1428598 with its own
    1,084 product reviews and 176 listings. If it is yours, its review
    base is a marketing asset nobody is currently counting; if it is not,
    its numbers must never appear in WiseQ materials. This is why the
    audit now keys every bol.com figure to its KvK number.
16. **Which warranty promise is operative.** Three public positions are
    live on the same storefront today: the legal pages and WiseQ's own
    `agents.md` say **1 year**; the Amazon listings and your internal
    manual say **2 years**; and the school-ICT page says **2 years,
    including physical damage** ("Kabel doorgebeten of hoofdband
    beschadigd? Ook dat valt onder de garantie"). The repair schedule
    from `Handleiding_opzet.txt` is now implemented
    (`src/wiseq/agents/warranty_policy.py`,
    `POST /school/warranty-decision`) — but it implements *your manual*,
    under which a physically broken Unbreakable at 4 months is a 50%
    discount case rather than a warranty case, because Unbreakable's
    physical-break warranty window is only 3 months. That contradicts
    the school page. Please decide which is operative, and align the
    terms page, the school page, the product listings and the agent
    behaviour to it.
17. **The class-set sizing table.** The quantity rule WiseQ publishes is
    now implemented (`POST /school/class-set-sizing`), but one point
    needs your confirmation: the table's own "+ 10%" buffer and the
    separate "10 tot 15% uitval per schooljaar" attrition allowance
    describe the same spares for shared use. The implementation treats
    the attrition allowance as **replacing** the table buffer when a
    school declares intensive shared use, rather than adding to it.
    Stacking them would quote roughly 25% spares where you publish
    10–15%. If you actually intend them to be cumulative, say so and it
    is a one-line change.

18. **The low-stock price raise size.** Your own setup guide says FiveX
    raises the price automatically when stock is 10 units or lower, and
    then hedges the amount: *"Ik geloof dat die prijsstijging 10% is"* —
    "I believe that price increase is 10%". Because the source itself is
    uncertain, the system ships **10% as a placeholder** and labels it as
    such in the API and the demo. The **threshold of 10 units is treated
    as fact** (the guide states it without hedging); only the percentage
    is a placeholder. Set `WISEQ_STOCK_PRICE_RAISE_PCT` to the real value
    to confirm it.

19. **The strike escalation thresholds.** The operating manual says at
    3 strikes you must be involved and a plan of action executed, and at
    5 strikes the whole assortment switches to VVB. Both are implemented
    literally (`GET /strikes`). Two things need your call: whether the
    threshold should count *consecutive* strikes or cumulative ones (the
    system counts cumulative), and whether the on-time norm is measured
    against the **promised** delivery date. The system currently uses a
    2-working-day proxy because the order model has no promised-date
    column — adding that column makes it exact.

20. **The low-stock threshold of 10 is often too late.** The guide says
    so itself: some articles sell 10 units a day, so the stock gap
    arrives before the threshold fires. The system therefore also
    reports **days of cover** and marks anything within 3 days as
    urgent. Your call: is 3 days the right urgency window, and should a
    fast-selling article get a higher threshold instead of the same 10?

21. **Which of the 31 researched integrations to build first.** The
    repository's `data/oss/` folder holds 31 curated open-source
    searches (428 projects) that nothing in the system read until now.
    `GET /integration-backlog` ranks them against what this replica does
    not yet do. The highest-scoring uncovered lanes are SEO auditing,
    generic marketplace APIs, Shopify tooling, accounting, workflow
    automation and a helpdesk. Nothing is installed -- this is your
    choice, not the system's.

22. **An API token for the deployment.** The API is not left open --
    remote access fails closed until `WISEQ_API_TOKEN` is set, and every
    write needs the token from anywhere, including localhost. Generate
    one with
    `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`
    and put it in `.env` before exposing the port beyond localhost. If
    you want a different scheme (per-user tokens, an OAuth provider in
    front of it, or a reverse proxy that handles auth), that is a
    design choice for you to make.

23. **How often the recurring jobs should run.** The shipped cadences
    are: catalogue sync hourly, strike check hourly, price-gap check
    every 6 hours, stock guard daily, review drafts daily. They are
    sensible defaults derived from the manual, not measured facts about
    your operation. Adjust the intervals in
    `WiseQOrchestrator.scheduler()` to match your actual rhythm -- and
    decide whether you want the loop running inside the container
    (`scripts/run_scheduler.py serve`) or driven by your own cron.

24. **What "on time" means when the order has no promised date.** Also
    connected to 19: an order that was never shipped is counted as NOT
    on time rather than excluded. That is deliberate — excluding
    unshipped orders would silently inflate the rate — but if bol.com's
    own calculation excludes them, your 93% norm and the system's number
    will not line up.

---

## Install editable, not copied

If you create the virtualenv by hand:

    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"      # note the -e

Without the `-e`, pip copies the package into site-packages. Any later
edit to `src/wiseq/` is then invisible to the running system: a newly
added API route keeps answering 404 while the test suite passes, because
the tests read `src/` directly. `scripts/run_local.sh` and the Dockerfile
already do the right thing; this is only for manual setup.

## A harmless warning you may see during install

If you install on a minimal Linux image, `pip` may print:

    bash: id: command not found
    bash: [: : integer expression expected

**This is harmless and you can ignore it.** It comes from the *shell
wrapper that launches the install* probing the current user with
`[ "$(id -u)" -eq 0 ]` in an environment where the `id` utility is not on
`PATH`. It is not emitted by this project: no script here calls `id` or
`whoami` (there is a regression test that enforces that). The install
finishes normally and every verification step passes afterwards.

If you want it gone, install with `--no-build-isolation`, or make sure
`coreutils` (which provides `id`) is on `PATH`.

---

## If the verifier says "postgres UNREACHABLE"

That means the PostgreSQL server is not running — not that the code is
broken. The verifier now tells the two situations apart, because a
skipped suite must never be allowed to pass as success.

Start the server and rerun:

```bash
export PATH=/tmp/pgbin/bin:$PATH
pg_ctl -D /path/to/pgdata -l /path/to/pg.log start
```

If the server keeps disappearing between sessions, the cluster is
sitting somewhere the OS reclaims (a tmpfs or a temp directory). Move
its data directory to persistent storage and point `pg_ctl -D` at the
new path.

## Support

- Business rules live in `src/wiseq/domain/shipping.py` and
  `src/wiseq/agents/` — each has a docstring explaining the client rule it
  implements and where the rule came from.
- Database shape: `src/wiseq/db/schema.py`.
- If a rule is wrong, it is almost always one of two things: the CSV in the
  client repo changed, or the rule is hardcoded where it should be in
  `config.py`. Both are a five-minute fix.

## The warranty: what the system applies, and what is still broken

The live storefront does not agree with itself about the warranty.
Checked across all 95 pages on 2026-10-30:

| Where | Years |
|---|---|
| `/agents.md`, `/pages/algemene-voorwaarden`, `/pages/veelgestelde-vragen` | 1 |
| 9 school-facing and collection pages | 2 |
| Your operating manual | 2 |
| Amazon / internal material | 2 |

**The system applies two years**, because that is what your operating
manual says. It does not read the warranty period off the storefront,
and it will not assemble a customer answer from whichever page a
retrieval happened to reach.

This is now data, not prose:
`wiseq.agents.warranty_policy.public_warranty_contradiction()` returns
the full breakdown, and `GET /policy/warranty` serves it over HTTP.

`warranty_answer_requires_confirmation()` returns `True` while the
pages disagree. Any agent that would state a warranty period to a
customer is expected to check it and route to a human.

**Only you can fix this.** It needs the general terms, the school
pages, the channel listings and the quote templates to say the same
thing. Until then, the system keeps saying so out loud rather than
quietly picking one.

## Everything that is still your decision

`GET /decisions-owed` (or `wiseq.agents.decisions_owed.DecisionsAgent`)
is the single list. As of 2026-10-30, against the live storefront:

| Kind | Count | What it blocks |
|---|---|---|
| shipping rules | 5 | framing any order in that category |
| catalogue lines | 29 lines / 88 variants | an offer including that line |
| policy contradictions | 1 | any customer-facing warranty statement |
| master sheets not exported | 16 | capabilities that depend on them |

The five shipping categories are `2x Adapter ?`, `Koptelefooncase`,
`USB HUBS`, `Smartwatch` and `Tag`.

Two of the catalogue decisions are different in kind and worth calling
out:

* **Samples.** Five storefront variants (EUR 10.00 to 20.00) are tagged
  `sample`. A non-zero price does not make a sample sellable -- that is
  a question of intent, not of price.
* **Newer lines.** The `Premium USB-C Kabel` line (6 variants, EUR
  11.95 to 13.95), the `USB Hub` line (6 variants) and the `WiseTab`
  line (4 variants) sell on the storefront but post-date the master
  catalogue. Whether they are in the master, or are a deliberate
  addition, is a business call.

The system blocks rather than guesses. It will not sell a product
because it has a price, and it will not quote a warranty period taken
from one page while another page disagrees.

---

## Live storefront technical findings (not blocking, but worth a look)

`scripts/audit_pages.py` fetched and read **95 live pages** on 2026-10-30.
Eleven pages carry a small technical defect, and none of them break the
system. They are listed here because they are cheap to fix and each one
is a small loss of traffic or of machine-readable information.

| Finding | Pages | What it costs |
|---|---|---|
| Missing meta description | 4 | The search snippet is assembled from whatever text happens to be nearby |
| Multiple `h1` | 4 | The page has no single stated subject for screen readers or crawlers |
| Missing `h1` | 2 | Same, in reverse -- the page never says what it is about |
| Missing canonical URL | 1 | `agents.md` can be ranked at more than one address |

The affected pages are `/collections/sample`, `/pages/algemene-voorwaarden`,
`/pages/e-book`, `/pages/later-betalen-bevestigd`,
`/pages/recommended-products`, `/pages/welk-snoer-oplaadkabels-quiz`,
four `/blogs/nieuws/...` articles, and `/agents.md`.

The full report, with the fix spelled out for each finding, is written by

```bash
.venv/bin/python scripts/audit_pages.py --out data/public
```

which produces `data/public/public-page-audit-latest.md`. The audit runs
as step 8b of `scripts/verify_all.sh`, so a regression here fails the
build rather than passing quietly.

Nothing here is a decision only you can make -- they are edits to your
theme and templates. The system does not need them fixed to run.
