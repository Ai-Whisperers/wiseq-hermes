"""Ingest loads the client's REAL master data (counts asserted against the repo)."""
from wiseq.db.db import Database


def test_components_loaded(loaded):
    n = loaded.scalar("SELECT COUNT(*) FROM components")
    assert n == 114, f"expected 114 decoded component SKUs, got {n}"


def test_bundles_loaded(loaded):
    n = loaded.scalar("SELECT COUNT(*) FROM bundles")
    assert n == 25, f"expected 25 bundles, got {n}"


def test_bundle_components_are_json_lists(loaded):
    import json
    rows = loaded.query("SELECT bundle_key, component_skus FROM bundles")
    for r in rows:
        comps = json.loads(r["component_skus"])
        assert isinstance(comps, list)
        assert comps, f"{r['bundle_key']} has no components"


def test_bundle_keys_normalised(loaded):
    """'117 + 240' must normalise to '117+240'."""
    keys = {r["bundle_key"] for r in loaded.query("SELECT bundle_key FROM bundles")}
    assert "117+240" in keys
    assert not any(" " in k for k in keys)


def test_shipping_rules_loaded(loaded):
    n = loaded.scalar("SELECT COUNT(*) FROM shipping_rules")
    assert n == 15, f"expected 15 shipping-rule templates, got {n}"


def test_unvalidated_rules_are_flagged(loaded):
    """The 3 problematic rules must NOT be silently marked OK."""
    rows = loaded.query(
        "SELECT category, validation_status FROM shipping_rules "
        "WHERE validation_status != 'OK'")
    assert len(rows) >= 3, "expected at least 3 non-OK rules"
    categories = {r["category"] for r in rows}
    assert "USB HUBS" in categories
    assert "Smartwatch" in categories
    assert "Tag" in categories


def test_tariffs_loaded_with_be_costs(loaded):
    n = loaded.scalar("SELECT COUNT(*) FROM shipping_tariffs")
    assert n > 0
    be = loaded.query("SELECT * FROM shipping_tariffs WHERE country='BE'")
    assert be, "expected Belgium tariffs"


def test_products_created_from_components_and_bundles(loaded):
    products = loaded.scalar("SELECT COUNT(*) FROM products")
    assert products == 139, f"expected 114 components + 25 bundles, got {products}"


def test_ean_registry_has_missing_entries(loaded):
    """The whole point: EAN coverage starts incomplete and is measurable."""
    missing = loaded.scalar(
        "SELECT COUNT(*) FROM ean_registry WHERE status='missing'")
    assert missing > 0


def test_ingest_is_idempotent(loaded, repo_dir):
    from wiseq.ingest.loaders import load_all
    before = loaded.scalar("SELECT COUNT(*) FROM products")
    load_all(loaded, repo_dir)
    after = loaded.scalar("SELECT COUNT(*) FROM products")
    assert before == after, "re-running ingest duplicated rows"


def test_synthetic_price_flag_set(loaded):
    assert loaded.scalar(
        "SELECT COUNT(*) FROM products WHERE synthetic_price=1") > 0
