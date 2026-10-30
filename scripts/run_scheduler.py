#!/usr/bin/env python3
"""Run the WiseQ recurring jobs.

Three ways to use it:

    # run every job once, now, and exit  (this is what a cron job wants)
    python scripts/run_scheduler.py once

    # run only one job
    python scripts/run_scheduler.py once --job sync_shopify

    # run the loop in the foreground until Ctrl-C
    python scripts/run_scheduler.py serve

Every job is detect-and-recommend.  Nothing here sends an email, changes
a live price, or contacts bol.com -- the jobs call the same agents the
API calls, and those agents write approvals for a human to decide on.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# In the Docker image the package is pip-installed, so `src/` does not
# exist and the import below resolves from site-packages.  Adding `src`
# to the path when it IS present makes the script work from a checkout
# without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from wiseq.config import get_settings            # noqa: E402
from wiseq.db.db import Database                 # noqa: E402
from wiseq.ingest.loaders import load_all        # noqa: E402
from wiseq.orchestrator import WiseQOrchestrator  # noqa: E402
from wiseq.scheduler import SchedulerGiveUp       # noqa: E402


def build_orchestrator() -> WiseQOrchestrator:
    settings = get_settings()
    repo = settings.repo_dir or (Path(__file__).resolve().parents[1]
                                  / "data" / "wiseq-repo")
    db = Database(settings.database_url)
    db.init_schema()
    if repo and Path(repo).exists():
        load_all(db, Path(repo))
    return WiseQOrchestrator(db, repo=Path(repo) if repo else None,
                             discount_pct=settings.school_discount_pct)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["once", "serve", "status"],
                    help="run every job once, run the loop, or show status")
    ap.add_argument("--job", help="run only this job (with 'once')")
    ap.add_argument("--poll", type=int, default=30,
                    help="seconds between polls in 'serve' mode")
    ap.add_argument("--max-failures", type=int, default=5,
                    help="stop the worker after this many CONSECUTIVE "
                         "failures of one job")
    args = ap.parse_args()

    orch = build_orchestrator()
    sched = orch.scheduler()

    if args.mode == "status":
        # The status a human actually needs: is the worker alive, are the
        # jobs healthy, and what is still broken.
        print(json.dumps({
            "liveness": sched.liveness(),
            "stale_jobs": sched.stale_jobs(),
            "job_state": sched.job_state(),
            "jobs": sched.status()["jobs"],
        }, indent=2, default=str))
        return 0

    if args.mode == "once":
        results = sched.run_once(only=args.job)
        print(json.dumps(results, indent=2, default=str))
        failures = [r for r in results if r.get("status") == "failed"]
        return 1 if failures else 0

    try:
        sched.serve_forever(poll_seconds=args.poll,
                            max_consecutive_failures=args.max_failures)
    except SchedulerGiveUp as exc:
        # A non-zero exit is the signal to the container runtime that the
        # worker gave up on a broken job rather than exiting cleanly.
        print(f"scheduler gave up: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
