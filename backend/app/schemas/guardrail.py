from datetime import datetime
from pydantic import BaseModel


class GuardrailCreate(BaseModel):
    name: str
    scanner_type: str
    direction: str  # input | output
    is_active: bool = True
    on_fail_action: str = "block"  # block | fix | monitor | reask
    params: dict = {}
    order: int = 0


class GuardrailUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    on_fail_action: str | None = None
    params: dict | None = None
    order: int | None = None


class GuardrailRead(BaseModel):
    id: int
    name: str
    scanner_type: str
    direction: str
    is_active: bool
    on_fail_action: str
    params: dict
    order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
