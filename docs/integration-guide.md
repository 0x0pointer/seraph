# SKF Guard — Integration Guide

This guide walks you through integrating SKF Guard into any application that uses an LLM. You will scan user input before it reaches the model, and scan the model's output before it reaches the user.

---

## How It Works

```
User Input
    │
    ▼
┌──────────────────────────┐
│  POST /api/scan/prompt   │  ← SKF Guard input scan
│  Authorization: Bearer   │
│  <connection key>        │
└──────────┬───────────────┘
           │ is_valid: true → pass through
           │ is_valid: false → block, return error to user
           ▼
     Your LLM (OpenAI, Anthropic, etc.)
           │
           ▼
┌──────────────────────────┐
│  POST /api/scan/output   │  ← SKF Guard output scan
│  Authorization: Bearer   │
│  <connection key>        │
└──────────┬───────────────┘
           │ is_valid: true → return response to user
           │ is_valid: false → block, do not show to user
           ▼
     User receives safe response
```

---

## Prerequisites

1. SKF Guard backend running (`uvicorn app.main:app --port 8000`)
2. A connection API key — create one in the dashboard under **Connections**

---

## Step 1 — Create a Connection

Log in to the dashboard at `http://localhost:3000`, go to **Connections**, and create a new connection. Copy the generated key — it looks like:

```
ts_conn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

This key is used as the `Authorization: Bearer` header for all scan calls. Each connection can have its own set of active guardrails.

---

## Step 2 — Scan User Input

Before sending the user's message to your LLM, send it to SKF Guard:

### cURL

```bash
curl -X POST http://localhost:8000/api/scan/prompt \
  -H "Authorization: Bearer YOUR_CONNECTION_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "How do I make a bomb?"}'
```

### Python

```python
import requests

SKFGUARD_URL = "http://localhost:8000"
CONNECTION_KEY = "YOUR_CONNECTION_KEY"

def scan_input(user_message: str) -> dict:
    resp = requests.post(
        f"{SKFGUARD_URL}/api/scan/prompt",
        json={"text": user_message},
        headers={"Authorization": f"Bearer {CONNECTION_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

result = scan_input("How do I make a bomb?")

if not result["is_valid"]:
    print("Blocked:", result["violation_scanners"])
else:
    safe_text = result["sanitized_text"]
    # → send safe_text to your LLM
```

### Node.js / TypeScript

```typescript
const SKFGUARD_URL = "http://localhost:8000";
const CONNECTION_KEY = "YOUR_CONNECTION_KEY";

async function scanInput(userMessage: string) {
  const res = await fetch(`${SKFGUARD_URL}/api/scan/prompt`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${CONNECTION_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text: userMessage }),
  });

  if (!res.ok) throw new Error(`SKF Guard error: ${res.status}`);
  return res.json();
}

const result = await scanInput("How do I make a bomb?");

if (!result.is_valid) {
  return { error: "Your message was blocked by safety guardrails.", violations: result.violation_scanners };
}

const safeText = result.sanitized_text;
// → send safeText to your LLM
```

### Response Schema

```json
{
  "is_valid": false,
  "sanitized_text": "How do I make a bomb?",
  "scanner_results": {
    "PromptInjection": { "is_valid": true,  "score": 0.01 },
    "BanTopics":       { "is_valid": false, "score": 0.94 },
    "Toxicity":        { "is_valid": true,  "score": 0.12 }
  },
  "violation_scanners": ["BanTopics"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `is_valid` | bool | `false` = blocked, `true` = safe to proceed |
| `sanitized_text` | string | Input text after any redaction (e.g. Secrets scanner) |
| `scanner_results` | object | Per-scanner verdict and risk score (0–1) |
| `violation_scanners` | array | Names of scanners that triggered |

---

## Step 3 — Scan LLM Output

After receiving the model's response, scan it before returning to the user:

### Python

```python
def scan_output(ai_response: str, original_prompt: str) -> dict:
    resp = requests.post(
        f"{SKFGUARD_URL}/api/scan/output",
        json={"text": ai_response, "prompt": original_prompt},
        headers={"Authorization": f"Bearer {CONNECTION_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

output_result = scan_output(ai_response, user_message)

if not output_result["is_valid"]:
    return {"error": "The AI response was blocked by safety guardrails."}

final_response = output_result["sanitized_text"]
```

### Node.js / TypeScript

```typescript
async function scanOutput(aiResponse: string, originalPrompt: string) {
  const res = await fetch(`${SKFGUARD_URL}/api/scan/output`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${CONNECTION_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text: aiResponse, prompt: originalPrompt }),
  });

  if (!res.ok) throw new Error(`SKF Guard error: ${res.status}`);
  return res.json();
}

const outputResult = await scanOutput(aiResponse, userMessage);

if (!outputResult.is_valid) {
  return { error: "The AI response was blocked by safety guardrails." };
}

const finalResponse = outputResult.sanitized_text;
```

---

## Step 4 — Full Integration Example

### Python (OpenAI)

```python
import os
import requests
from openai import OpenAI

SKFGUARD_URL = os.getenv("SKF_GUARD_API_URL", "http://localhost:8000")
CONNECTION_KEY = os.getenv("SKF_GUARD_CONNECTION_KEY", "")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _skf_headers():
    return {"Authorization": f"Bearer {CONNECTION_KEY}", "Content-Type": "application/json"}

def chat(user_message: str) -> dict:
    # 1. Scan input
    input_result = requests.post(
        f"{SKFGUARD_URL}/api/scan/prompt",
        json={"text": user_message},
        headers=_skf_headers(),
        timeout=30,
    ).json()

    if not input_result.get("is_valid", True):
        return {
            "blocked": True,
            "direction": "input",
            "violations": input_result["violation_scanners"],
            "message": "Your message was blocked by safety guardrails.",
        }

    safe_input = input_result.get("sanitized_text") or user_message

    # 2. Call LLM
    completion = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user",   "content": safe_input},
        ],
    )
    ai_response = completion.choices[0].message.content or ""

    # 3. Scan output
    output_result = requests.post(
        f"{SKFGUARD_URL}/api/scan/output",
        json={"text": ai_response, "prompt": safe_input},
        headers=_skf_headers(),
        timeout=30,
    ).json()

    if not output_result.get("is_valid", True):
        return {
            "blocked": True,
            "direction": "output",
            "violations": output_result["violation_scanners"],
            "message": "The AI response was blocked by safety guardrails.",
        }

    return {
        "blocked": False,
        "response": output_result.get("sanitized_text") or ai_response,
    }
```

### Node.js / TypeScript (OpenAI)

```typescript
import OpenAI from "openai";

const SKF_GUARD_URL = process.env.SKF_GUARD_API_URL ?? "http://localhost:8000";
const CONNECTION_KEY = process.env.SKF_GUARD_CONNECTION_KEY ?? "";
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const skfHeaders = {
  "Authorization": `Bearer ${CONNECTION_KEY}`,
  "Content-Type": "application/json",
};

async function chat(userMessage: string) {
  // 1. Scan input
  const inputRes = await fetch(`${SKF_GUARD_URL}/api/scan/prompt`, {
    method: "POST", headers: skfHeaders,
    body: JSON.stringify({ text: userMessage }),
  });
  const inputResult = await inputRes.json();

  if (!inputResult.is_valid) {
    return { blocked: true, direction: "input", violations: inputResult.violation_scanners };
  }

  const safeInput = inputResult.sanitized_text || userMessage;

  // 2. Call LLM
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: "You are a helpful assistant." },
      { role: "user",   content: safeInput },
    ],
  });
  const aiResponse = completion.choices[0].message.content ?? "";

  // 3. Scan output
  const outputRes = await fetch(`${SKF_GUARD_URL}/api/scan/output`, {
    method: "POST", headers: skfHeaders,
    body: JSON.stringify({ text: aiResponse, prompt: safeInput }),
  });
  const outputResult = await outputRes.json();

  if (!outputResult.is_valid) {
    return { blocked: true, direction: "output", violations: outputResult.violation_scanners };
  }

  return { blocked: false, response: outputResult.sanitized_text || aiResponse };
}
```

---

## Per-Connection Guardrails

Each connection key can have its own set of active guardrails, independent of the global defaults.

In the dashboard: **Connections → select a connection → Guardrails tab**

You can enable/disable any scanner and override thresholds per connection. This lets you run different scanner profiles for:
- Internal tools (looser rules)
- Customer-facing products (stricter rules)
- Experimental integrations (custom rule sets)

Via API:

```bash
# List guardrails for a connection
GET /api/connections/{connection_id}/guardrails

# Update guardrails for a connection
PUT /api/connections/{connection_id}/guardrails
Content-Type: application/json
Authorization: Bearer YOUR_JWT_TOKEN

{
  "guardrail_ids": [1, 2, 5, 8]
}
```

---

## Handling Blocked Requests

When `is_valid` is `false`, always show the user a clear message. Never silently drop their input or show a generic error.

### Recommended response structure

```json
{
  "error": "Your message was blocked by safety guardrails.",
  "blocked_by": ["BanTopics", "PromptInjection"],
  "direction": "input"
}
```

For output blocks, do not return the raw AI response. Show a fallback message instead:

```
"The AI's response was blocked. Please try rephrasing your question."
```

---

## Audit Log

Every scan is automatically logged. Access the full audit trail at:

```
GET /api/audit
Authorization: Bearer YOUR_JWT_TOKEN
```

Or browse it in the dashboard under **Audit Log**. Each entry contains:
- Timestamp
- Direction (input / output)
- Scanner results (per-scanner verdict and score)
- Violation scanners
- Token count
- Connection key identifier

---

## Self-Hosting Checklist

- [ ] Set a strong `SECRET_KEY` in `backend/.env`
- [ ] Set `ADMIN_PASSWORD` before running `seed.py`
- [ ] Configure `CORS_ORIGINS` to only include your frontend domain
- [ ] Set up SMTP for password-reset emails
- [ ] Run behind a reverse proxy (nginx/Caddy) with TLS in production
- [ ] Rotate connection keys periodically
- [ ] Back up `skfguard.db` regularly (or migrate to PostgreSQL for production)

---

## SDK / Library Wrappers

SKF Guard uses a plain HTTP API — no SDK required. Use any HTTP client:

| Language | Recommended client |
|---|---|
| Python | `requests`, `httpx` |
| Node.js / TypeScript | `fetch`, `axios` |
| Go | `net/http` |
| Ruby | `faraday`, `net/http` |
| PHP | `Guzzle`, `curl` |
| Rust | `reqwest` |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `401 Unauthorized` | Wrong or missing connection key | Check `Authorization: Bearer <key>` header |
| `422 Unprocessable Entity` | Missing `text` field in request body | Ensure body is `{"text": "..."}` |
| `503 Service Unavailable` | Scanner model loading (cold start) | Wait 10–30 s for ONNX models to warm up |
| All scans return `is_valid: true` | No scanners active on connection | Enable scanners in Dashboard → Connections → Guardrails |
| Slow scan times | ONNX not being used | Ensure `use_onnx: true` in scanner params and `onnxruntime` is installed |
