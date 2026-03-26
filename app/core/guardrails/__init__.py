"""
Auto-discovers scanner definitions from input/ and output/ subpackages
and assembles the unified GUARDRAIL_CATALOG list.

Each scanner file exports a SCANNER dict with: name, scanner_type,
on_fail_action, params, order. The loader injects 'direction' (from the
folder name) and 'is_active' (defaults to True — config.yaml is the
single source of truth for activation).
"""
import importlib
import pkgutil
from pathlib import Path


def _load_scanners(direction: str) -> list[dict]:
    """Import all scanner modules from a direction subpackage."""
    package_name = f"app.core.guardrails.{direction}"
    package_path = Path(__file__).parent / direction
    scanners = []
    for _finder, module_name, _is_pkg in pkgutil.iter_modules([str(package_path)]):
        mod = importlib.import_module(f"{package_name}.{module_name}")
        scanner_def = getattr(mod, "SCANNER", None)
        if scanner_def is not None:
            entry = {**scanner_def, "direction": direction, "is_active": True}
            scanners.append(entry)
    scanners.sort(key=lambda s: s.get("order", 999))
    return scanners


GUARDRAIL_CATALOG: list[dict] = _load_scanners("input") + _load_scanners("output")
