"""Test for app/core/guardrail_catalog.py — import and basic structure."""


class TestGuardrailCatalog:
    def test_catalog_is_nonempty_list(self):
        from app.core.guardrail_catalog import GUARDRAIL_CATALOG

        assert isinstance(GUARDRAIL_CATALOG, list)
        assert len(GUARDRAIL_CATALOG) > 0

    def test_catalog_entries_have_required_keys(self):
        from app.core.guardrail_catalog import GUARDRAIL_CATALOG

        for entry in GUARDRAIL_CATALOG:
            assert "scanner_type" in entry
            assert "direction" in entry
            assert entry["direction"] in ("input", "output")
