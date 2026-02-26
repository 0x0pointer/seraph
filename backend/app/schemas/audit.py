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


class AuditLogList(BaseModel):
    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int
