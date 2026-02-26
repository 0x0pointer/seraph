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
