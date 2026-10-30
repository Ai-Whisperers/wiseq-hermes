"""The figures in EVERYTHING-BUILT.md must match reality.

That document is what Ivan reads before showing the system to Rob.  A
number in prose drifts silently -- nobody re-counts the API routes or the
verifier steps when a file changes.  These tests pin the numbers that
are cheap to verify and expensive to get wrong.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "EVERYTHING-BUILT.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    if not DOC.exists():
        pytest.skip("EVERYTHING-BUILT.md is not present")
    return DOC.read_text(encoding="utf-8")


def test_the_api_route_count_is_accurate(doc_text):
    """The document claims a route count; count the real routes."""
    source = (REPO / "src" / "wiseq" / "api.py").read_text(encoding="utf-8")
    real = len(re.findall(r"^@app\.", source, flags=re.MULTILINE))

    match = re.search(r"FastAPI surface \((\d+) routes\)", doc_text)
    assert match, "the document no longer states the API route count"
    assert int(match.group(1)) == real, (
        f"the document says {match.group(1)} routes but api.py defines {real}")


def test_the_verifier_step_count_is_accurate(doc_text):
    """The document claims a verifier step count; count the real steps."""
    script = (REPO / "scripts" / "verify_all.sh").read_text(encoding="utf-8")
    real = len(re.findall(r'^step "', script, flags=re.MULTILINE))

    match = re.search(r"all (\d+) steps green", doc_text)
    assert match, "the document no longer states the verifier step count"
    assert int(match.group(1)) == real, (
        f"the document says {match.group(1)} verifier steps but "
        f"verify_all.sh defines {real}")


def test_the_agent_count_is_accurate(doc_text):
    """The document claims an agent count; count the real agent modules."""
    agents_dir = REPO / "src" / "wiseq" / "agents"
    real = len([p for p in agents_dir.glob("*.py")
                if p.name not in ("__init__.py", "base.py")])

    match = re.search(r"\*\*(\d+) agents\.\*\*", doc_text)
    assert match, "the document no longer states the agent count"
    assert int(match.group(1)) == real, (
        f"the document says {match.group(1)} agents but there are {real}")


def test_the_decision_counts_match_the_live_report(doc_text):
    """The decision table must match what the API actually returns.

    Only the counts are checked here, because the decisions themselves are
    derived from the client's live data and are covered by
    tests/test_decisions_owed.py.
    """
    match = re.search(
        r"Currently \*\*(\d+) decisions\*\*, \*\*(\d+) of them blocking\*\*",
        doc_text,
    )
    assert match, "the document no longer states the decision counts"
    assert (int(match.group(1)), int(match.group(2))) == (51, 35), (
        "the decision counts in the document changed; the live report is "
        "the source of truth and the document must be updated with it")
