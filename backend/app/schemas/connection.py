from datetime import datetime

from pydantic import BaseModel, computed_field, field_validator


class ApiConnectionCreate(BaseModel):
    name: str
    environment: str = "production"
    alert_enabled: bool = False
    alert_threshold: int | None = None
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0
    monthly_alert_spend: float | None = None
    max_monthly_spend: float | None = None

    @field_validator("alert_threshold")
    @classmethod
    def validate_threshold(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("alert_threshold must be between 0 and 100")
        return v


class ApiConnectionUpdate(BaseModel):
    name: str | None = None
    environment: str | None = None
    alert_enabled: bool | None = None
    alert_threshold: int | None = None
    cost_per_input_token: float | None = None
    cost_per_output_token: float | None = None
    monthly_alert_spend: float | None = None
    max_monthly_spend: float | None = None

    @field_validator("alert_threshold")
    @classmethod
    def validate_threshold(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("alert_threshold must be between 0 and 100")
        return v


class ApiConnectionRead(BaseModel):
    id: int
    name: str
    environment: str
    api_key: str
    status: str
    org_id: int | None = None
    created_by_username: str | None = None
    alert_enabled: bool
    alert_threshold: int | None
    use_custom_guardrails: bool = False
    total_requests: int
    total_violations: int
    cost_per_input_token: float
    cost_per_output_token: float
    monthly_alert_spend: float | None
    max_monthly_spend: float | None
    month_spend: float
    month_input_tokens: int
    month_output_tokens: int
    month_started_at: datetime | None
    created_at: datetime
    last_active_at: datetime | None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def violation_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.total_violations / self.total_requests * 100, 1)

    @computed_field
    @property
    def estimated_cost(self) -> float:
        """Legacy flat-rate estimate kept for backward compat."""
        return round(self.total_requests * 0.001, 4)

    @computed_field
    @property
    def spend_percentage(self) -> float | None:
        if self.monthly_alert_spend is None or self.monthly_alert_spend == 0:
            return None
        return (self.month_spend / self.monthly_alert_spend) * 100

    @computed_field
    @property
    def alert_spend_active(self) -> bool:
        pct = self.spend_percentage
        return pct is not None and pct >= 80

    @computed_field
    @property
    def spend_limit_reached(self) -> bool:
        pct = self.spend_percentage
        return pct is not None and pct >= 100

    @computed_field
    @property
    def max_spend_reached(self) -> bool:
        return self.max_monthly_spend is not None and self.month_spend >= self.max_monthly_spend


class ConnectionGuardrailItem(BaseModel):
    id: int
    name: str
    scanner_type: str
    direction: str
    is_active: bool
    enabled_for_conn: bool
    threshold_override: float | None = None
    model_config = {"from_attributes": False}


class GuardrailSelection(BaseModel):
    id: int
    threshold_override: float | None = None


class ConnectionGuardrailsUpdate(BaseModel):
    use_custom_guardrails: bool
    guardrails: list[GuardrailSelection]
