"""The installed package must resolve to `src/`, not to a stale copy.

`pip install ".[dev]"` installs a COPY of the package into site-packages.
After that, `import wiseq` loads the copy -- so an edit to `src/wiseq/*`
is invisible to anything that imports the installed package, including
the FastAPI app under test and the API smoke script.

That is exactly what happened on 2026-10-29: the new `/strikes` and
`/stock-price-guard` routes were present in `src/wiseq/api.py` but the
installed copy did not have them, so the endpoints answered 404 while
the unit tests (which put `src` on `pythonpath`) passed happily.

This test fails when the installed package is a copy rather than an
editable pointer to `src/`.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_installed_package_resolves_to_the_source_tree():
    import wiseq

    installed = Path(wiseq.__file__).resolve()
    src = (REPO / "src").resolve()

    try:
        installed.relative_to(src)
        return  # editable / path-based install: correct
    except ValueError:
        pass

    # Not under src/.  That is only acceptable if it is an editable
    # pointer (a .pth redirect), not a copied directory.
    sp = installed.parent.parent
    editable = list(sp.glob("__editable__*wiseq*.pth"))
    assert editable, (
        f"The installed package is a COPY at {installed}, not the source "
        f"tree at {src}. Edits to src/ will not be visible to anything "
        f"that imports the installed package. "
        f"Fix: .venv/bin/pip install -e '.[dev]'")


def test_the_api_module_resolves_to_the_source_tree():
    import wiseq.api

    installed = Path(wiseq.api.__file__).resolve()
    src = (REPO / "src").resolve()
    try:
        installed.relative_to(src)
        return
    except ValueError:
        pass
    sp = installed.parent.parent
    editable = list(sp.glob("__editable__*wiseq*.pth"))
    assert editable, (
        f"wiseq.api is a stale copy at {installed}; install editable.")


def test_every_new_route_is_present_in_the_imported_app():
    """Guards the specific regression: routes added to src but not served."""
    from wiseq.api import app

    paths = {getattr(r, "path", None) for r in app.routes}
    for expected in ("/strikes", "/strikes/record", "/stock-price-guard",
                     "/school/class-set-sizing", "/school/warranty-decision",
                     "/prices/sync-shopify", "/prices/sync-ucp"):
        assert expected in paths, f"route {expected} missing from the app"
