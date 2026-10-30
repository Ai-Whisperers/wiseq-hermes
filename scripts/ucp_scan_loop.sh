#!/usr/bin/env bash
# Keep running the resumable UCP catalogue scan until every SKU is settled.
#
# The storefront rate-limits a full scan, and its back-off window is
# measured in tens of minutes.  The scan is RESUMABLE: each run asks only
# for the SKUs it never resolved, so a throttled run is continued rather
# than restarted, and the storefront sees fewer calls on every attempt.
#
# Usage:  scripts/ucp_scan_loop.sh [progress_file] [max_minutes]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROGRESS="${1:-$ROOT/data/wiseq.ucp_scan.json}"
MAX_MINUTES="${2:-180}"
LOG="$ROOT/data/ucp_scan_loop.log"
DEADLINE=$(( $(date +%s) + MAX_MINUTES * 60 ))

attempt=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    attempt=$(( attempt + 1 ))
    echo "=== attempt $attempt at $(date -u +%FT%TZ) ===" >> "$LOG"

    "$ROOT/.venv/bin/python" scripts/ucp_scan_live.py \
        --progress "$PROGRESS" >> "$LOG" 2>&1
    status=$?

    summary=$("$ROOT/.venv/bin/python" - "$PROGRESS" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("unknown")
    raise SystemExit
resolved = len(d.get("resolved") or {})
not_found = len(d.get("not_found") or [])
failed = len(d.get("failed") or [])
print(f"{resolved} {not_found} {failed}")
PY
)
    set -- $summary
    resolved="${1:-0}"; not_found="${2:-0}"; failed="${3:-0}"

    echo "resolved=$resolved not_found=$not_found failed=$failed status=$status" >> "$LOG"

    # Done when nothing is left to ask about.
    if [ "$resolved" -gt 0 ] && [ "$(( resolved + not_found ))" -ge 139 ]; then
        echo "COMPLETE: $resolved resolved, $not_found not found" >> "$LOG"
        exit 0
    fi

    # Back off a little between attempts so a live rate limit can expire.
    sleep 120
done

echo "TIMEOUT after $MAX_MINUTES minutes; progress is saved in $PROGRESS" >> "$LOG"
exit 2
