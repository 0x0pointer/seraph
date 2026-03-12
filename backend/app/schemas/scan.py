from pydantic import BaseModel


class ScanRequest(BaseModel):
    text: str
    prompt: str | None = None  # Required for output scan (original prompt)
    input_tokens: int | None = None   # If omitted, estimated as len(text) // 4
    output_tokens: int | None = None  # If omitted, estimated as 0


class ScannerResult(BaseModel):
    name: str
    score: float
    is_valid: bool


class ScanResponse(BaseModel):
    is_valid: bool
    sanitized_text: str
    scanner_results: dict[str, float]
    violation_scanners: list[str]
    audit_log_id: int
    # Guardrails AI-inspired action metadata
    on_fail_actions: dict[str, str] = {}     # scanner_name → action taken (blocked/fixed/monitored/reask)
    monitored_scanners: list[str] = []       # violations logged but allowed through (monitor action)
    reask_context: list[str] | None = None   # correction instructions for reask-action violations
    fix_applied: bool = False                # True if at least one scanner sanitized the text


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
    audit_log_id: int | None = None
