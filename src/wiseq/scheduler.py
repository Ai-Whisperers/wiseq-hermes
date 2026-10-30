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

import os
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .db.db import Database
from .agents.base import audit


class SchedulerGiveUp(RuntimeError):
    """Raised when a job keeps failing and the worker should stop.

    It is a distinct exception on purpose: the caller (the container
    entry point, or the process supervisor) can tell "the worker gave
    up on a broken job" from "the worker crashed", and react
    differently -- restart the container in the first case, page a human
    in the second.
    """


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
            self._record_job_state(job, "failed", job.last_error)
            audit(self.db, "scheduler", "job_failed", "job", job.name,
                  {"error": job.last_error,
                   "trace": traceback.format_exc()[-2000:]})
            return {"job": job.name, "status": "failed", "error": job.last_error}

        job.last_error = None
        self._log_run(job, started, "ok", result)
        self._record_job_state(job, "ok")
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
    def serve_forever(self, poll_seconds: int = 30,
                      max_consecutive_failures: int = 5) -> None:
        """Run the loop until interrupted.  Safe to stop with Ctrl-C.

        The loop writes a heartbeat on every iteration, so an operator
        can tell a live worker from a dead one.  It also watches for a
        job that keeps failing and stops the worker when that happens:
        a worker that retries forever fills the log and hides the real
        problem.
        """
        self._running = True
        iteration = 0
        audit(self.db, "scheduler", "scheduler_started", "scheduler", None,
              {"jobs": [j.name for j in self.jobs], "pid": os.getpid()})
        self.heartbeat(iteration)
        try:
            while self._running:
                iteration += 1
                self.run_due()
                self.heartbeat(iteration)

                stop, reason = self.should_stop(max_consecutive_failures)
                if stop:
                    audit(self.db, "scheduler", "scheduler_stopped", "scheduler", None,
                          {"reason": reason, "failures": max_consecutive_failures})
                    raise SchedulerGiveUp(reason)

                time.sleep(poll_seconds)
        except KeyboardInterrupt:  # pragma: no cover - operator interrupt
            pass
        except SchedulerGiveUp:
            self._running = False
            raise
        finally:
            self.heartbeat(iteration, status="stopped")
            audit(self.db, "scheduler", "scheduler_stopped", "scheduler", None,
                  {"runs": {j.name: j.run_count for j in self.jobs}})

    def stop(self) -> None:
        self._running = False

    # -- supervision ----------------------------------------------------
    def _ensure_supervision_tables(self) -> None:
        """The tables that prove the worker is alive.

        The heartbeat is a write on every loop iteration.  That is
        deliberate: it is the only evidence that the process is doing
        anything at all, and a cheap write on a short interval is
        cheaper than a silent outage nobody notices for a week.
        """
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_heartbeats (
                heartbeat_id TEXT PRIMARY KEY,
                pid         INTEGER NOT NULL,
                jobs        TEXT NOT NULL,
                job_count   INTEGER NOT NULL DEFAULT 0,
                iteration   INTEGER NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'running',
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_job_state (
                job_name             TEXT PRIMARY KEY,
                last_run_at          TIMESTAMP,
                last_success_at      TIMESTAMP,
                last_failure_at      TIMESTAMP,
                last_error           TEXT,
                last_status          TEXT,
                run_count            INTEGER NOT NULL DEFAULT 0,
                failure_count        INTEGER NOT NULL DEFAULT 0,
                timeout_count        INTEGER NOT NULL DEFAULT 0,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

    def heartbeat(self, iteration: int = 0, status: str = "running") -> None:
        """Record one loop iteration."""
        self._ensure_supervision_tables()
        self.db.execute(
            "INSERT INTO scheduler_heartbeats "
            "(heartbeat_id, pid, jobs, job_count, iteration, status) "
            "VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, os.getpid(), _json([j.name for j in self.jobs]),
             len(self.jobs), iteration, status))

    def _record_job_state(self, job: Job, status: str,
                          error: str | None = None) -> None:
        """Persist a job's counters.

        These live in the database rather than in the Job object because
        a restarted scheduler has no memory of the previous process: the
        counters have to survive the restart for "too many CONSECUTIVE
        failures" to mean anything across a crash-and-restart cycle.
        """
        self._ensure_supervision_tables()
        now = datetime.now(timezone.utc)
        row = self.db.query_one(
            "SELECT consecutive_failures, run_count, failure_count "
            "FROM scheduler_job_state WHERE job_name = ?", (job.name,))

        consecutive = (row.get("consecutive_failures", 0) if row else 0)
        runs = (row.get("run_count", 0) if row else 0)
        failures = (row.get("failure_count", 0) if row else 0)

        if status == "ok":
            consecutive = 0
        elif status == "failed":
            consecutive += 1
            failures += 1
        runs += 1

        self.db.execute(
            "INSERT INTO scheduler_job_state "
            "(job_name, last_run_at, last_success_at, last_failure_at, "
            " last_error, last_status, run_count, failure_count, "
            " consecutive_failures, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(job_name) DO UPDATE SET "
            " last_run_at=excluded.last_run_at, "
            " last_success_at=COALESCE(excluded.last_success_at, "
            "                        scheduler_job_state.last_success_at), "
            " last_failure_at=COALESCE(excluded.last_failure_at, "
            "                        scheduler_job_state.last_failure_at), "
            " last_error=excluded.last_error, "
            " last_status=excluded.last_status, "
            " run_count=excluded.run_count, "
            " failure_count=excluded.failure_count, "
            " consecutive_failures=excluded.consecutive_failures, "
            " updated_at=excluded.updated_at",
            (job.name, now,
             now if status == "ok" else None,
             now if status == "failed" else None,
             error, status, runs, failures, consecutive, now))

    def job_state(self) -> list[dict[str, Any]]:
        """The persisted per-job counters."""
        self._ensure_supervision_tables()
        return self.db.query(
            "SELECT job_name, last_run_at, last_success_at, last_failure_at, "
            "last_error, last_status, run_count, failure_count, "
            "timeout_count, consecutive_failures, updated_at "
            "FROM scheduler_job_state ORDER BY job_name")

    def last_heartbeat(self) -> dict[str, Any] | None:
        """The newest heartbeat, or None if the worker never wrote one."""
        self._ensure_supervision_tables()
        return self.db.query_one(
            "SELECT heartbeat_id, pid, jobs, job_count, iteration, status, "
            "created_at FROM scheduler_heartbeats ORDER BY created_at DESC "
            "LIMIT 1")

    def liveness(self, stale_after_seconds: int = 300) -> dict[str, Any]:
        """Is the scheduler worker alive?

        Three states, not two.  ``alive`` means the heartbeat is recent.
        ``stale`` means the heartbeat exists but is older than the
        threshold -- the worker started and then stopped, which is
        different from never having started.  ``never_started`` means
        there is no heartbeat at all.

        The distinction matters: "stale" points at a worker that died
        or is wedged, while "never_started" points at a deployment that
        never ran one.
        """
        beat = self.last_heartbeat()
        if beat is None:
            return {"state": "never_started", "alive": False,
                    "stale_after_seconds": stale_after_seconds,
                    "last_heartbeat_at": None, "pid": None}

        created = _as_datetime(beat.get("created_at"))
        age = (datetime.now(timezone.utc) - created).total_seconds()
        alive = age <= stale_after_seconds
        return {
            "state": "alive" if alive else "stale",
            "alive": alive,
            "stale_after_seconds": stale_after_seconds,
            "last_heartbeat_at": created.isoformat(),
            "heartbeat_age_seconds": int(age),
            "pid": beat.get("pid"),
            "job_count": beat.get("job_count"),
        }

    def stale_jobs(self, stale_after_seconds: int = 300) -> list[dict[str, Any]]:
        """Jobs that have not run recently, or that keep failing.

        A job whose interval is longer than the staleness threshold
        would be reported stale even when it is working perfectly, so
        the threshold per job is the larger of the caller's threshold
        and the job's own interval.  A job that has never run at all is
        reported too -- that is a misconfiguration, not a slow job.
        """
        now = datetime.now(timezone.utc)
        states = {row["job_name"]: row for row in self.job_state()}
        out: list[dict[str, Any]] = []

        for job in self.jobs:
            state = states.get(job.name)
            threshold = max(stale_after_seconds, job.interval_seconds * 2)

            if state is None or not state.get("last_run_at"):
                out.append({"job": job.name, "reason": "never_ran",
                            "consecutive_failures": 0})
                continue

            last_run = _as_datetime(state.get("last_run_at"))
            age = (now - last_run).total_seconds()
            if age > threshold:
                out.append({
                    "job": job.name,
                    "reason": "not_run_recently",
                    "seconds_since_last_run": int(age),
                    "threshold_seconds": threshold,
                    "consecutive_failures": state.get("consecutive_failures", 0),
                })
                continue

            if state.get("consecutive_failures", 0) >= 3:
                out.append({
                    "job": job.name,
                    "reason": "repeated_failures",
                    "consecutive_failures": state.get("consecutive_failures", 0),
                    "last_error": state.get("last_error"),
                })
        return out

    def should_stop(self, max_consecutive_failures: int = 5) -> tuple[bool, str]:
        """Should the worker give up?

        A job that fails the same way five times in a row is not going
        to recover on its own, and a worker that keeps retrying forever
        fills the log and hides the real problem.  The worker stops and
        says why, so a human can look.

        This is a recommendation, not a silent exit: the reason is
        recorded and the process exits non-zero.
        """
        for state in self.job_state():
            failures = state.get("consecutive_failures", 0)
            if failures >= max_consecutive_failures:
                return True, (f"job {state['job_name']!r} failed "
                              f"{failures} times in a row: "
                              f"{state.get('last_error')}")
        return False, ""

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


def _as_datetime(value: Any) -> datetime:
    """Read a timestamp back from either dialect."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
