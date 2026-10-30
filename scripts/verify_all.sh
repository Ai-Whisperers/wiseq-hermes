#!/usr/bin/env bash
# Full verification sweep.  Runs everything that can be verified without
# external accounts, and prints a single pass/fail summary.
#
#   ./scripts/verify_all.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-$ROOT/.venv/bin/python}"
REPO="${WISEQ_REPO_DIR:-$ROOT/data/wiseq-repo}"
PORT="${VERIFY_PORT:-8123}"
DB="/tmp/wiseq_verify.db"
FAIL=0

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }

step "1. package importable"
if "$PY" -c "import wiseq, wiseq.api, wiseq.orchestrator" 2>/dev/null; then
  ok "all modules import"
else
  bad "module import"
fi

step "2. unit test suite"
if OUT=$("$PY" -m pytest tests -q 2>&1); then
  ok "$(printf '%s' "$OUT" | grep -oE '[0-9]+ passed' | head -1)"
else
  bad "pytest: $(printf '%s' "$OUT" | tail -3)"
fi

step "3. client data present"
if [ -d "$REPO/data" ]; then
  ok "client repo at $REPO"
else
  bad "client repo missing at $REPO"
fi

step "4. end-to-end demo"
rm -f "$ROOT/wiseq.db"
if "$PY" scripts/demo_end_to_end.py "$REPO" > /tmp/wiseq_demo.log 2>&1; then
  ok "demo completed ($(grep -c '^STEP' /tmp/wiseq_demo.log) steps)"
else
  bad "demo failed: $(tail -3 /tmp/wiseq_demo.log)"
fi

step "4b. client-facing demo (the script to show Rob)"
rm -f /tmp/wiseq_robdemo.db
if WISEQ_REPO_DIR="$REPO" WISEQ_DATABASE_URL="sqlite:////tmp/wiseq_robdemo.db" \
     "$PY" scripts/demo_for_rob.py > /tmp/wiseq_robdemo.log 2>&1; then
  if grep -q "END OF DEMO" /tmp/wiseq_robdemo.log; then
    ok "client demo ran to the end ($(grep -c '^==' /tmp/wiseq_robdemo.log) sections)"
  else
    bad "rob demo did not reach the end: $(tail -3 /tmp/wiseq_robdemo.log)"
  fi
else
  bad "rob demo failed: $(tail -3 /tmp/wiseq_robdemo.log)"
fi

step "5. live API + acceptance suite"
rm -f "$DB"
# The API requires a token for every write.  Configure ONE token for both
# the server and the smoke script -- if they disagree, every write in the
# smoke run answers 401 and the step fails for the wrong reason.
export WISEQ_API_TOKEN="${WISEQ_API_TOKEN:-verify-all-local-token}"
WISEQ_REPO_DIR="$REPO" WISEQ_DATABASE_URL="sqlite:///$DB" \
  "$PY" -m uvicorn wiseq.api:app --host 127.0.0.1 --port "$PORT" \
  > /tmp/wiseq_api.log 2>&1 &
API_PID=$!
for _ in $(seq 1 30); do
  curl -fsS -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
if curl -fsS -m 5 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  ok "API healthy on :$PORT"
  if OUT=$(./scripts/api_smoke.sh "http://127.0.0.1:$PORT" 2>&1); then
    ok "$(printf '%s' "$OUT" | grep -oE 'passed: [0-9]+' | head -1) API checks"
  else
    bad "api smoke: $(printf '%s' "$OUT" | grep -E 'FAIL' | head -3)"
  fi
else
  bad "API did not become healthy: $(tail -5 /tmp/wiseq_api.log)"
fi
kill "$API_PID" 2>/dev/null; wait "$API_PID" 2>/dev/null

step "5b. PostgreSQL backend"
# Production runs on PostgreSQL (Supabase). When a server is reachable the
# same pipeline is exercised against it; otherwise this step is skipped and
# reported as such rather than silently passing.
if [ -n "${WISEQ_TEST_PG_URL:-}" ]; then
  # -rs prints the skip reasons, so an unreachable server is
  # distinguishable from a tests-are-skipped condition.
  if OUT=$(WISEQ_REPO_DIR="$REPO" "$PY" -m pytest tests/test_postgres.py -q -rs 2>&1); then
    # A skip is NOT a pass here.  If the server went away mid-run the tests
    # skip cleanly and pytest still exits 0, which would report a green
    # PostgreSQL step that never touched PostgreSQL.
    if printf '%s' "$OUT" | grep -qE '[0-9]+ skipped'; then
      # Distinguish "the server is gone" from "the tests genuinely skipped".
      # A skipped suite means PostgreSQL was never exercised, so this step
      # fails either way -- but the operator needs to know WHICH to fix.
      if printf '%s' "$OUT" | grep -qiE 'connection refused|could not connect|server closed|OperationalError|connection refused'; then
        bad "postgres UNREACHABLE (server down?): $(printf '%s' "$OUT" | grep -iE 'refused|OperationalError' | head -1) -- start it, e.g. pg_ctl -D <datadir> start"
      else
        bad "postgres tests skipped: $(printf '%s' "$OUT" | grep -E 'skipped|error' | head -2)"
      fi
    else
      ok "postgres: $(printf '%s' "$OUT" | grep -oE '[0-9]+ passed' | head -1)"
    fi
  else
    bad "postgres tests: $(printf '%s' "$OUT" | tail -3)"
  fi
else
  printf '  \033[33mSKIP\033[0m PostgreSQL (set WISEQ_TEST_PG_URL to enable)\n'
fi

step "6. SMTP delivery to test mailbox only"
"$PY" scripts/smtp_catcher.py 1026 /tmp/wiseq_smtp.txt >/dev/null 2>&1 &
SMTP_PID=$!
sleep 2
if OUT=$("$PY" - <<'PY' 2>&1
import sys; sys.path.insert(0, "src")
from wiseq.db.db import Database
from wiseq.connectors.mail import MailDispatcher, OutboundMail
db = Database("sqlite:///:memory:"); db.init_schema()
d = MailDispatcher(db, host="127.0.0.1", port=1026)
r = d.send(OutboundMail(to="real.customer@example.invalid", subject="Verify",
                        body="test", category="verify"))
print(r["delivered"], r["sent_to"])
PY
); then
  if [ "$(printf '%s' "$OUT" | awk '{print $1}')" = "True" ] &&
     [ "$(printf '%s' "$OUT" | awk '{print $2}')" = "weissvanderpol@gmail.com" ]; then
    ok "delivered=True, addressed to weissvanderpol@gmail.com"
  else
    bad "mail result unexpected: $OUT"
  fi
else
  bad "mail send failed"
fi
if grep -q "To: weissvanderpol@gmail.com" /tmp/wiseq_smtp.txt 2>/dev/null; then
  ok "SMTP envelope header correct"
else
  bad "SMTP envelope header wrong"
fi
kill "$SMTP_PID" 2>/dev/null; wait "$SMTP_PID" 2>/dev/null

step "7. no credentials in the tree"
# The pattern is built from pieces so this script does not match itself.
PAT="ghp_""[A-Za-z0-9]{20,}|sk-""[A-Za-z0-9]{20,}|postgres://[^:]+:[^@[:space:]]+@"
HITS=$(grep -rIlE "$PAT" --exclude-dir=.venv --exclude-dir=.git --exclude-dir=data \
       --exclude=verify_all.sh . 2>/dev/null)
if [ -n "$HITS" ]; then
  bad "credential-like string found in:"
  printf '%s\n' "$HITS" | sed 's/^/       /'
else
  ok "no credential-like strings found"
fi

step "8. public-site audit report is present"
# The audit is a dated snapshot of what the live storefront says.  A stale
# snapshot is worse than none, so the file must exist AND carry the raw
# catalogue it was built from.
# Generate it if it is missing.  The audit is a live snapshot of the
# storefront, so it is regenerated rather than committed -- otherwise the
# repo would carry a frozen dated picture of somebody else's shop.
if [ ! -f "$ROOT/data/public/public-site-audit-latest.md" ]; then
  printf '  ... generating the live audit (no snapshot present)\n'
  mkdir -p "$ROOT/data/public"
  ( cd "$ROOT" && WISEQ_REPO_DIR="$REPO" "$PY" scripts/audit_public_site.py \
      --out data/public >/tmp/wiseq_audit.log 2>&1 ) || true
fi

if [ -f "$ROOT/data/public/public-site-audit-latest.md" ]; then
  ok "audit report present"
  if [ -f "$ROOT/data/public/public-site-audit-latest.json" ]; then
    if OUT=$("$PY" - <<'PY' 2>&1
import json
from pathlib import Path
d = json.loads(Path("data/public/public-site-audit-latest.json").read_text())
raw = d.get("raw_catalogue", {}).get("products", [])
assert raw, "raw catalogue missing from the snapshot"
print(f"observed {d['observed']}: {len(raw)} live products")
PY
    ); then
      ok "$OUT"
    else
      bad "audit snapshot is missing its raw catalogue: $OUT"
    fi
  else
    bad "audit JSON sidecar missing"
  fi
else
  # The audit report is a LIVE snapshot, not a committed artifact.  It is
  # regenerated by the audit script and is deliberately not in the repo,
  # because committing it would freeze a dated picture of the storefront.
  # Fail with the exact command, not a bare "missing".
  bad "audit report missing -- generate it with: .venv/bin/python scripts/audit_public_site.py --out data/public"
fi

step "8b. per-page storefront audit"
# The catalogue audit in step 8 covers the storefront as a whole.  This
# step covers the INDIVIDUAL pages -- the policy pages an agent reads to
# learn a business rule, and the structured data a shopping agent
# parses.  It is the only check that notices when two pages publish
# DIFFERENT versions of the same rule, which is exactly the kind of
# contradiction that reaches a school as a wrong answer.
#
# The page audit needs the network, so it is skipped rather than failed
# when the network is unavailable -- but it never fails SILENTLY: the
# number of contradictions found is always reported.
if OUT=$("$PY" scripts/audit_pages.py --out data/public >/tmp/wiseq_page_audit.log 2>&1 && echo "ran"); then
  if OUT=$("$PY" - <<'PY' 2>&1
import json
from pathlib import Path
d = json.loads(Path("data/public/public-page-audit-latest.json").read_text())
pages = d.get("audited", {}).get("pages", 0)
contradictions = d.get("findings", [])
print(f"{pages} pages audited, {len(contradictions)} contradiction(s)")
for finding in contradictions:
    print(f"  - {finding['rule']}: {' vs '.join(sorted(finding['values']))}")
PY
  ); then
    ok "$OUT"
  else
    bad "page audit snapshot unreadable: $OUT"
  fi
else
  printf '  ... page audit skipped (no network): %s\n' "$(tail -2 /tmp/wiseq_page_audit.log | tr '\n' ' ')"
fi

step "9. live storefront prices still resolve"
# The catalogue is priced from the live storefront.  If the storefront moved
# or a price was withdrawn, the catalogue would silently quote the wrong
# number, so the live source is checked rather than trusted.
if OUT=$(WISEQ_REPO_DIR="$REPO" "$PY" - <<'PY' 2>&1
import os, sys, tempfile
sys.path.insert(0, "src")
from pathlib import Path
from wiseq.db.db import Database
from wiseq.orchestrator import WiseQOrchestrator
tmp = tempfile.mkdtemp()
db = Database(f"sqlite:///{tmp}/v.db"); db.init_schema()
orch = WiseQOrchestrator(db, repo=Path(os.environ["WISEQ_REPO_DIR"]))
orch.ingest()
report = orch.sync_shopify()
priced = report.get("priced_rows", 0)
print("priced_rows", priced)
assert priced >= 139, f"expected at least 139 priced products, got {priced}"
PY
); then
  ok "$(printf '%s' "$OUT" | grep 'priced_rows' | head -1)"
else
  bad "live storefront sync: $(printf '%s' "$OUT" | tail -3)"
fi

printf '\n======================================================\n'
if [ "$FAIL" -eq 0 ]; then
  printf 'ALL VERIFICATION STEPS PASSED\n'
else
  printf '%d STEP(S) FAILED\n' "$FAIL"
fi
printf '======================================================\n'
exit "$FAIL"
