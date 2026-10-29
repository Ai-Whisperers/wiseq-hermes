#!/usr/bin/env bash
# One-command local run (no Docker needed if you have Python 3.11+).
#
#   ./scripts/run_local.sh              # install, migrate, seed, serve
#   ./scripts/run_local.sh --demo       # also run the end-to-end demo
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
VENV="${VENV:-$ROOT/.venv}"

if [ ! -d "$VENV" ]; then
  echo ">> creating virtualenv at $VENV"
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo ">> installing package"
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"

if [ ! -f .env ]; then
  cp .env.example .env
  echo ">> created .env from .env.example -- edit it before going live"
fi

REPO_DIR="${WISEQ_REPO_DIR:-$ROOT/data/wiseq-repo}"
if [ ! -d "$REPO_DIR" ]; then
  echo ">> client data repo not found at $REPO_DIR"
  echo "   clone it with:"
  echo "   git clone --depth 1 https://github.com/Ai-Whisperers/wiseq-ai-onboarding.git data/wiseq-repo"
  echo "   (or point WISEQ_REPO_DIR at your own copy)"
fi

echo ">> running test suite"
pytest -q

if [ "${1:-}" = "--demo" ]; then
  echo ">> end-to-end demo"
  python scripts/demo_end_to_end.py "$REPO_DIR"
fi

echo ">> starting API on http://127.0.0.1:8000  (docs at /docs)"
exec uvicorn wiseq.api:app --host "${WISEQ_API_HOST:-127.0.0.1}" --port "${WISEQ_API_PORT:-8000}"
