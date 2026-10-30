#!/usr/bin/env bash
# Full API acceptance test against a live WiseQ API instance.
# Usage: ./scripts/api_smoke.sh [base_url]
set -uo pipefail

BASE="${1:-http://127.0.0.1:8099}"
PASS=0; FAIL=0; HIT_SEQ=0

# The API refuses writes without a token, and refuses remote reads.
# Every request in this script therefore sends one.
# The server's token comes from WISEQ_API_TOKEN.  When the script is run
# standalone against a server started with a different token, set the
# same value in the environment -- otherwise every write answers 401.
TOKEN="${WISEQ_API_TOKEN:-smoke-test-token}"
AUTH_HDR=(-H "X-WiseQ-Token: $TOKEN")

# Python interpreter used for JSON assertions.  Prefer the project venv so
# the same interpreter that runs the service parses the responses.
PYBIN="${PYBIN:-}"
if [ -z "$PYBIN" ]; then
  for cand in "$(dirname "$0")/../.venv/bin/python" "$(command -v python3)" \
              "$(command -v python)"; do
    if [ -n "$cand" ] && [ -x "$cand" ]; then PYBIN="$cand"; break; fi
  done
fi
PYBIN="${PYBIN:-python3}"

hit() {  # hit METHOD PATH EXPECTED_STATUS [JSON_BODY]
  local method="$1" path="$2" want="$3" body="${4:-}"
  local out status
  # Writes require an API token.  If one is configured in the environment
  # it is sent; if not, the smoke run sends one anyway so the write path
  # is exercised rather than skipped.
  if [ -n "$body" ]; then
    out=$(curl -s -m 30 -w '\n%{http_code}' -X "$method" "$BASE$path" \
          "${AUTH_HDR[@]}" -H 'Content-Type: application/json' -d "$body")
  else
    out=$(curl -s -m 30 -w '\n%{http_code}' -X "$method" "$BASE$path" \
          "${AUTH_HDR[@]}")
  fi
  status="${out##*$'\n'}"
  if [ "$status" = "$want" ]; then
    printf '  PASS  %-6s %-28s %s\n' "$method" "$path" "$status"
    PASS=$((PASS+1))
    HIT_SEQ=$((HIT_SEQ+1))
    printf '%s' "${out%$'\n'*}" > "/tmp/wq_resp_${HIT_SEQ}.json"
  else
    printf '  FAIL  %-6s %-28s got=%s want=%s\n' "$method" "$path" "$status" "$want"
    printf '        body: %s\n' "$(printf '%s' "${out%$'\n'*}" | head -c 300)"
    FAIL=$((FAIL+1))
  fi
}

echo "WiseQ API acceptance test against $BASE"
echo "======================================================"

echo "-- read endpoints --"
hit GET  "/health"                200
hit GET  "/metrics"               200
hit GET  "/bundle-spine"          200
hit GET  "/assortment"            200
hit GET  "/audit"                 200
hit GET  "/approvals"             200

# The school discount is NOT a verified WiseQ rule (the live site publishes
# volume tiers that live inside WiseQ's own Shopify app and cannot be
# synced).  /health must therefore report the placeholder state, or an
# operator would have no way to see that the demo's discount line is
# still an unverified placeholder.
HEALTH_BODY="$(curl -sS --max-time 20 "$BASE/health" "${AUTH_HDR[@]}" | head -c 2000)"
echo "-- class-set sizing + warranty --"
SIZING="$(curl -sS --max-time 20 -X POST "$BASE/school/class-set-sizing" "${AUTH_HDR[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"pupils":200,"use_model":"Gedeelde set per bouw (roulerend)","largest_group":120}')"
if printf '%s' "$SIZING" | grep -q '"total_quantity":132'; then
  printf '  PASS  %-28s %s\n' "class-set sizing table" "largest group + 10% = 132"
  PASS=$((PASS+1))
else
  printf '  FAIL  %-28s %s\n' "class-set sizing table" "unexpected: $SIZING"
  FAIL=$((FAIL+1))
fi

# An unrecognised use model must be refused, never guessed.
BADMODEL="$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -X POST \
  "$BASE/school/class-set-sizing" "${AUTH_HDR[@]}" -H 'Content-Type: application/json' \
  -d '{"pupils":30,"use_model":"gewoon een paar"}')"
if [ "$BADMODEL" = "422" ]; then
  printf '  PASS  %-28s %s\n' "unknown use model refused" "422, not a guess"
  PASS=$((PASS+1))
else
  printf '  FAIL  %-28s %s\n' "unknown use model refused" "got $BADMODEL"
  FAIL=$((FAIL+1))
fi

WARRANTY="$(curl -sS --max-time 20 -X POST "$BASE/school/warranty-decision" \
  "${AUTH_HDR[@]}" -H 'Content-Type: application/json' \
  -d '{"model":"WiseQ Unbreakable","months_used":4,"damage_type":"physical_break"}')"
if printf '%s' "$WARRANTY" | grep -q '"discount_pct":50'; then
  printf '  PASS  %-28s %s\n' "warranty policy applied" "3-6 months -> 50%"
  PASS=$((PASS+1))
else
  printf '  FAIL  %-28s %s\n' "warranty policy applied" "unexpected: $WARRANTY"
  FAIL=$((FAIL+1))
fi

if printf '%s' "$WARRANTY" | grep -q '"needs_approval":true'; then
  printf '  PASS  %-28s %s\n' "warranty needs approval" "human decision required"
  PASS=$((PASS+1))
else
  printf '  FAIL  %-28s %s\n' "warranty needs approval" "not flagged"
  FAIL=$((FAIL+1))
fi

echo "-- placeholder disclosure --"
if printf '%s' "$HEALTH_BODY" | grep -q '"school_discount_is_placeholder":true'; then
  printf '  PASS  %-28s %s\n' "discount flagged placeholder" "school_discount_is_placeholder=true"
  PASS=$((PASS+1))
else
  printf '  FAIL  %-28s %s\n' "discount flagged placeholder" "not reported by /health"
  FAIL=$((FAIL+1))
fi

echo "-- ingest (real client data) --"
hit POST "/ingest"                 200 '{}'

echo "-- price import (the catalogue ships without sell prices) --"
# Without prices the school pipeline correctly refuses to quote.  Import a
# few so the offer path can be exercised for real.
hit POST "/prices/import"          200 \
  '{"csv":"sku_text,price_eur\n231,19.95\n234,24.50\n117,14.42\n","source_name":"acceptance test"}'
hit GET  "/prices/gaps"            200

echo "-- live storefront sync (public catalogue mirror) --"
# wiseq.nl publishes /products.json.  This needs no credentials and writes
# nothing to the live store.  It is the fastest way to close the price gap.
# If the storefront is unreachable the check is skipped, not failed -- a
# network outage is not a defect in the system under test.
SYNC_OUT=$(curl -s -m 90 -w '\n%{http_code}' -X POST "$BASE/prices/sync-shopify" "${AUTH_HDR[@]}" \
  -H 'Content-Type: application/json' -d '{"load_into_db": true}')
SYNC_STATUS="${SYNC_OUT##*$'\n'}"
SYNC_BODY="${SYNC_OUT%$'\n'*}"
if [ "$SYNC_STATUS" = "200" ]; then
  HIT_SEQ=$((HIT_SEQ+1))
  printf '%s' "$SYNC_BODY" > "/tmp/wq_resp_${HIT_SEQ}.json"
  SYNC_PRICED=$(printf '%s' "$SYNC_BODY" | "$PYBIN" -c \
    "import json,sys;print(json.load(sys.stdin).get('priced_rows',0))")
  SYNC_UNRES=$(printf '%s' "$SYNC_BODY" | "$PYBIN" -c \
    "import json,sys;print(len(json.load(sys.stdin).get('unresolved',[])))")
  if [ "${SYNC_PRICED:-0}" -gt 0 ] && [ "${SYNC_UNRES:-1}" -eq 0 ]; then
    printf '  PASS  %-6s %-28s %s\n' "POST" "/prices/sync-shopify" "$SYNC_STATUS"
    printf '        priced %s rows, %s unresolved\n' "$SYNC_PRICED" "$SYNC_UNRES"
    PASS=$((PASS+1))
  else
    printf '  FAIL  %-6s %-28s priced=%s unresolved=%s\n' \
      "POST" "/prices/sync-shopify" "$SYNC_PRICED" "$SYNC_UNRES"
    FAIL=$((FAIL+1))
  fi
else
  printf '  SKIP  %-6s %-28s storefront unreachable (HTTP %s)\n' \
    "POST" "/prices/sync-shopify" "$SYNC_STATUS"
fi

echo "-- UCP/MCP storefront connector --"
# The storefront publishes its own UCP endpoint.  This check is read-only
# and tolerant: the storefront rate-limits, so a throttle is reported as a
# SKIP rather than a failure, but a real answer must agree with the Shopify
# mirror on price.
UCP_OUT=$(curl -s -m 90 -w '\n%{http_code}' -X POST "$BASE/prices/sync-ucp" "${AUTH_HDR[@]}" \
  -H 'Content-Type: application/json' -d '{"skus": ["231", "233", "331"], "load_into_db": false}')
UCP_STATUS="${UCP_OUT##*$'\n'}"
UCP_BODY="${UCP_OUT%$'\n'*}"
if [ "$UCP_STATUS" = "200" ]; then
  UCP_RL=$(printf '%s' "$UCP_BODY" | "$PYBIN" -c \
    "import json,sys;print(json.load(sys.stdin).get('rate_limited',False))")
  UCP_RES=$(printf '%s' "$UCP_BODY" | "$PYBIN" -c \
    "import json,sys;print(json.load(sys.stdin).get('resolved',0))")
  UCP_MM=$(printf '%s' "$UCP_BODY" | "$PYBIN" -c \
    "import json,sys;print(len(json.load(sys.stdin).get('price_mismatches',[])))")
  if [ "$UCP_RL" = "True" ]; then
    printf '  SKIP  %-6s %-28s storefront rate-limited\n' \
      "POST" "/prices/sync-ucp"
  elif [ "${UCP_RES:-0}" -gt 0 ] && [ "${UCP_MM:-1}" -eq 0 ]; then
    printf '  PASS  %-6s %-28s %s\n' "POST" "/prices/sync-ucp" "$UCP_STATUS"
    printf '        resolved %s skus, %s price mismatches vs shopify\n' "$UCP_RES" "$UCP_MM"
    PASS=$((PASS+1))
  else
    printf '  FAIL  %-6s %-28s resolved=%s mismatches=%s\n' \
      "POST" "/prices/sync-ucp" "$UCP_RES" "$UCP_MM"
    FAIL=$((FAIL+1))
  fi
else
  printf '  SKIP  %-6s %-28s endpoint unavailable (HTTP %s)\n' \
    "POST" "/prices/sync-ucp" "$UCP_STATUS"
fi

echo "-- school order from email --"
EMAIL_BODY=$(cat <<'JSON'
{"email":"info@basisschool-de-zon.test",
 "body":"Beste WiseQ team,\n\nWij willen graag 10x de MagSafe draadloze oplader en 2x de 45W GaN snellader bestellen voor onze bovenbouw.\n\nMet vriendelijke groet,\nBasisschool De Zon"}
JSON
)
hit POST "/school-orders"          200 "$EMAIL_BODY"

ORDER_NO=$("$PYBIN" - <<'PY'
import json, glob, os
best = ""
for f in glob.glob("/tmp/wq_resp_*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if isinstance(d, dict) and d.get("order_number"):
        best = d["order_number"]
print(best)
PY
)
echo "  ..order number: ${ORDER_NO:-<none>}"

# The order must contain resolved lines. A zero-line or zero-total order
# means the email parser or the catalogue matcher regressed, and a school
# order that quotes EUR 0 for goods must never be treated as a pass.
echo "-- order lines resolved --"
"$PYBIN" - <<'PY'
import json, glob, sys
best = {}
for f in glob.glob("/tmp/wq_resp_*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if isinstance(d, dict) and d.get("order_number"):
        best = d
lines = best.get("lines") or []
if not lines:
    print("  FAIL  order has no resolved lines")
    sys.exit(1)
unframed = [l for l in lines if l.get("framing_status") != "framed"]
print(f"  PASS  order has {len(lines)} resolved line(s)")
for l in lines:
    print(f"        - {l['sku']:>4}  x{l['quantity']:<4} "
          f"EUR {l['unit_price_eur']:.2f}  ship EUR {l['shipping_eur']:.2f} "
          f"[{l['carrier']}] {l['title'][:44]}")
if unframed:
    print(f"  FAIL  {len(unframed)} line(s) not framed")
    sys.exit(1)
print("  PASS  every line framed to a carrier")
PY
if [ $? -ne 0 ]; then FAIL=$((FAIL+1)); else PASS=$((PASS+2)); fi

echo "-- offer draft (approval gated) --"
hit POST "/school-orders/offer"    200 "{\"order_number\":\"${ORDER_NO}\"}"

echo "-- offer carries real goods value (not a shipping-only quote) --"
# A quote of EUR 0 for the goods is a business error: the catalogue ships
# without sell prices, so a missing price must surface as a block rather
# than silently produce a EUR 0 offer.
OFFER=$("$PYBIN" - <<'PY'
import json, glob
best = {}
for f in glob.glob("/tmp/wq_resp_*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if isinstance(d, dict) and "offer_number" in d:
        best = d
print(json.dumps(best))
PY
)
"$PYBIN" - <<'PY'
import json, glob, sys
best = {}
for f in glob.glob("/tmp/wq_resp_*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if isinstance(d, dict) and "offer_number" in d:
        best = d
if not best:
    print("  FAIL  no offer returned")
    sys.exit(1)
lines = best.get("lines") or []
goods = sum(float(l.get("line_total_eur") or 0) for l in lines)
total = float(best.get("total_eur") or 0)
status = best.get("status")
print(f"  PASS  offer {best.get('offer_number')} status={status} "
      f"goods EUR {goods:.2f} total EUR {total:.2f}")
if not lines:
    print("  FAIL  offer has no lines")
    sys.exit(1)
if goods <= 0:
    print("  FAIL  offer quotes EUR 0 for the goods")
    sys.exit(1)
if status == "blocked_missing_price":
    print("  FAIL  offer blocked on missing price after a price import")
    sys.exit(1)
PY
if [ $? -ne 0 ]; then FAIL=$((FAIL+1)); else PASS=$((PASS+2)); fi

echo "-- integration backlog --"
hit GET  "/integration-backlog"                  200
BACKLOG_SEQ=$HIT_SEQ
hit POST "/integration-backlog/request-decision" 200 '{}'
# The backlog must be real research, not an empty shell.
if [ -s /tmp/wq_resp_${BACKLOG_SEQ}.json ] && grep -q '"lane"' /tmp/wq_resp_${BACKLOG_SEQ}.json; then
  PASS=$((PASS+1)); printf '  PASS  backlog contains ranked lanes\n'
else
  FAIL=$((FAIL+1)); printf '  FAIL  backlog contains ranked lanes\n'
fi

echo "-- scheduler (recurring jobs) --"
hit GET  "/scheduler"                     200
hit POST "/scheduler/run"                200 '{}'
# The scheduler must have registered the business jobs.
SCHED_SEQ=$HIT_SEQ
hit GET  "/scheduler"                     200
if grep -q 'stock_guard' /tmp/wq_resp_${SCHED_SEQ}.json; then
  PASS=$((PASS+1)); printf '  PASS  scheduler registered the business jobs\n'
else
  FAIL=$((FAIL+1)); printf '  FAIL  scheduler registered the business jobs\n'
fi

echo "-- purchase intelligence --"
hit POST "/purchase-intel"         200 '{}'

echo "-- strike monitoring + stock price guard --"
hit GET  "/strikes"                200
hit POST "/strikes/record"         200 '{"week_start":"2026-10-27"}'
hit GET  "/stock-price-guard"      200
# The strike monitor must report the published 93% norm.
STRIKE_BODY="$(curl -sS --max-time 20 "$BASE/strikes" "${AUTH_HDR[@]}" | head -c 2000)"
if echo "$STRIKE_BODY" | grep -q '"norm_pct":93'; then
  echo "  ok   strike norm is 93%"
  PASS=$((PASS + 1))
else
  printf '  FAIL strike norm not 93%%: %s\n' "$STRIKE_BODY"
  FAIL=$((FAIL + 1))
fi
# The price guard must not silently apply a raise.
GUARD_BODY="$(curl -sS --max-time 20 "$BASE/stock-price-guard" "${AUTH_HDR[@]}" | head -c 2000)"
if echo "$GUARD_BODY" | grep -q '"actionable"'; then
  echo "  ok   stock price guard reports recommendations"
  PASS=$((PASS + 1))
else
  printf '  FAIL stock price guard did not report\n'
  FAIL=$((FAIL + 1))
fi

echo "-- review drafts --"
hit POST "/reviews/draft"          200 "{\"order_number\":\"${ORDER_NO}\"}"

echo "-- approval gate (human decision) --"
# Re-read the queue live: the offer draft above is what queued a new one.
APPROVAL_ID=$(curl -s -m 15 "$BASE/approvals" "${AUTH_HDR[@]}" | "$PYBIN" -c '
import json,sys
for row in json.load(sys.stdin):
    if row.get("status") == "pending":
        print(row["approval_id"]); break
')
if [ -n "$APPROVAL_ID" ]; then
  hit POST "/approvals/$APPROVAL_ID" 200 \
    '{"decision":"approved","decided_by":"rob","note":"api smoke test"}'
else
  printf '  SKIP  no pending approval found\n'
fi

echo
echo "======================================================"
echo "passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ]