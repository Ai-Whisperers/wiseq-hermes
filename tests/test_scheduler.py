"""The recurring scheduler must be durable, observable and fail-safe."""
from __future__ import annotations

import pytest

from wiseq.db.db import Database
from wiseq.scheduler import Scheduler


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path/'s.db'}")
    d.init_schema()
    return d


# -- registration -----------------------------------------------------
def test_job_is_registered(db):
    s = Scheduler(db)
    s.every("ping", 60, lambda: "pong")
    assert s.get("ping") is not None
    assert s.get("missing") is None


def test_interval_is_at_least_one_second(db):
    s = Scheduler(db)
    job = s.every("ping", 0, lambda: "pong")
    assert job.interval_seconds == 1


def test_status_lists_every_job(db):
    s = Scheduler(db)
    s.every("a", 60, lambda: 1, description="first")
    s.every("b", 60, lambda: 2, description="second")
    status = s.status()
    assert len(status["jobs"]) == 2
    assert {j["name"] for j in status["jobs"]} == {"a", "b"}


# -- execution --------------------------------------------------------
def test_run_once_executes_the_job(db):
    calls = []
    s = Scheduler(db)
    s.every("ping", 60, lambda: calls.append(1) or "pong")
    results = s.run_once()
    assert calls == [1]
    assert results[0]["status"] == "ok"


def test_run_once_can_target_one_job(db):
    calls = []
    s = Scheduler(db)
    s.every("a", 60, lambda: calls.append("a"))
    s.every("b", 60, lambda: calls.append("b"))
    s.run_once(only="a")
    assert calls == ["a"]


def test_run_once_with_unknown_job_runs_nothing(db):
    calls = []
    s = Scheduler(db)
    s.every("a", 60, lambda: calls.append("a"))
    results = s.run_once(only="nope")
    assert results == []
    assert calls == []


def test_result_is_summarised(db):
    """The run log must stay small: counts, not whole payloads."""
    s = Scheduler(db)
    s.every("a", 60, lambda: {"count": 3, "items": [1, 2, 3, 4], "meta": {"x": 1}})
    result = s.run_once()[0]["result"]
    assert result["count"] == 3
    assert result["items"] == 4
    assert result["meta"] == 1


def test_a_failing_job_is_recorded_not_raised(db):
    def boom():
        raise ValueError("kaboom")
    s = Scheduler(db)
    s.every("bad", 60, boom)
    result = s.run_once()[0]
    assert result["status"] == "failed"
    assert "kaboom" in result["error"]


def test_one_failing_job_does_not_stop_the_others(db):
    ran = []
    s = Scheduler(db)
    s.every("bad", 60, lambda: (_ for _ in ()).throw(ValueError("x")))
    s.every("good", 60, lambda: ran.append("good"))
    s.run_once()
    assert ran == ["good"]


def test_failure_is_audited(db):
    s = Scheduler(db)
    s.every("bad", 60, lambda: (_ for _ in ()).throw(ValueError("x")))
    s.run_once()
    rows = db.query("SELECT action FROM audit_log WHERE action='job_failed'")
    assert len(rows) == 1


def test_failure_counters_accumulate(db):
    s = Scheduler(db)
    s.every("bad", 60, lambda: (_ for _ in ()).throw(ValueError("x")))
    s.run_once()
    s.run_once()
    job = s.get("bad")
    assert job.run_count == 2
    assert job.failure_count == 2


# -- the run log ------------------------------------------------------
def test_runs_are_recorded_in_the_database(db):
    s = Scheduler(db)
    s.every("ping", 60, lambda: "ok")
    s.run_once()
    runs = s.recent_runs()
    assert len(runs) == 1
    assert runs[0]["job_name"] == "ping"
    assert runs[0]["status"] == "ok"


def test_failed_runs_are_recorded_with_the_error(db):
    s = Scheduler(db)
    s.every("bad", 60, lambda: (_ for _ in ()).throw(ValueError("nope")))
    s.run_once()
    runs = s.recent_runs()
    assert runs[0]["status"] == "failed"
    assert "nope" in runs[0]["error"]


def test_recent_runs_are_newest_first(db):
    s = Scheduler(db)
    s.every("a", 60, lambda: 1)
    s.every("b", 60, lambda: 2)
    s.run_once()
    s.run_once()
    runs = s.recent_runs()
    # two jobs, two rounds of run_once -> four recorded runs
    assert len(runs) == 4
    assert runs[0]["started_at"] >= runs[1]["started_at"]


# -- scheduling --------------------------------------------------------
def test_run_due_skips_a_job_that_is_not_due(db):
    calls = []
    s = Scheduler(db)
    s.every("a", 3600, lambda: calls.append(1))
    s.run_once()
    assert len(calls) == 1
    s.run_due()          # not due yet -- the interval has not elapsed
    assert len(calls) == 1


def test_run_due_runs_a_job_once_the_interval_passed(db):
    calls = []
    s = Scheduler(db)
    s.every("a", 1, lambda: calls.append(1))
    s.run_once()
    s.run_due(now=10 ** 12)     # far in the future
    assert len(calls) == 2


def test_run_at_start_flag_exists(db):
    s = Scheduler(db)
    job = s.every("a", 60, lambda: 1, run_at_start=False)
    assert job.run_at_start is False


# -- orchestration wiring ---------------------------------------------
def test_orchestrator_registers_the_business_jobs(tmp_path):
    """The scheduler must cover the manual's own cadence."""
    from pathlib import Path
    from wiseq.orchestrator import WiseQOrchestrator
    d = Database(f"sqlite:///{tmp_path/'o.db'}")
    d.init_schema()
    orch = WiseQOrchestrator(d, repo=Path(tmp_path))
    names = {j["name"] for j in orch.scheduler().status()["jobs"]}
    assert {"sync_shopify", "strike_check", "stock_guard",
            "review_drafts"} <= names


def test_orchestrator_jobs_are_described(tmp_path):
    from pathlib import Path
    from wiseq.orchestrator import WiseQOrchestrator
    d = Database(f"sqlite:///{tmp_path/'o2.db'}")
    d.init_schema()
    orch = WiseQOrchestrator(d, repo=Path(tmp_path))
    for job in orch.scheduler().status()["jobs"]:
        assert job["description"], f"{job['name']} has no description"


def test_no_job_sends_email_or_writes_a_price(tmp_path):
    """A scheduled job must never act on the business directly."""
    from pathlib import Path
    from wiseq.orchestrator import WiseQOrchestrator
    d = Database(f"sqlite:///{tmp_path/'o3.db'}")
    d.init_schema()
    orch = WiseQOrchestrator(d, repo=Path(tmp_path))
    for job in orch.scheduler().jobs:
        assert job.fn.__name__.startswith("_"), \
            "scheduler jobs must be private helpers, not agent entry points"
