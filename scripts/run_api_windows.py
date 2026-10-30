#!/usr/bin/env python
"""Start the WiseQ API on Windows with the environment it needs.

The scheduled task that keeps the API alive on Ivan's PC runs this
script.  A scheduled task does not inherit the shell's environment, so
the API token has to be read from disk and injected here.  Without it the
API still starts, but remote reads are refused -- which is correct, and
not what we want when the API is deliberately published on the Tailscale
address for a demonstration.

The token is never printed.  It is written to ``.wiseq-token`` with
owner-only permissions and read back here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / ".wiseq-token"

HOST = os.environ.get("WISEQ_API_HOST", "100.105.54.119")
PORT = os.environ.get("WISEQ_API_PORT", "8010")


def _main() -> int:
    os.environ.setdefault("WISEQ_REPO_DIR", str(ROOT / "data" / "wiseq-repo"))

    token = ""
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if token:
        os.environ["WISEQ_API_TOKEN"] = token
    else:
        # No token file: the API still starts, and remote reads fail
        # closed.  That is the safe direction, so continue.
        print("[wiseq] no .wiseq-token found; remote reads stay refused",
              flush=True)

    import uvicorn

    uvicorn.run("wiseq.api:app", host=HOST, port=int(PORT),
                log_level="info", access_log=True)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
