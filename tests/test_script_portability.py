"""Guards against scripts that only work on the machine that wrote them.

Every operational script must be runnable from a fresh clone, inside the
Docker image, and on a colleague's laptop.  The concrete failure this
prevents: `scripts/api_smoke.sh` used to call a hardcoded absolute path to
the original developer's virtualenv, so the API acceptance suite silently
skipped its assertions anywhere else (Docker, CI, a new clone).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

# Any absolute path into a developer home / scratch tree.  `/data` is
# deliberately NOT matched: it is the legitimate container mount point used
# by docker-compose.yml, and repo-relative paths like `$ROOT/data/...` are
# portable by construction.
DEV_PATH = re.compile(r"/(?:opt|home|Users|root)/[^\s\"'|:)]*")

def _script_files() -> list[Path]:
    files = sorted(
        p
        for p in SCRIPTS.rglob("*")
        if p.is_file() and p.suffix in {".sh", ".py", ".bat"}
    )
    assert files, "no scripts found to check"
    return files


def test_no_script_contains_a_developer_machine_path() -> None:
    """No script may embed an absolute path from a specific machine."""
    offenders: list[str] = []
    for path in _script_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            match = DEV_PATH.search(line)
            if match:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {match.group(0)}")
    assert not offenders, "developer-specific paths found:\n" + "\n".join(offenders)


def test_api_smoke_resolves_its_interpreter_dynamically() -> None:
    """api_smoke.sh must resolve its interpreter from the environment.

    The only permitted literal `.venv/bin/python` is the *candidate* inside
    the resolution loop, which is derived from the script's own location and
    is therefore portable.  Every actual invocation must go through $PYBIN.
    """
    text = (SCRIPTS / "api_smoke.sh").read_text(encoding="utf-8")
    literal_lines = [
        line
        for line in text.splitlines()
        if ".venv/bin/python" in line
    ]
    for line in literal_lines:
        assert 'dirname "$0"' in line, (
            "api_smoke.sh references .venv/bin/python outside the "
            f"location-derived candidate list: {line.strip()}"
        )
    # The resolution logic must still exist and try the project venv first.
    assert "PYBIN=" in text
    assert "command -v python3" in text


def test_api_smoke_uses_pybin_for_every_interpreter_call() -> None:
    """Every python invocation in api_smoke.sh must go through $PYBIN."""
    text = (SCRIPTS / "api_smoke.sh").read_text(encoding="utf-8")
    # Heredoc-style calls: `PYBIN - <<'PY'` (possibly quoted).
    calls = re.findall(r"^\s*(?:\S*python\S*)\s+-\s+<<", text, re.MULTILINE)
    assert not calls, (
        "api_smoke.sh invokes python without $PYBIN:\n" + "\n".join(calls)
    )
    assert '"$PYBIN" - <<' in text or "$PYBIN - <<" in text


@pytest.mark.parametrize("name", ["verify_all.sh", "run_local.sh"])
def test_verifier_scripts_are_portable(name: str) -> None:
    """The main verification scripts must not depend on one machine."""
    path = SCRIPTS / name
    assert path.exists(), f"{name} is missing"
    text = path.read_text(encoding="utf-8")
    assert not DEV_PATH.search(text), f"{name} embeds a developer-specific path"
