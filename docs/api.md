# Seraph — REST API Reference

Base URL: `https://seraph.io/api`

All protected endpoints require a JWT Bearer token (obtained from `/auth/login`) or a static API key (from `/auth/api-token`):

```
Authorization: Bearer <token>
```

---

## Authentication

### POST /auth/login
Login with username and password. Returns a JWT.

**Request:**
```json
{ "username": "admin", "password": "your-password" }
```

**Response:**
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

---

### POST /auth/register
Register a new user account. Requires a valid Cloudflare Turnstile token.

**Request:**
```json
{
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "username": "janedoe",
  "password": "strongpassword123",
  "turnstile_token": "..."
}
```

**Response:** `201 Created` — `TokenResponse`

---

### GET /auth/me
Returns the currently authenticated user.

**Response:**
```json
{
  "id": 1,
  "username": "admin",
  "full_name": "Administrator",
  "email": "admin@example.com",
  "role": "admin",
  "org_id": null,
  "team_id": null
}
```

---

### PATCH /auth/me
Update own profile (username, full_name, email).

**Request:**
```json
{ "full_name": "New Name", "email": "new@example.com" }
```

---

### POST /auth/change-password
Change the authenticated user's password.

**Request:**
```json
{ "current_password": "oldpass", "new_password": "newpass123456" }
```

Minimum 12 characters. Returns `400` if current password is wrong.

---

### POST /auth/api-token
Get the user's static API key (generates one if it doesn't exist).

**Response:**
```json
{ "api_token": "ts_live_abc123...", "created": true }
```

---

### POST /auth/api-token/regenerate
Invalidate the current API key and issue a new one.

---

### POST /auth/forgot-password
Send a password reset email (requires SMTP configured).

**Request:** `{ "email": "user@example.com" }`

Always returns `202` to prevent email enumeration.

---

### POST /auth/reset-password
Reset password using a token from the reset email.

**Request:** `{ "token": "...", "new_password": "newpassword123" }`

---

## Scanning

### POST /scan/prompt
Scan a user input through all active **input** guardrails. Authenticate with your static API key.

**Request:**
```json
{ "text": "How do I hack into a system?" }
```

**Response:**
```json
{
  "is_valid": false,
  "sanitized_text": "How do I hack into a system?",
  "scanner_results": {
    "PromptInjection": { "is_valid": true, "score": 0.12 },
    "BanTopics":       { "is_valid": false, "score": 0.91 }
  },
  "violation_scanners": ["BanTopics"],
  "audit_log_id": 42
}
```

---

### POST /scan/output
Scan an LLM response through all active **output** guardrails.

**Request:**
```json
{
  "text": "Here is how you can build a weapon...",
  "prompt": "How do I build a weapon?"
}
```

**Response:** Same shape as `/scan/prompt`.

---

## Guardrails

### GET /guardrails
List all guardrail configurations (JWT required).

**Response:** Array of `GuardrailConfig` objects.

---

### POST /guardrails
Create a new guardrail configuration.

**Request:**
```json
{
  "name": "Custom Toxicity Filter",
  "scanner_type": "Toxicity",
  "direction": "input",
  "is_active": true,
  "params": { "threshold": 0.7 },
  "order": 99
}
```

---

### PUT /guardrails/{id}
Update a guardrail (name, params, is_active, order).

---

### DELETE /guardrails/{id}
Delete a guardrail. Returns `204 No Content`.

---

### PATCH /guardrails/{id}/toggle
Toggle the `is_active` state of a guardrail.

---

## Connections (API Keys)

### GET /connections
List API connections belonging to the authenticated user.

---

### POST /connections
Create a new API connection.

**Request:**
```json
{ "name": "My App", "environment": "production" }
```

---

### DELETE /connections/{id}
Delete a connection and revoke its key.

---

### GET /connections/{id}/guardrails
List all guardrails and whether each is enabled for this connection.

**Response:**
```json
[
  {
    "id": 1,
    "name": "Prompt Injection Detector",
    "scanner_type": "PromptInjection",
    "direction": "input",
    "is_active": true,
    "enabled_for_conn": true
  }
]
```

---

### PUT /connections/{id}/guardrails
Set which guardrails apply to this connection.

**Request:**
```json
{
  "use_custom_guardrails": true,
  "guardrail_ids": [1, 3, 7]
}
```

When `use_custom_guardrails` is `false`, all globally active guardrails apply.

---

## Audit Logs

### GET /audit
Paginated audit log.

**Query params:**
- `page` (int, default 1)
- `page_size` (int, default 20, max 100)
- `direction` (`input` | `output`)
- `is_valid` (bool)
- `search` (string, max 200 chars)

**Response:**
```json
{
  "items": [...],
  "total": 1234,
  "page": 1,
  "page_size": 20
}
```

---

## Analytics

### GET /analytics/summary
Aggregate scan statistics.

**Response:**
```json
{
  "total_scans": 5000,
  "violations_today": 23,
  "avg_risk_score": 0.142,
  "active_guardrails": 6
}
```

---

### GET /analytics/trends?days=30
Daily scan and violation counts for the last N days.

**Response:** Array of `{ "date": "2026-02-26", "total": 120, "violations": 4 }`.

---

### GET /analytics/top-violations?limit=10
Most frequently triggered scanners.

**Response:** Array of `{ "scanner": "BanTopics", "count": 45 }`.

---

## Public

### GET /public/platform-info
Returns public platform info — no authentication required.

**Response:**
```json
{ "company_name": "Seraph", "chatbot_enabled": true }
```

---

## Error Responses

| Status | Meaning |
|--------|---------|
| `400` | Bad request (e.g. wrong current password) |
| `401` | Missing or invalid token |
| `403` | Insufficient permissions |
| `404` | Resource not found |
| `413` | Request body too large (max 1 MB) |
| `422` | Validation error (e.g. password too short) |
| `503` | Maintenance mode active |
