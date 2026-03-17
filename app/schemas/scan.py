from pydantic import BaseModel


class ScanRequest(BaseModel):
    text: str
    prompt: str | None = None  # Required for output scan (original prompt)


class ScanResponse(BaseModel):
    is_valid: bool
    sanitized_text: str
    scanner_results: dict[str, float]
    violation_scanners: list[str]
    on_fail_actions: dict[str, str] = {}
    monitored_scanners: list[str] = []
    reask_context: list[str] | None = None
    fix_applied: bool = False


class Message(BaseModel):
    role: str   # system | user | assistant | tool
    content: str


class GuardRequest(BaseModel):
    messages: list[Message]
    breakdown: bool = False


class DetectorResult(BaseModel):
    detector: str
    flagged: bool
    score: float = 0.0


class GuardResponse(BaseModel):
    flagged: bool
    metadata: dict                      # {"request_uuid": str}
    breakdown: list[DetectorResult] | None = None
    scanner_results: dict[str, float]
    violation_scanners: list[str]
