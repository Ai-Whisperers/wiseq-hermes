"""Tests for scheduler supervision.

The problem supervision solves is narrow: *a scheduler that has stopped
working must not look like a scheduler that is working*.  A scheduler
that is up but whose jobs have silently stopped is worse than one that
is visibly down, so the tests here are about telling those apart.

The counters live in the database rather than in the process, so
"three consecutive failures" means the same thing before and after a
restart.  That is tested explicitly.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiseq.db.db import Database  # noqa: E402
from wiseq.scheduler import Scheduler, SchedulerGiveUp  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path/'sched.db'}")
    database.init_schema()
    return database


@pytest.fixture()
def sched(db):
    return Scheduler(db=db)


def _boom():
    raise RuntimeError("boom")


# --------------------------------------------------------------------------
# heartbeats
# --------------------------------------------------------------------------
def test_a_heartbeat_is_written(sched):
    sched.heartbeat(1)
    beat = sched.last_heartbeat()
    assert beat is not None
    assert beat["status"] == "running"


def test_the_heartbeat_records_the_pid(sched):
    import os

    sched.heartbeat(1)
    assert sched.last_heartbeat()["pid"] == os.getpid()


def test_the_heartbeat_records_the_job_names(sched):
    sched.every("a", 60, lambda: 1)
    sched.every("b", 60, lambda: 1)
    sched.heartbeat(1)
    beat = sched.last_heartbeat()
    assert beat["job_count"] == 2
    assert "a" in beat["jobs"] and "b" in beat["jobs"]


def test_a_scheduler_that_never_ran_is_never_started(sched):
    liveness = sched.liveness()
    assert liveness["state"] == "never_started"
    assert liveness["alive"] is False


def test_a_recent_heartbeat_is_alive(sched):
    sched.heartbeat(1)
    liveness = sched.liveness(stale_after_seconds=300)
    assert liveness["state"] == "alive"
    assert liveness["alive"] is True


def test_an_old_heartbeat_is_stale_not_never_started(sched):
    """A worker that started and then stopped is a different problem
    from one that never started."""
    sched.heartbeat(1)
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    sched.db.execute("UPDATE scheduler_heartbeats SET created_at = ?", (old,))
    liveness = sched.liveness(stale_after_seconds=300)
    assert liveness["state"] == "stale"
    assert liveness["alive"] is False


def test_a_clean_stop_is_recorded(sched):
    sched.heartbeat(3, status="stopped")
    assert sched.last_heartbeat()["status"] == "stopped"


# --------------------------------------------------------------------------
# per-job state
# --------------------------------------------------------------------------
def test_a_successful_run_is_recorded(sched):
    job = sched.every("ok", 60, lambda: {"n": 1})
    sched.run_job(job)
    state = sched.job_state()[0]
    assert state["last_status"] == "ok"
    assert state["run_count"] == 1
    assert state["consecutive_failures"] == 0
    assert state["last_success_at"] is not None


def test_a_failed_run_is_recorded_with_the_error(sched):
    job = sched.every("bad", 60, _boom)
    sched.run_job(job)
    state = sched.job_state()[0]
    assert state["last_status"] == "failed"
    assert "boom" in state["last_error"]
    assert state["consecutive_failures"] == 1


def test_consecutive_failures_reset_on_success(sched):
    """Three failures then a success means one, not three."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 3:
            raise RuntimeError("boom")
        return "ok"

    job = sched.every("flaky", 60, flaky)
    for _ in range(3):
        sched.run_job(job)
    assert sched.job_state()[0]["consecutive_failures"] == 3

    sched.run_job(job)
    assert sched.job_state()[0]["consecutive_failures"] == 0


def test_the_counters_survive_a_restart(sched, db):
    """A restarted scheduler has no memory -- the counters must be in the
    database, or 'three consecutive failures' means nothing across a
    crash-and-restart cycle."""
    job = sched.every("bad", 60, _boom)
    sched.run_job(job)
    sched.run_job(job)

    fresh = Scheduler(db=db)
    assert fresh.job_state()[0]["consecutive_failures"] == 2


def test_the_total_run_count_survives_a_restart(sched, db):
    job = sched.every("ok", 60, lambda: 1)
    sched.run_job(job)
    sched.run_job(job)

    fresh = Scheduler(db=db)
    assert fresh.job_state()[0]["run_count"] == 2


# --------------------------------------------------------------------------
# stale jobs
# --------------------------------------------------------------------------
def test_a_job_that_never_ran_is_stale(sched):
    sched.every("never", 60, lambda: 1)
    stale = sched.stale_jobs()
    assert any(s["job"] == "never" and s["reason"] == "never_ran" for s in stale)


def test_a_recently_run_job_is_not_stale(sched):
    job = sched.every("ok", 60, lambda: 1)
    sched.run_job(job)
    stale = sched.stale_jobs()
    assert not any(s["job"] == "ok" for s in stale)


def test_a_long_interval_job_is_not_called_stale(sched):
    """A job that runs daily must not be reported stale after five
    minutes just because the default threshold is short."""
    job = sched.every("daily", 86400, lambda: 1)
    sched.run_job(job)
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    sched.db.execute("UPDATE scheduler_job_state SET last_run_at = ?", (old,))
    stale = sched.stale_jobs(stale_after_seconds=300)
    assert not any(s["job"] == "daily" for s in stale)


def test_a_repeatedly_failing_job_is_stale(sched):
    job = sched.every("bad", 60, _boom)
    for _ in range(3):
        sched.run_job(job)
    stale = sched.stale_jobs()
    assert any(s["job"] == "bad" and s["reason"] == "repeated_failures"
               for s in stale)


# --------------------------------------------------------------------------
# giving up
# --------------------------------------------------------------------------
def test_the_worker_does_not_give_up_on_a_few_failures(sched):
    job = sched.every("bad", 60, _boom)
    sched.run_job(job)
    sched.run_job(job)
    stop, reason = sched.should_stop(max_consecutive_failures=5)
    assert stop is False
    assert reason == ""


def test_the_worker_gives_up_after_repeated_failures(sched):
    job = sched.every("bad", 60, _boom)
    for _ in range(5):
        sched.run_job(job)
    stop, reason = sched.should_stop(max_consecutive_failures=5)
    assert stop is True
    assert "bad" in reason


def test_the_give_up_reason_names_the_job_and_the_error(sched):
    job = sched.every("broken", 60, _boom)
    for _ in range(5):
        sched.run_job(job)
    _, reason = sched.should_stop(max_consecutive_failures=5)
    assert "broken" in reason
    assert "boom" in reason


def test_a_success_resets_the_give_up_counter(sched):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 4:
            raise RuntimeError("boom")
        return "ok"

    job = sched.every("flaky", 60, flaky)
    for _ in range(4):
        sched.run_job(job)
    assert sched.should_stop(max_consecutive_failures=5)[0] is False

    sched.run_job(job)
    assert sched.should_stop(max_consecutive_failures=5)[0] is False


def test_the_give_up_exception_is_distinct(sched):
    """A worker that gave up on a broken job is not the same as a
    worker that crashed."""
    assert issubclass(SchedulerGiveUp, RuntimeError)


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------
def test_the_loop_writes_a_heartbeat_and_stops(sched, monkeypatch):
    """The loop must leave evidence that it ran."""
    sched.every("ok", 60, lambda: 1)

    calls = {"n": 0}

    def fake_sleep(seconds):
        calls["n"] += 1
        if calls["n"] >= 2:
            sched.stop()

    monkeypatch.setattr("wiseq.scheduler.time.sleep", fake_sleep)
    sched.serve_forever(poll_seconds=1)

    assert sched.last_heartbeat() is not None
    assert sched.liveness()["state"] == "alive"


def test_the_loop_raises_when_a_job_keeps_failing(sched, monkeypatch):
    job = sched.every("bad", 60, _boom)
    for _ in range(5):
        sched.run_job(job)

    monkeypatch.setattr("wiseq.scheduler.time.sleep", lambda s: None)
    with pytest.raises(SchedulerGiveUp):
        sched.serve_forever(poll_seconds=1, max_consecutive_failures=5)
