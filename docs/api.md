# Talix Shield — REST API Reference

Base URL: `http://localhost:8000/api`

All protected endpoints require a Bearer token in the Authorization header:
```
Authorization: Bearer <token>
```

---

## Authentication

### POST /auth/login
Login with username and password.

**Request:**
```json
{ "username": "admin", "password": "admin" }
```

**Response:**
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

### GET /auth/me
Returns the current authenticated user.

**Response:**
```json
{ "id": 1, "username": "admin", "role": "admin" }
```

---

## Guardrails

### GET /guardrails
List all guardrail configurations.

**Response:** Array of GuardrailConfig objects.

### POST /guardrails
Create a new guardrail configuration.

**Request:**
```json
{
  "name": "Toxicity Filter",
  "scanner_type": "Toxicity",
  "direction": "input",
  "is_active": true,
  "params": { "threshold": 0.7 },
  "order": 1
}
```

### PUT /guardrails/{id}
Update a guardrail configuration.

**Request body:** Same as POST, all fields optional.

### DELETE /guardrails/{id}
Delete a guardrail configuration. Returns 204 No Content.

### PATCH /guardrails/{id}/toggle
Toggle the active state of a guardrail. Returns updated config.

---

## Scanning

### POST /scan/prompt
Scan an input prompt through all active input guardrails.

**Request:**
```json
{ "text": "How do I hack into a system?" }
```

**Response:**
```json
{
  "is_valid": false,
  "sanitized_text": "How do I [REDACTED]?",
  "scanner_results": { "PromptInjection": 0.95, "Toxicity": 0.2 },
  "violation_scanners": ["PromptInjection"],
  "audit_log_id": 42
}
```

### POST /scan/output
Scan an LLM output through all active output guardrails.

**Request:**
```json
{
  "text": "Here is how you can...",
  "prompt": "The original user prompt"
}
```

**Response:** Same shape as `/scan/prompt`.

---

## Audit Logs

### GET /audit
List audit logs with pagination and filtering.

**Query params:**
- `page` (int, default 1)
- `page_size` (int, default 20, max 100)
- `direction` (string: "input" | "output")
- `is_valid` (bool)

**Response:**
```json
{
  "items": [...],
  "total": 1234,
  "page": 1,
  "page_size": 20
}
```

### GET /audit/abuse
Same as `/audit` but pre-filtered to `is_valid=false` (violations only).

---

## Analytics

### GET /analytics/summary
Returns aggregate statistics.

**Response:**
```json
{
  "total_scans": 5000,
  "violations_today": 23,
  "avg_risk_score": 0.142,
  "active_guardrails": 6
}
```

### GET /analytics/trends?days=30
Returns daily scan/violation counts for the last N days.

**Response:** Array of `{ date, total, violations }` objects.

### GET /analytics/top-violations?limit=10
Returns the most frequently triggered scanners.

**Response:** Array of `{ scanner, count }` objects.
