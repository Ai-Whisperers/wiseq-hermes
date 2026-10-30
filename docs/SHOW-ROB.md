# Ready to Show Rob — The Walkthrough

**Date:** 2026-10-29
**One command, no credentials, no Docker, no network.**

```bash
cd wiseq-hermes
WISEQ_REPO_DIR=./data/wiseq-repo .venv/bin/python scripts/demo_for_rob.py
```

Runs in ~3 seconds and prints the whole story. It is also verification step
**4b**, so it cannot silently rot — if it breaks, the build goes red.

---

## What Rob sees on screen

| # | Section | The point | Numbers |
|---|---|---|---|
| 1 | **Your catalogue, loaded from your own files** | "we're using your data, not mock-ups" | 114 components, 25 bundles, 139 products, 15 shipping rules, 30 tariffs, 80 keywords, 25/25 bundles resolved, 5.8% EAN coverage |
| 2 | **A school emails us** | the input is verbatim Dutch, exactly as schools write it | "Wij willen graag **10x** de MagSafe draadloze oplader en **2x** de 45W GaN snellader…" |
| 3 | **We understood it** | no human needed to read the email | 2 lines resolved: SKU 231 ×10 (LVB), SKU 117 ×2 (PostNL) |
| 3b | **The catalogue ships without prices — so we get them** | shows the honest gap *and* the fix | 139 products with no price → live Shopify mirror → 230 fetched, 139 priced, 0 unresolved, 88 reported as not-in-catalogue |
| 4 | **We priced it against your own tariffs** | real numbers from `verzendtarieven.csv` | subtotal EUR 233.40, 0% *placeholder* discount (no flat discount is published), +EUR 5.84 shipping = **EUR 239.24** |
| 5 | **And then we asked a human** | the safety model, in plain words | offer `draft`, `requires_human_send: True`, 4 pending approvals, nothing sent |
| 6 | **Review requests** | Dutch copy, human-sent, test mailbox only | "Beste De Zon, Bedankt voor uw vertrouwen in WiseQ…" → `weissvanderpol@gmail.com` |
| 7 | **Purchase intelligence** | restock suggestions, not auto-orders | 6-month rolling average over 183 days |
| 8+ | **Class sets, warranty, strike watch, low-stock guard, integration backlog** | the operating rules, live | WiseQ's own published sizing table; 1 vs 2 year warranty contradiction; 93% on-time norm; 46 low-stock articles |
| last | **What WiseQ still has to decide** | the honest close: every open decision, named, with what we do meanwhile | 8 open decisions, each with its source and its fallback |

The last line printed is the one to leave on screen:

> Every number above came from WiseQ's own master files.
> No credential was used. No message left the test mailbox.
> No order was placed, no price was changed, nothing was sent.

**One line on that screen is ours, not Rob's, and the demo says so.**
The school-discount line is flagged in the output as a PLACEHOLDER, and it
reads **0%** — WiseQ publishes *staffelprijzen* (volume tiers), not a flat
discount, and no percentage appears in the operating manual or the
2026-10-28 transcript.

The demo also ends with a section that lists **every decision still open**
— the staffel ladder, the EAN export, the warranty, the five shipping
categories, the 88 products outside the master model, the five samples,
the EUR 2.95 fee and the stock price raise. For each one it says what we
did in the meantime (held at zero, flagged, asked a human) and where the
answer has to come from. That section exists so Rob is never left
assuming the system is finished: it is finished on the rules WiseQ has
published, and waiting on the rules only Rob can publish.

If Rob asks "so where are my school prices?", the honest answer is: *"your
staffel tiers live inside your own Shopify app — the SamitaWS registration
form — so we cannot scrape them. Export them and we will load them."* That
moment is worth having in the demo rather than hiding: it shows the system
does not invent business rules it cannot source, and it points Rob at the
one export we actually need from him.

---

## The three things worth pausing on

### 1. It reads Dutch the way Dutch is actually written

The order arrives as `10x MagSafe draadloze oplader`. The catalogue calls
it `Draadloze Oplader - Geschikt Voor MagSafe - 1 Meter - Wit`.

A substring match can never connect those two. Token scoring does. The
demo shows both strings side by side so Rob sees the problem, not just the
answer.

### 2. It refuses to guess on shipping

Every line is framed to a real carrier and rate from the client's own
tariff sheet — and the 5 categories the client's own sheet marks
unconfirmed are held at `needs_confirmation` instead of being invented.
Watch for that in the demo output: *"10 validated, 5 need confirmation."*

### 3. It stops before anything consequential

The offer is built, priced, and **queued** — with `requires_human_send:
True` and a pending approval. Nothing is sent, no price is changed, no
order is placed. The demo says so out loud at every step.

---

## If Rob wants to poke at it himself

The API is running alongside the demo:

```bash
curl http://localhost:8000/metrics          # counts and quality KPIs
curl http://localhost:8000/bundle-spine     # bundle integrity report
curl http://localhost:8000/approvals        # the human decision queue
curl http://localhost:8000/prices/gaps      # what's still unpriced
```

And the acceptance suite proves the whole thing end to end:

```bash
./scripts/verify_all.sh      # all steps green
```

---

## The demo in a single sentence

> "Your catalogue, your tariffs, your shipping rules — we read a school
> email the way your customer actually writes it, we price it from your own
> sheet, and then we ask a human before anything leaves the building."

---

## What the demo does *not* do, and why you should say so

Say these before Rob asks:

1. **Prices are demo values.** The demo imports `231 → 19.95` and
   `117 → 14.42` to make the flow visible. Real prices come from FiveX /
   Mastersheet via the same import. The demo labels this as step 3b.
2. **No MCP connector is live.** bol.com, PostNL, Klaviyo, Exact Online and
   Google Ads all need Rob's accounts. The demo runs entirely on the
   client's own files, which is the point — the operating rules are the
   hard part and they are proven independently of the credentials.
3. **Docker has not been run here.** No daemon in this build container. The
   image was validated by reproducing its install in a clean venv and
   running the full acceptance suite against it. First run on Rob's host:
   `docker compose up -d`.
4. **The synthetic data is synthetic on purpose.** 6 schools, 24 orders,
   40 listings exist so every flow has something to chew on. Rob's real
   bol.com export replaces them in place — every loader upserts.
5. **Some figures are transcript-derived, not system-derived.** Revenue
   (~EUR 1.5M), ~300 bol.com listings, ~7,000 subscribers and the "178%
   Belgium lift" come from the 2026-10-28 TurboScribe transcript. The repo
   has `data/CLAIMS-LEDGER.md` for exactly this — check it before putting
   any of it in a deck. The system-derived numbers (catalogue counts, EAN
   coverage, shipping rates, bundle spine) are computed live and are safe.
