"""Durable recurring jobs for the WiseQ operations replica.

Everything the replica knows how to do on demand -- syncing the
storefront catalogue, checking the strike norm, guarding low stock,
drafting reviews -- used to need a human to press the button.  That is
fine for a demo and useless for an operating business: the rules have
their own cadence.

From the operating manual and setup guide:

  * bol.com evaluates the on-time norm **every Wednesday at 10:00**;
  * prices and stock drift continuously, so the storefront catalogue
    should be re-synced on a short interval;
  * the stock-price guard should run daily;
  * review invitations go out on a delay after delivery.

This module is the durable scheduler.  It is deliberately small and
dependency-free: a loop, a job registry, and a run log in the
database.  No APScheduler, no Celery, no Redis -- the whole point is
that the directory stays portable and starts with one command.

Design rules that matter:

  * **A job that raises an exception is logged and the loop continues.**
    One broken job must never stop the others.
  * **Jobs are detect-and-recommend only.**  Nothing here sends an
    email, changes a live price, or contacts bol.com.  The jobs call the
    same agents the API calls, and those agents write approvals.
  * **Every run is recorded** in ``job_runs`` so an operator can see
    what happened and when, including failures.
  * **The scheduler can be driven one-shot** (``run_once``) so a cron
    job, an external scheduler, or a test can trigger it without
    starting a thread.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .db.db import Database
from .agents.base import audit


@dataclass
class Job:
    """One recurring task."""

    name: str
    fn: Callable[[], Any]
    #: Seconds between runs.
    interval_seconds: int
    #: When True the job runs once at startup.
    run_at_start: bool = True
    #: Free-text note shown in /health and the demo.
    description: str = ""
    last_run_at: datetime | None = None
    last_error: str | None = None
    run_count: int = 0
    failure_count: int = 0
    #: Seconds until the next run is allowed.
    next_due: float = 0.0


@dataclass
class Scheduler:
    """A small, durable, dependency-free job loop."""

    db: Database
    jobs: list[Job] = field(default_factory=list)
    _running: bool = False

    # -- registration ---------------------------------------------------
    def every(self, name: str, seconds: int, fn: Callable[[], Any],
              description: str = "", run_at_start: bool = True) -> Job:
        job = Job(name=name, fn=fn, interval_seconds=max(1, seconds),
                  run_at_start=run_at_start, description=description)
        self.jobs.append(job)
        return job

    def get(self, name: str) -> Job | None:
        for j in self.jobs:
            if j.name == name:
                return j
        return None

    # -- persistence ----------------------------------------------------
    def _ensure_table(self) -> None:
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS job_runs (
                run_id       TEXT PRIMARY KEY,
                job_name     TEXT NOT NULL,
                started_at   TIMESTAMP NOT NULL,
                finished_at  TIMESTAMP,
                status       TEXT NOT NULL DEFAULT 'running',
                detail       TEXT,
                error        TEXT
            )""")

    def _log_run(self, job: Job, started: datetime, status: str,
                 detail: Any = None, error: str | None = None) -> None:
        self._ensure_table()
        self.db.execute(
            """INSERT INTO job_runs (run_id, job_name, started_at, finished_at,
                                     status, detail, error)
               VALUES (?,?,?,CURRENT_TIMESTAMP,?,?,?)""",
            (f"{job.name}-{started.strftime('%Y%m%d%H%M%S%f')}", job.name,
             started, status,
             _json(detail), error))

    # -- execution ------------------------------------------------------
    def run_job(self, job: Job) -> dict[str, Any]:
        """Run one job, catching and recording any failure."""
        started = datetime.now(timezone.utc)
        job.run_count += 1
        job.last_run_at = started
        try:
            result = job.fn()
        except Exception as exc:  # noqa: BLE001 - a job must not kill the loop
            job.failure_count += 1
            job.last_error = f"{type(exc).__name__}: {exc}"
            self._log_run(job, started, "failed", None, job.last_error)
            audit(self.db, "scheduler", "job_failed", "job", job.name,
                  {"error": job.last_error,
                   "trace": traceback.format_exc()[-2000:]})
            return {"job": job.name, "status": "failed", "error": job.last_error}

        job.last_error = None
        self._log_run(job, started, "ok", result)
        audit(self.db, "scheduler", "job_ran", "job", job.name,
              {"result": _summarise(result)})
        return {"job": job.name, "status": "ok", "result": _summarise(result)}

    def run_due(self, now: float | None = None) -> list[dict[str, Any]]:
        """Run every job whose interval has elapsed."""
        now = now if now is not None else time.time()
        results = []
        for job in self.jobs:
            if job.next_due and now < job.next_due:
                continue
            results.append(self.run_job(job))
            job.next_due = now + job.interval_seconds
        return results

    def run_once(self, only: str | None = None) -> list[dict[str, Any]]:
        """Run every job (or one named job) exactly once.

        This is the entry point for an external cron job -- there is no
        need to run the loop to get the value of the jobs.
        """
        results = []
        for job in self.jobs:
            if only and job.name != only:
                continue
            results.append(self.run_job(job))
            job.next_due = time.time() + job.interval_seconds
        return results

    # -- the loop -------------------------------------------------------
    def serve_forever(self, poll_seconds: int = 30) -> None:
        """Run the loop until interrupted.  Safe to stop with Ctrl-C."""
        self._running = True
        audit(self.db, "scheduler", "scheduler_started", "scheduler", None,
              {"jobs": [j.name for j in self.jobs]})
        try:
            while self._running:
                self.run_due()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:  # pragma: no cover - operator interrupt
            pass
        finally:
            audit(self.db, "scheduler", "scheduler_stopped", "scheduler", None,
                  {"runs": {j.name: j.run_count for j in self.jobs}})

    def stop(self) -> None:
        self._running = False

    # -- reporting ------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "jobs": [
                {
                    "name": j.name,
                    "description": j.description,
                    "interval_seconds": j.interval_seconds,
                    "run_count": j.run_count,
                    "failure_count": j.failure_count,
                    "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                    "last_error": j.last_error,
                }
                for j in self.jobs
            ],
        }

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        self._ensure_table()
        return self.db.query(
            "SELECT job_name, started_at, finished_at, status, error "
            "FROM job_runs ORDER BY started_at DESC LIMIT ?", (limit,))


def _json(value: Any) -> str | None:
    if value is None:
        return None
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:4000]
    except (TypeError, ValueError):
        return str(value)[:4000]


def _summarise(result: Any) -> Any:
    """Keep the run log small: counts, not whole report payloads."""
    if isinstance(result, dict):
        out = {}
        for k, v in result.items():
            if isinstance(v, (int, float, str, bool)) or v is None:
                out[k] = v
            elif isinstance(v, (list, tuple)):
                out[k] = len(v)
            elif isinstance(v, dict):
                out[k] = len(v)
        return out
    if isinstance(result, (list, tuple)):
        return len(result)
    if isinstance(result, (int, float, str, bool)) or result is None:
        return result
    return str(result)[:500]
