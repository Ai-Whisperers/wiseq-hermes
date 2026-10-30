"""Regression test for import paths that only break on one branch.

A relative import inside a conditional is invisible until that branch
actually runs.  The UCP connector had `from .prices import load_prices`
inside `if db is not None and load_into_db and resolved:` -- which
resolved to ``wiseq.connectors.prices``, a module that does not exist.
Every test that mocked the connector or skipped the load path passed;
only a real scan that RESOLVED a price AND loaded it crashed.

These tests import every module of the package and exercise the
conditional import paths explicitly, so a typo in a relative import
fails the suite instead of production.
"""
from __future__ import annotations

import ast
import importlib
import pkgutil

import pytest

import wiseq


def _all_modules() -> list[str]:
    """Every importable module in the package, including subpackages."""
    names = [wiseq.__name__]
    for info in pkgutil.walk_packages(wiseq.__path__, prefix="wiseq."):
        names.append(info.name)
    return names


def test_every_module_imports():
    """Import every module. A broken relative import fails here."""
    failures = []
    for name in _all_modules():
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not failures, "modules failed to import:\n" + "\n".join(failures)


def test_no_relative_import_points_at_a_missing_module():
    """No `from .x import y` may name a module that does not exist.

    This is the check that would have caught the UCP bug at commit time:
    the module it named (`wiseq.connectors.prices`) was never written.
    """
    import pathlib

    package_dir = pathlib.Path(wiseq.__file__).parent
    problems = []
    for path in package_dir.rglob("*.py"):
        rel = path.relative_to(package_dir).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        # The package root itself.
        module_name = "wiseq" + "".join("." + p for p in parts)

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            if node.module is None:
                continue
            # level=1 -> current package, level=2 -> parent package.
            base_parts = module_name.split(".")
            if parts and path.name == "__init__.py":
                anchor = module_name.split(".")
            else:
                anchor = module_name.split(".")[:-1]
            if node.level > len(anchor):
                problems.append(f"{path}: relative import goes above the package")
                continue
            target_parts = anchor[: len(anchor) - (node.level - 1)] + node.module.split(".")
            target = ".".join(target_parts)
            if not target.startswith("wiseq"):
                continue
            try:
                importlib.import_module(target)
            except ImportError:
                problems.append(
                    f"{path}: `from {'.' * node.level}{node.module} import ...` "
                    f"names {target}, which does not exist"
                )
    assert not problems, "broken relative imports:\n" + "\n".join(problems)


def test_ucp_price_load_path_is_importable():
    """The exact import the UCP loader uses, exercised directly.

    Regression for `from .prices import load_prices` inside
    wiseq/connectors/ucp.py, which resolved to a non-existent module.
    """
    from wiseq.ingest.prices import load_prices

    assert callable(load_prices)

    # The connector must not contain the broken import as CODE.  A plain
    # substring search also matches the explanatory comment that records
    # the fix, so parse the AST and look at real import statements only.
    source = importlib.util.find_spec("wiseq.connectors.ucp").origin
    tree = ast.parse(open(source, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "prices":
            assert node.level >= 2, (
                "ucp.py must not import a sibling .prices module "
                "(wiseq.connectors.prices does not exist); "
                "load_prices lives in wiseq.ingest.prices"
            )


def test_ucp_load_prices_path_resolves(monkeypatch):
    """Call the loader branch that used to crash.

    The branch is only reachable when the scan RESOLVED something AND was
    asked to load it into the database, which is why it went untested.
    """
    from wiseq.connectors import ucp as ucp_module

    class _Product:
        price_min = 12.50
        title = "Test product"

    class _FakeClient:
        endpoint = "http://example.invalid/ucp"

        def initialize(self):
            return {}

        def get_product(self, identifier):
            return _Product()

    class _FakeDB:
        def __init__(self):
            self.executed = []

        def query(self, sql, params=()):
            return []

        def execute(self, sql, params=()):
            self.executed.append((sql, params))

    db = _FakeDB()
    report = ucp_module.sync_ucp_catalog(
        db=db, client=_FakeClient(), skus=["1"], load_into_db=True
    )
    assert report["resolved"] == 1
    # It must have got as far as the load branch without an ImportError.
    assert report["loaded"] is not None
