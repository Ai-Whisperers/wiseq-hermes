"""The Docker claims in the documentation must match what was executed.

On 2026-10-30 the stack was built and run on a real Docker daemon for the
first time.  That produced `docs/DOCKER-VERIFICATION.md` and changed three
documents that previously said the Docker path had never been executed.

These tests exist so the documentation cannot quietly drift back to
claiming "not run" (which would understate what is verified) or to
claiming a green run that never happened (which would overstate it).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCKER_DOC = REPO / "docs" / "DOCKER-VERIFICATION.md"
DOCS_THAT_MENTION_DOCKER = [
    REPO / "README.md",
    REPO / "docs" / "EVERYTHING-BUILT.md",
    REPO / "docs" / "HANDOVER.md",
]


@pytest.fixture(scope="module")
def docker_doc_text() -> str:
    if not DOCKER_DOC.exists():
        pytest.skip("DOCKER-VERIFICATION.md is not present")
    return DOCKER_DOC.read_text(encoding="utf-8")


def test_the_docker_verification_document_exists(docker_doc_text: str) -> None:
    assert docker_doc_text.strip(), "DOCKER-VERIFICATION.md is empty"


def test_no_document_still_claims_docker_was_never_run() -> None:
    """The stale 'never executed' claims must not come back."""
    stale_phrases = [
        "the docker build and docker compose up themselves",
        "are unrun.",
        "it has never been executed",
        "yaml-validated and ci-simulated",
        "**not run** | this container has the docker cli",
    ]
    offenders: list[str] = []
    for path in DOCS_THAT_MENTION_DOCKER:
        text = path.read_text(encoding="utf-8")
        for phrase in stale_phrases:
            if phrase.lower() in text.lower():
                offenders.append(f"{path.relative_to(REPO)}: {phrase!r}")
    assert not offenders, (
        "these documents still claim Docker was never executed:\n"
        + "\n".join(offenders)
    )


def test_readme_records_docker_as_verified() -> None:
    """README's status table must show the Docker row as run and green."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    row = re.search(r"^\| `docker build` / `docker compose up` \|([^|]*)\|", text, re.MULTILINE)
    assert row, "the README no longer has a docker build status row"
    assert "run and green" in row.group(1).lower(), (
        "the README still marks the Docker row as unverified: "
        f"{row.group(1).strip()!r}"
    )


def test_the_docker_document_records_the_measured_results(docker_doc_text: str) -> None:
    """The measured figures from the real run must be recorded."""
    # The API acceptance suite result observed inside the container.
    assert "passed: 37" in docker_doc_text and "failed: 0" in docker_doc_text
    # The demo exit status and line count.
    assert "RC=0" in docker_doc_text
    assert "509" in docker_doc_text
    # The scheduler job result.
    assert "decisions_owed" in docker_doc_text
    assert "51" in docker_doc_text and "35" in docker_doc_text
    # The single-recipient guarantee.
    assert "weissvanderpol@gmail.com" in docker_doc_text


def test_the_docker_document_links_the_api_smoke_portability_bug() -> None:
    """The bug the Docker run found must stay documented."""
    text = DOCKER_DOC.read_text(encoding="utf-8")
    assert "api_smoke.sh" in text
    assert "PYBIN" in text
    assert "test_script_portability.py" in text


def test_the_docker_document_still_lists_what_is_unverified() -> None:
    """Honesty guard: the document must not claim more than was proved."""
    text = DOCKER_DOC.read_text(encoding="utf-8")
    assert "What is still not verified" in text
    for honest_item in ("Supabase", "MCP"):
        assert honest_item in text, (
            f"the Docker document should still flag {honest_item} as unverified"
        )
