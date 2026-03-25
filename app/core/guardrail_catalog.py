"""
Backward-compatibility shim.

The catalog is now split into individual scanner files under
app/core/guardrails/input/ and app/core/guardrails/output/.
"""
from app.core.guardrails import GUARDRAIL_CATALOG  # noqa: F401

__all__ = ["GUARDRAIL_CATALOG"]
