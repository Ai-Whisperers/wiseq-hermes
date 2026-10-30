"""The test suite must not depend on the shell it runs in.

The API validates the `X-WiseQ-Token` header against the ambient
``WISEQ_API_TOKEN`` environment variable.  The shared ``api_client``
fixture sends a fixed token in that header.  If the environment already
carried a different token, the header and the expected value would
disagree and every write test would answer 401 -- so the suite's result
would depend on whether the operator happened to export a token.

That is exactly the kind of non-hermetic behaviour that hides a real
failure: the suite goes red for an environmental reason, and the red is
easy to dismiss as "just unset your token" instead of "something is
wrong".

These tests pin the property: the suite behaves identically no matter
what token the ambient environment carries.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_a_write_test(env_token: str | None) -> tuple[int, str]:
    """Run one write-path test with a given ambient token.

    Returns the exit code and the combined output.
    """
    import os

    env = dict(os.environ)
    env.pop("WISEQ_API_TOKEN", None)
    if env_token is not None:
        env["WISEQ_API_TOKEN"] = env_token
    env["WISEQ_REPO_DIR"] = env.get(
        "WISEQ_REPO_DIR", str(ROOT / "data" / "wiseq-repo")
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_api_class_set_and_warranty.py",
         "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.returncode, proc.stdout + proc.stderr


class TestSuiteIsHermeticAgainstAmbientTokens:
    def test_write_tests_pass_with_no_ambient_token(self):
        code, out = _run_a_write_test(None)
        assert code == 0, out[-3000:]

    def test_write_tests_pass_with_a_different_ambient_token(self):
        # This is the case that used to fail: an inherited token made the
        # header and the expected token disagree.
        code, out = _run_a_write_test("some-other-token-from-the-environment")
        assert code == 0, out[-3000:]

    def test_write_tests_pass_with_a_token_that_looks_like_the_test_one(self):
        code, out = _run_a_write_test("pytest-local-token-but-different")
        assert code == 0, out[-3000:]

    def test_the_conftest_overrides_rather_than_defaults(self):
        source = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
        assert 'os.environ["WISEQ_API_TOKEN"] = TEST_API_TOKEN' in source
        assert "setdefault" not in source, (
            "setdefault lets an ambient token win, which is the "
            "non-hermetic behaviour this file exists to prevent"
        )
