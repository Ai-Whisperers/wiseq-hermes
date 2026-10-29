#!/usr/bin/env bash
# Build the deliverable archive of wiseq-hermes from the COMMITTED git state.
#
# Rationale: the archive must reproduce exactly what a fresh clone of the
# GitHub repo produces, plus the two things Git deliberately does not carry:
#   - data/wiseq-repo/  the client's master data (mounted, never committed)
#   - .venv/            rebuilt by the consumer
#
# Excluded: .git, .venv, bytecode, caches, runtime databases, .env,
#           fleet dispatch artifacts, credentials.
set -euo pipefail

# Everything is relative to this script, so the archive can be built from
# a clone anywhere.  Override the client repo path with WISEQ_REPO_DIR.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SCRATCH="${WISEQ_ARCHIVE_WORKDIR:-$ROOT}"
SRC="$ROOT"
CLIENT="${WISEQ_REPO_DIR:-$ROOT/data/wiseq-repo}"
OUT="${WISEQ_ARCHIVE_OUT:-$SCRATCH/wiseq-hermes.tar.gz}"
STAGE="$SCRATCH/.stage-archive"

echo "== staging from the committed tree =="
rm -rf "$STAGE"
mkdir -p "$STAGE/wiseq-hermes"
mkdir -p "$(dirname "$OUT")"

# Export exactly what is committed in git (tracked files only).
cd "$SRC"
git archive --format=tar HEAD | tar -x -C "$STAGE/wiseq-hermes"

# Bring the client master data in alongside (it is mounted, not committed).
if [ -d "$CLIENT" ]; then
  mkdir -p "$STAGE/wiseq-hermes/data"
  cp -r "$CLIENT" "$STAGE/wiseq-hermes/data/wiseq-repo"
  # Strip its .git so the archive carries no nested repository history.
  rm -rf "$STAGE/wiseq-hermes/data/wiseq-repo/.git"
else
  echo "NOTE: no client repo at $CLIENT -- building without client master data"
fi

echo "== stripping build/runtime noise =="
find "$STAGE" \( -name '__pycache__' -type d \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
find "$STAGE" \( -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' \) -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.db' -delete 2>/dev/null || true
find "$STAGE" -name '.env' -delete 2>/dev/null || true
rm -rf "$STAGE/wiseq-hermes/.git" "$STAGE/wiseq-hermes/.venv" 2>/dev/null || true
# Fleet dispatch artifacts
find "$STAGE" \( -name '.dispatch-body.md' -o -name '.dispatch-result.json' -o -name '.dispatch-findings.yaml' -o -name '.pr-body.md' \) -delete 2>/dev/null || true
# The private client files stay OUT of the deliverable archive.  They are
# gitignored in the client repo and untracked at origin, so the archive
# must not reintroduce them.
rm -f "$STAGE/wiseq-hermes/data/wiseq-repo/data/client/Handleiding_opzet.txt"
rm -f "$STAGE/wiseq-hermes/data/wiseq-repo/data/client/meetings/"*.txt
# Belt and braces: anything else matching the client's private patterns.
find "$STAGE/wiseq-hermes/data/wiseq-repo/data/client" -name '*.txt' -delete 2>/dev/null || true

echo "== credential scan =="
HITS=$(grep -rIlE '(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|ghs_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' "$STAGE" 2>/dev/null || true)
if [ -n "$HITS" ]; then
  echo "!! CREDENTIAL PATTERNS FOUND:"
  echo "$HITS"
  exit 1
fi
echo "0 credential-pattern hits"

echo "== building archive =="
rm -f "$OUT"
# IMPORTANT: tar the STAGED copy, not the live repo directory.  Tarring
# "$SCRATCH/wiseq-hermes" would silently ignore every cleanup step above
# and ship the working tree (private client files included).
cd "$STAGE"
tar -czf "$OUT" \
  --exclude='wiseq-hermes/.venv' --exclude='wiseq-hermes/.git' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='*.db' --exclude='.pytest_cache' \
  wiseq-hermes
SIZE=$(stat -c%s "$OUT")
ENTRIES=$(tar -tzf "$OUT" | wc -l)
echo "archive: $OUT"
echo "bytes:   $SIZE"
echo "entries: $ENTRIES"
rm -rf "$STAGE"
echo "OK"
