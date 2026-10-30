# Docker verification — what was actually executed

**Status: VERIFIED on a real Docker daemon.**

This document records a real `docker build` + `docker compose up` execution,
not a YAML lint. Every claim below is backed by command output captured on
**2026-10-30**.

---

## Where it ran

| | |
|---|---|
| Host | `ai-whisperers` peer, Tailscale `100.69.193.50` |
| Docker Engine | 29.9.2 |
| Docker Compose | v5.6.1 |
| Disk | 332 GB free |
| Image | `wiseq/hermes:latest` — 278 MB (67.3 MB compressed) |
| Source | the shipped `wiseq-hermes.tar.gz`, unpacked clean on the host |

The original build container had the Docker **CLI but no daemon**. A fleet peer
did have a working daemon, so the stack was shipped there and run for real.

---

## What was proved

### 1. The image builds

```
$ docker compose build
 Image wiseq/hermes:latest Built
```

16 build steps, no errors. The image is non-editable (`pip install .`), so
the built artifact is exactly what ships.

### 2. The stack starts and becomes healthy

```
$ docker compose up -d
$ docker compose ps
NAME              SERVICE    STATUS
wiseq-hermes      wiseq      Up (healthy)
wiseq-scheduler   scheduler  Up (healthy)
wiseq-mailhog     mailhog    Up
```

Three services: API, scheduler, MailHog. Compose creates the network and the
`wiseq-data` / `mailhog-data` volumes automatically.

### 3. The API is healthy and fail-closed

```
$ curl -s http://127.0.0.1:8000/health
{"status":"ok","service":"wiseq-hermes","school_discount_pct":0.0,
 "school_discount_is_placeholder":true,
 "auth":{"token_configured":true,"writes_require_token":true,
         "open_paths":["/health","/metrics"], ...}}
```

The discount placeholder guard is **active** inside the container: it reports
`school_discount_is_placeholder: true` and `school_discount_pct: 0.0`. The
0 % school discount is not silently promoted to a real rule.

### 4. The Rob demo runs inside the container

```
$ docker compose exec -T wiseq bash -lc 'python scripts/demo_for_rob.py'
RC=0
509 lines
```

Exit code 0, 509 lines — the complete demonstration, rendered from the
container's own database, with the client's own master data mounted
read-only at `/data/wiseq-repo`.

### 5. The scheduler runs every business job

```
$ docker compose run --rm scheduler python scripts/run_scheduler.py once
{"job": "sync_shopify",  "status": "ok"}
{"job": "strike_check",   "status": "ok"}
{"job": "stock_guard",    "status": "ok"}
{"job": "review_drafts",  "status": "ok"}
{"job": "price_gaps",     "status": "ok"}
{"job": "decisions_owed", "status": "ok", "result": {"total": 51, "blocking": 35}}
```

All six jobs `ok`. `decisions_owed` reproduces the authoritative
**51 decisions / 35 blocking** inside the container.

> **Command note.** The scheduler service uses a shell-form entrypoint, so
> `docker compose run --rm scheduler once` **replaces** the whole command with
> the bare word `once` and fails with `executable file not found`. The full
> path is required:
> `docker compose run --rm scheduler python scripts/run_scheduler.py once`.

### 6. Test email goes only to `weissvanderpol@gmail.com`

A message was deliberately addressed to `someone-else@example.com` to prove
the routing override. MailHog received:

```json
{"To":[{"Mailbox":"weissvanderpol","Domain":"gmail.com"}],
 "Subject":["[WiseQ-test] WiseQ Docker SMTP path test"],
 "Body":"Container SMTP path check.\n\n---\nintended recipient
          (reference only, NOT delivered): someone-else@example.com"}
```

- `sent_to: weissvanderpol@gmail.com` — the **only** recipient.
- The subject carries the `[WiseQ-test]` prefix.
- The original address survives only as a clearly-labelled reference line
  in the body, never as a recipient.
- MailHog is the local sink, so no real email ever left the host.

### 7. The API acceptance suite passes inside the container

```
$ docker compose exec -T wiseq bash -lc 'bash scripts/api_smoke.sh http://127.0.0.1:8000'
passed: 37   failed: 0
```

This found and fixed a real portability bug — see below.

---

## The bug the Docker run found

`scripts/api_smoke.sh` called an **absolute path** to the original
developer's virtualenv:

```bash
/opt/data/profiles/ivan/cache/scratch/wiseq-hermes/.venv/bin/python - <<'PY'
```

Five call sites. The script already had a correct `$PYBIN` resolution block
(the project venv, then `python3`, then `python`) — those five sites simply
never used it.

**Consequence:** on any other machine the assertions did not run. In Docker
the suite reported `passed: 31  failed: 3` and the human-approval-gate check
was silently **skipped** — the most important assertion in the suite, absent,
with a green-looking summary.

**Fix:** every call now uses `"$PYBIN"`. After the fix, in Docker:
`passed: 37  failed: 0`, and the approval gate assertion really executes.

`tests/test_script_portability.py` (5 tests) now prevents any operational
script from embedding a developer-specific path again. Reintroducing the
defect produces 3 failures.

---

## Reproducing it yourself

```bash
cp .env.example .env      # then set a real WISEQ_API_TOKEN
docker compose build
docker compose up -d
docker compose exec -T wiseq bash -lc 'python scripts/demo_for_rob.py'
docker compose exec -T wiseq bash -lc 'bash scripts/api_smoke.sh http://127.0.0.1:8000'
```

MailHog UI: <http://localhost:8025> — every generated message appears there.

## What is still not verified

- **Hosted Supabase.** The compose file includes a `postgres` profile for
  Supabase-style DSNs, but no hosted Supabase project has been connected.
- **Production MCP connectors.** bol.com, PostNL, Klaviyo and Exact Online
  need Rob's accounts and API keys.
- **Docker on Ivan's Windows desktop.** `ivan-desktop` has no Docker
  installed. The API there runs natively via Task Scheduler on port 8010.
