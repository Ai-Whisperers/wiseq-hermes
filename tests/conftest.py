import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPO = Path(os.getenv("WISEQ_REPO_DIR", str(ROOT.parent / "wiseq-repo")))

# The API refuses writes without a token.  The test session configures
# one so the write path is exercised rather than refused; the dedicated
# tests in test_api_auth.py manage their own token deliberately.
TEST_API_TOKEN = "pytest-local-token"
os.environ.setdefault("WISEQ_API_TOKEN", TEST_API_TOKEN)


@pytest.fixture(scope="session")
def repo_dir() -> Path:
    if not REPO.exists():
        pytest.skip(f"client repo data not present at {REPO}")
    return REPO


@pytest.fixture(scope="session")
def api_client():
    """A TestClient that can call the write endpoints."""
    from fastapi.testclient import TestClient

    from wiseq.api import app
    return TestClient(app, headers={"X-WiseQ-Token": TEST_API_TOKEN})


@pytest.fixture()
def db(tmp_path):
    from wiseq.db.db import Database
    database = Database(f"sqlite:///{tmp_path}/test.db")
    database.init_schema()
    yield database
    database.close()


@pytest.fixture()
def loaded(db, repo_dir):
    from wiseq.ingest.loaders import load_all
    load_all(db, repo_dir)
    return db
