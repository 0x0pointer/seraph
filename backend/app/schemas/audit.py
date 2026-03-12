from datetime import datetime
from pydantic import BaseModel, computed_field


class AuditLogRead(BaseModel):
    id: int
    direction: str
    raw_text: str
    sanitized_text: str | None
    is_valid: bool
    scanner_results: dict
    violation_scanners: list
    ip_address: str | None
    connection_id: int | None
    connection_name: str | None
    connection_environment: str | None
    input_tokens: int | None
    output_tokens: int | None
    token_cost: float | None
    org_id: int | None = None
    user_id: int | None = None
    team_id: int | None = None
    created_at: datetime
    # Guardrails AI-inspired action metadata
    on_fail_actions: dict | None = None    # scanner_name → action taken
    fix_applied: bool = False              # text was sanitized by a fix-action scanner
    reask_context: list | None = None     # correction instructions for reask-action violations

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def max_risk_score(self) -> float:
        if not self.scanner_results:
            return 0.0
        vals = [v for v in self.scanner_results.values() if isinstance(v, (int, float))]
        return round(max(vals, default=0.0), 3)

    @computed_field
    @property
    def scanner_count(self) -> int:
        return len(self.scanner_results)

    @computed_field
    @property
    def outcome(self) -> str:
        """Human-readable outcome: pass | fixed | blocked | reask | monitored."""
        actions = self.on_fail_actions or {}
        if not self.is_valid:
            if any(v == "reask" for v in actions.values()):
                return "reask"
            return "blocked"
        if self.fix_applied:
            return "fixed"
        monitored = [k for k, v in actions.items() if v == "monitored"]
        if monitored:
            return "monitored"
        return "pass"


class AuditLogList(BaseModel):
    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int
