# MCP connectors and credentials

Status of every external integration: what it is for, what credential it
needs, who provides it, and whether the system works without it.

**No credential value appears in this repository.** Every secret is
`[REDACTED]` in `.env.example` and is expected to live in Rob's `.env` or
his own secret store.

---

## Summary

| # | System | Credential | Provider | Blocks what | Works without it? |
|---|---|---|---|---|---|
| 0 | **WiseQ storefront UCP/MCP** | **none — already public** | WiseQ | nothing; it is live | yes — it is already live |
| 1 | Supabase | DB password | Rob | PostgreSQL runtime | yes — SQLite |
| 2 | bol.com Selling API | client id + secret + refresh token | Rob | live listing/order read | yes — seeded mirror |
| 3 | PostNL | API key + organisation number | Rob | shipment label creation | yes — rates from your CSV |
| 4 | Klaviyo | private API key + revision | Rob | subscriber/segment sync | yes — segment logic works offline |
| 5 | Exact Online | app id + secret + division | Rob | invoicing schools | yes — PDF offer draft |
| 6 | Google Ads | customer id + OAuth | Rob | keyword bidding | yes — volumes already loaded |
| 7 | Google Search Console | service-account JSON | Rob | ranking feedback loop | yes |
| 8 | bol.com back office | Playwright session | Rob | UI-level actions | yes |
| 9 | SMTP relay | host/port/user/pass | Rob | sending real mail | yes — MailHog |
| 10 | Hermes MCP servers | — | AI Whisperers + Rob's approval | agent autonomy | yes |

**The system is fully demonstrable with zero credentials.** That is
deliberate: the operating rules are the hard part, and they are encoded and
tested independently of the accounts.

---

## 0. WiseQ storefront UCP/MCP — already live, no credential needed

This one needs nothing from Rob, so it is worth reading before any of the
others.

The WiseQ shop already publishes a complete agent-facing commerce interface.
It was verified working on **2026-10-29**.

| Surface | URL | What it is |
|---|---|---|
| Agent brief | `https://www.wiseq.nl/agents.md` | the storefront describing itself to an AI agent |
| UCP discovery | `https://www.wiseq.nl/.well-known/ucp` | protocol version and capabilities |
| MCP endpoint | `https://www.wiseq.nl/api/ucp/mcp` | JSON-RPC 2.0, 13 tools |
| Catalogue JSON | `https://www.wiseq.nl/products.json?limit=250` | the whole storefront, public |
| Agentic sitemap | `https://www.wiseq.nl/sitemap_agentic_discovery.xml` | points at `agents.md` |

### What the MCP endpoint exposes

13 tools, of which six are read-only and ten are write operations:

- read-only: `search_catalog`, `lookup_catalog`, `get_product`,
  `get_cart`, `get_checkout`, `get_order`;
- write: `create_checkout`, `update_checkout`, `complete_checkout`,
  `cancel_checkout`, `create_cart`, `update_cart`, `cancel_cart`.

### How this system uses it

`src/wiseq/connectors/ucp.py` calls **only the read-only tools**. The write
tools are blocked in code by an explicit allow list, not by convention:

```python
client.call_tool("create_checkout", ...)   # raises UCPError
```

That is deliberate and matches what WiseQ's own `agents.md` says: *"Agents
mogen een betaling niet zelfstandig afronden"* — agents must not complete a
payment on their own.

### Two independent price sources, cross-checked

| Source | How | Credentials |
|---|---|---|
| Shopify mirror | `GET /products.json` | none |
| UCP/MCP | `search_catalog` / `get_product` | none |

Both are public and both are read. The system does not assume they agree:
`POST /prices/sync-ucp` reports any disagreement in `price_mismatches`
rather than silently picking one. On 2026-10-29 a 12-SKU cross-check
returned **12 resolved, 0 mismatches**.

### Two gotchas worth knowing

1. **The profile must be a JSON document.** `meta.ucp-agent.profile` has to
   point at a JSON file. Pointing it at an HTML page fails with
   `Invalid content type`; pointing it at JSON without a version fails with
   `Missing ucp version`. `/.well-known/ucp.json` satisfies both.
2. **The endpoint rate-limits.** A full 139-SKU scan without spacing trips
   it and the storefront asks the caller to wait ~45 minutes. The connector
   therefore keeps a minimum gap between calls and, when it is throttled,
   **stops and reports `rate_limited: true`** rather than recording the
   remaining SKUs as missing. A throttled run must never look like an empty
   catalogue.

Amounts come back in **minor units** (cents). The connector converts them
before anything else sees them — a price quoted to a buyer in cents is a
business error.

---

## 1. Supabase

```ini
WISEQ_DATABASE_URL=postgresql://postgres.PROJECT_REF:[REDACTED]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

Use the **session pooler** (port 5432) for the app. Use the **direct**
connection (port 5432 on `db.PROJECT_REF.supabase.co`) for migrations, or
just let the app create the schema on boot.

Rob provides: project reference, database password.

## 2. bol.com Selling API

```ini
BOL_CLIENT_ID=[REDACTED]
BOL_CLIENT_SECRET=[REDACTED]
BOL_REFRESH_TOKEN=[REDACTED]
```

Register the app at bol.com → Settings → Selling API. Authorise it against
your seller account to receive the refresh token.

Agents that need it:
- **assortment** — pull live listings, title length, description length,
  image dimensions, and current keyword coverage. This is the agent that
  finds the content problems in the operating manual.
- **school_orders** — learn real SKU demand from order history.
- **reviews** — see which delivered orders have not been reviewed yet.

Rob provides: client id, client secret, and the refresh token after
authorising the app.

## 3. PostNL

```ini
POSTNL_API_KEY=[REDACTED]
POSTNL_ORGANISATION_NUMBER=[REDACTED]
```

Customer Portal → Settings → API credentials.

Agent: turns a framed order into a label. Note that **rate selection is
already implemented and does not need this** — the rates come from your
own `verzendtarieven.csv`, which is loaded and passing tests. The API is
only needed to create the actual shipment.

Rob provides: API key, organisation number.

## 4. Klaviyo

```ini
KLAVIYO_PRIVATE_API_KEY=[REDACTED]
KLAVIYO_REVISION=2024-10-15
```

Settings → API → Create API key.

Agent: pulls subscriber segments so purchase intelligence can be reported
per segment rather than in aggregate.

Rob provides: private API key.

## 5. Exact Online

```ini
EXACT_ONLINE_APP_ID=[REDACTED]
EXACT_ONLINE_SECRET=[REDACTED]
EXACT_ONLINE_DIVISION=[REDACTED]
```

Apps → Create own app → grant sales invoice + customer read/write.

Agent: creates the invoice for a school order once the offer is approved,
replacing the PDF draft.

Rob provides: app id, secret, and the **division number** (which legal
entity invoices — ask your accountant).

## 6 & 7. Google Ads + Search Console

```ini
GOOGLE_ADS_CUSTOMER_ID=[REDACTED]
GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google-sa.json
```

The service-account JSON must be added to `searchconsole` and to the Ads
account as a developer.

Agent: closes the SEO loop — the 80 search-volume keywords are already in
the `search_keywords` table; this lets the agent check whether the content
changes it recommends actually moved the needle.

Rob provides: customer id, and the service-account JSON file.

## 8. bol.com back office (Playwright)

Optional. Only if you want an agent to operate the bol.com UI directly
(fix a listing image, update a price). Higher risk, higher value.

Rob provides: an authenticated session, and his explicit approval that the
agent may act in the back office.

## 9. SMTP relay

```ini
SMTP_HOST=[REDACTED]
SMTP_PORT=587
SMTP_USER=[REDACTED]
SMTP_PASSWORD=[REDACTED]
```

For testing: `SMTP_HOST=mailhog`, `SMTP_PORT=1025` (the compose service).

Rob provides: the relay credentials.

## 10. Hermes MCP servers

These are installed in Hermes, not in this repository. Each one is a decision
about what the agents may touch.

| Server | Install | Gives agents |
|---|---|---|
| MCP Postgres | `hermes mcp install postgres` | direct SQL against Supabase |
| MCP Filesystem | `hermes mcp install filesystem` | read/export CSVs |
| MCP Fetch | `hermes mcp install fetch` | fetch product pages |
| Playwright | `hermes mcp install playwright` | browser automation |

Rob approves which of these are installed and what directories/tables they
may reach.

---

## Secret handling

- Secrets live in `.env` (git-ignored) or in the environment.
- `.env.example` contains **only** `[REDACTED]` placeholders.
- The `outbox` table records what was sent and to whom, so the audit trail
  never contains a credential.
- The `audit_log` table records agent actions, not payloads containing
  credentials.
- No credential is ever passed to an LLM prompt or written to a log line.

## Order to connect them

1. **Supabase** — the data has to live somewhere durable.
2. **bol.com** — it is the largest source of truth and unlocks the
   assortment and school-order agents against real data.
3. **PostNL** — needed once real orders are being shipped.
4. **Klaviyo** — needed once the newsletter is being segmented.
5. **Exact Online** — needed once invoices replace PDF offers.
6. **Google** — last; it is the most optional and the least urgent.
