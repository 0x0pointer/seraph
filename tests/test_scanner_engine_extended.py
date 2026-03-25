"""Extended unit tests for app/services/scanner_engine.py — uncovered branches."""
import asyncio
import concurrent.futures
from unittest.mock import patch, MagicMock

_run = lambda coro: asyncio.run(coro)


class TestGetExecutor:
    def test_creates_executor_lazily(self):
        import app.services.scanner_engine as se

        saved = se._executor
        try:
            se._executor = None
            executor = se._get_executor()
            assert isinstance(executor, concurrent.futures.ThreadPoolExecutor)
            assert se._executor is executor
        finally:
            se._executor = saved

    def test_returns_existing_executor(self):
        import app.services.scanner_engine as se

        saved = se._executor
        try:
            fake = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            se._executor = fake
            assert se._get_executor() is fake
        finally:
            se._executor = saved
            fake.shutdown(wait=False)


class TestGetVault:
    def test_creates_vault_lazily(self):
        import app.services.scanner_engine as se

        saved = se._vault
        try:
            se._vault = None
            vault = se._get_vault()
            assert vault is not None
            # Calling again returns same instance
            assert se._get_vault() is vault
        finally:
            se._vault = saved

    def test_returns_existing_vault(self):
        import app.services.scanner_engine as se

        saved = se._vault
        try:
            fake_vault = MagicMock()
            se._vault = fake_vault
            assert se._get_vault() is fake_vault
        finally:
            se._vault = saved


class TestBuildScannerAnonymize:
    def test_anonymize_gets_vault_injected(self):
        from app.services.scanner_engine import _build_scanner

        mock_vault = MagicMock()
        mock_scanner = MagicMock(return_value="anon_instance")

        with patch("app.services.scanner_engine._get_vault", return_value=mock_vault):
            with patch("app.services.scanner_engine._import_scanner", mock_scanner) as mock_import:
                result = _build_scanner("Anonymize", "input", {"use_onnx": True})

        mock_import.assert_called_once_with(
            "Anonymize", "input", {"vault": mock_vault, "use_onnx": True}
        )

    def test_deanonymize_gets_vault_injected(self):
        from app.services.scanner_engine import _build_scanner

        mock_vault = MagicMock()
        mock_scanner = MagicMock(return_value="deanon_instance")

        with patch("app.services.scanner_engine._get_vault", return_value=mock_vault):
            with patch("app.services.scanner_engine._import_scanner", mock_scanner) as mock_import:
                result = _build_scanner("Deanonymize", "output", {})

        mock_import.assert_called_once_with(
            "Deanonymize", "output", {"vault": mock_vault}
        )

    def test_anonymize_and_deanonymize_share_vault(self):
        from app.services.scanner_engine import _build_scanner

        captured_vaults = []

        def capture_import(scanner_type, direction, params):
            captured_vaults.append(params.get("vault"))
            return MagicMock()

        mock_vault = MagicMock()
        with patch("app.services.scanner_engine._get_vault", return_value=mock_vault):
            with patch("app.services.scanner_engine._import_scanner", side_effect=capture_import):
                _build_scanner("Anonymize", "input", {})
                _build_scanner("Deanonymize", "output", {})

        assert len(captured_vaults) == 2
        assert captured_vaults[0] is captured_vaults[1]


class TestImportScanner:
    def test_import_scanner_success(self):
        from app.services.scanner_engine import _import_scanner

        mock_module = MagicMock()
        mock_class = MagicMock(return_value="scanner_instance")
        mock_module.FakeScanner = mock_class

        with patch("importlib.import_module", return_value=mock_module):
            result = _import_scanner("FakeScanner", "input", {"threshold": 0.5})

        assert result == "scanner_instance"
        mock_class.assert_called_once_with(threshold=0.5)

    def test_import_scanner_failure_raises(self):
        from app.services.scanner_engine import _import_scanner
        import pytest

        with patch("importlib.import_module", side_effect=ImportError("no module")):
            with pytest.raises(ImportError):
                _import_scanner("Missing", "input", {})

    def test_import_scanner_output_direction(self):
        from app.services.scanner_engine import _import_scanner

        mock_module = MagicMock()
        mock_class = MagicMock(return_value="out_instance")
        mock_module.OutScanner = mock_class

        with patch("importlib.import_module", return_value=mock_module) as mock_import:
            result = _import_scanner("OutScanner", "output", {})

        mock_import.assert_called_once_with("llm_guard.output_scanners")
        assert result == "out_instance"


class TestImportCustomScanner:
    def test_import_custom_scanner(self):
        from app.services.scanner_engine import _import_custom_scanner

        mock_cls = MagicMock(return_value="custom_instance")
        with patch(
            "app.services.custom_scanner.CustomRuleScanner", mock_cls
        ):
            result = _import_custom_scanner("input", {"blocked_keywords": ["x"]})

        assert result == "custom_instance"
        mock_cls.assert_called_once_with(direction="input", blocked_keywords=["x"])


class TestImportEmbeddingShield:
    def test_import_embedding_shield(self):
        from app.services.scanner_engine import _import_embedding_shield

        mock_cls = MagicMock(return_value="shield_instance")
        with patch(
            "app.services.embedding_shield.EmbeddingShield", mock_cls
        ):
            result = _import_embedding_shield({"threshold": 0.8})

        assert result == "shield_instance"
        mock_cls.assert_called_once_with(threshold=0.8)


class TestLoadScannersFromConfig:
    def test_loads_from_yaml_config(self):
        from app.services.scanner_engine import (
            _load_scanners_from_config,
            invalidate_cache,
        )
        from app.core.config import ScannerConfig

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners.input = [
            ScannerConfig(type="CustomRule", params={"blocked_keywords": ["bad"]})
        ]

        mock_scanner = MagicMock()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch(
                "app.services.scanner_engine._build_scanner",
                return_value=mock_scanner,
            ):
                entries = _load_scanners_from_config("input")

        assert len(entries) == 1
        assert entries[0][1] == "CustomRule"
        assert entries[0][5] == "block"
        invalidate_cache()

    def test_loads_from_yaml_config_with_threshold(self):
        from app.services.scanner_engine import (
            _load_scanners_from_config,
            invalidate_cache,
        )
        from app.core.config import ScannerConfig

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners.input = [
            ScannerConfig(
                type="Toxicity",
                threshold=0.7,
                params={},
                on_fail="monitor",
            )
        ]

        mock_scanner = MagicMock()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch(
                "app.services.scanner_engine._build_scanner",
                return_value=mock_scanner,
            ) as mock_build:
                entries = _load_scanners_from_config("input")

        assert len(entries) == 1
        assert entries[0][5] == "monitor"
        # threshold should have been injected into params
        call_params = mock_build.call_args[0][2]
        assert call_params.get("threshold") == 0.7
        invalidate_cache()

    def test_falls_back_to_guardrail_catalog(self):
        from app.services.scanner_engine import (
            _load_scanners_from_config,
            invalidate_cache,
        )

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners = None

        fake_catalog = [
            {
                "scanner_type": "Toxicity",
                "direction": "input",
                "is_active": True,
                "params": {"threshold": 0.5},
                "on_fail_action": "block",
            },
            {
                "scanner_type": "Other",
                "direction": "output",
                "is_active": True,
                "params": {},
                "on_fail_action": "monitor",
            },
        ]

        mock_scanner = MagicMock()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch(
                "app.core.guardrail_catalog.GUARDRAIL_CATALOG", fake_catalog
            ):
                with patch(
                    "app.services.scanner_engine._build_scanner",
                    return_value=mock_scanner,
                ):
                    entries = _load_scanners_from_config("input")

        # Only the input scanner should be loaded
        assert len(entries) == 1
        assert entries[0][1] == "Toxicity"
        invalidate_cache()

    def test_skips_scanner_on_build_error(self):
        from app.services.scanner_engine import (
            _load_scanners_from_config,
            invalidate_cache,
        )
        from app.core.config import ScannerConfig

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners.output = [
            ScannerConfig(type="BadScanner", params={}),
        ]

        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch(
                "app.services.scanner_engine._build_scanner",
                side_effect=Exception("build failed"),
            ):
                entries = _load_scanners_from_config("output")

        assert len(entries) == 0
        invalidate_cache()

    def test_cache_hit_returns_cached(self):
        from app.services.scanner_engine import (
            _load_scanners_from_config,
            invalidate_cache,
            _cache,
            _cache_valid,
        )

        invalidate_cache()

        sentinel = [("fake_scanner", "FakeType", [], 0, {}, "block")]
        _cache["input"] = sentinel
        _cache_valid.add("input")

        result = _load_scanners_from_config("input")
        assert result is sentinel
        invalidate_cache()


class TestReloadScanners:
    def test_reload_invalidates_cache(self):
        from app.services.scanner_engine import (
            reload_scanners,
            _cache,
            _cache_valid,
        )

        _cache["input"] = [("x",)]
        _cache_valid.add("input")

        reload_scanners()

        assert len(_cache) == 0
        assert len(_cache_valid) == 0


class TestWarmup:
    def test_warmup_calls_scans(self):
        from app.services.scanner_engine import warmup

        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=MagicMock,
        ) as mock_input, patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=MagicMock,
        ) as mock_output:
            # Make them return coroutines
            async def fake_input(text):
                return (True, text, {}, [], {}, None, False)

            async def fake_output(prompt, output):
                return (True, output, {}, [], {}, None, False)

            mock_input.side_effect = fake_input
            mock_output.side_effect = fake_output

            _run(warmup())

        mock_input.assert_called_once_with("warmup check")
        mock_output.assert_called_once_with("warmup check", "warmup check")

    def test_warmup_handles_input_failure(self):
        from app.services.scanner_engine import warmup

        async def fail_input(text):
            raise RuntimeError("input model broken")

        async def ok_output(prompt, output):
            return (True, output, {}, [], {}, None, False)

        with patch(
            "app.services.scanner_engine.run_input_scan",
            side_effect=fail_input,
        ), patch(
            "app.services.scanner_engine.run_output_scan",
            side_effect=ok_output,
        ):
            # Should not raise
            _run(warmup())

    def test_warmup_handles_output_failure(self):
        from app.services.scanner_engine import warmup

        async def ok_input(text):
            return (True, text, {}, [], {}, None, False)

        async def fail_output(prompt, output):
            raise RuntimeError("output model broken")

        with patch(
            "app.services.scanner_engine.run_input_scan",
            side_effect=ok_input,
        ), patch(
            "app.services.scanner_engine.run_output_scan",
            side_effect=fail_output,
        ):
            _run(warmup())


class TestRunInputScanNoEntries:
    def test_no_entries_returns_valid(self):
        from app.services.scanner_engine import run_input_scan, invalidate_cache

        invalidate_cache()

        with patch(
            "app.services.scanner_engine._load_scanners_from_config",
            return_value=[],
        ):
            result = _run(run_input_scan("hello"))

        assert result == (True, "hello", {}, [], {}, None, False)
        invalidate_cache()


class TestRunOutputScanNoEntries:
    def test_no_entries_returns_valid(self):
        from app.services.scanner_engine import run_output_scan, invalidate_cache

        invalidate_cache()

        with patch(
            "app.services.scanner_engine._load_scanners_from_config",
            return_value=[],
        ):
            result = _run(run_output_scan("prompt", "output"))

        assert result == (True, "output", {}, [], {}, None, False)
        invalidate_cache()
