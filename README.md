# Project 73 — LLM Security Platform

**Production-ready guardrails for Large Language Models**

Project 73 wraps the llm-guard scanner library with a FastAPI backend, SQLite-persisted configuration, audit logging, multi-tenant org support, and a full Next.js admin dashboard + marketing site.

> **Status:** Beta

---

## Features

| Area | Details |
|------|---------|
| **39 scanners** | 16 input + 23 output scanners via llm-guard |
| **REST API** | FastAPI backend with JWT auth + connection API keys |
| **Per-connection guardrails** | Choose exactly which scanners run per API key |
| **Dynamic config** | Enable/disable and tune scanners live — no redeployment |
| **Audit log** | Every scan logged with full scanner breakdown & token costs |
| **Analytics** | Violation trends, top scanners, risk scores, spend tracking |
| **Multi-tenant** | Organisations, teams, roles (`admin`, `org_admin`, `viewer`) |
| **Admin panel** | Super-admin UI — manage users, orgs, platform settings |
| **Stripe billing** | Checkout, billing portal, webhooks — Free / Starter / Pro / Enterprise |
| **Chatbot demo** | Embedded Flask chatbot showing guardrails in action |
| **Marketing site** | Public-facing landing page, docs, pricing, terms, privacy |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│               Frontend  (Next.js 14 — port 3000)            │
│   Marketing Site (/)    │   Admin Dashboard (/dashboard)     │
└────────────────────────────────┬────────────────────────────┘
                                 │  REST API  /api/*
┌────────────────────────────────▼────────────────────────────┐
│               Backend  (FastAPI — port 8000)                 │
│  /api/auth   /api/guardrails   /api/scan   /api/audit        │
│  /api/analytics   /api/connections   /api/admin              │
│  /api/org   /api/teams   /api/notifications                  │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────┐
│           Scanner Engine  (llm-guard — local install)        │
│  Loads active guardrail configs from DB on first request     │
│  Thread-pool executor; cache invalidated on config change    │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────┐
│                   SQLite  (project73.db)                     │
│  users · organizations · teams · guardrail_configs           │
│  api_connections · connection_guardrails · audit_logs        │
│  platform_settings · announcements · notifications           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              Chatbot Demo  (Flask — port 3001)               │
│  Proxies user messages through /api/scan before OpenAI call  │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

**Backend:** Python 3.11+, FastAPI, SQLAlchemy 2 (async), aiosqlite, Pydantic v2, python-jose, passlib[bcrypt], stripe

**Frontend:** Next.js 14 (App Router), TypeScript, Tailwind CSS, Recharts, SWR, js-cookie

**Chatbot:** Flask, OpenAI Python SDK

**Scanners:** llm-guard (local install from source)

---

## Project Structure

```
project73/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # REST endpoints (auth, scan, guardrails, admin …)
│   │   ├── core/             # Config, database, security, guardrail catalog
│   │   ├── models/           # SQLAlchemy ORM models
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   └── services/         # Scanner engine, email, billing
│   ├── seed.py               # DB seeder (creates admin user + guardrail configs)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/              # Next.js App Router pages
│       │   ├── (marketing)/  # Public marketing pages
│       │   ├── dashboard/    # Admin dashboard
│       │   ├── login/
│       │   └── register/
│       └── components/       # Shared UI components
├── chatbot/
│   ├── server.py             # Flask server
│   ├── index.html            # Chat UI
│   └── run.sh                # Start script
├── docs/
│   └── integration-guide.html  # Full integration guide (Mermaid diagrams)
└── docker-compose.yml
```

---

## Quick Start

### Option A — Docker Compose

```bash
docker-compose up --build
```

- Frontend: http://localhost:3000
- API + Swagger: http://localhost:8000/docs
- Chatbot: http://localhost:3001

Default admin username: `admin` — password set via `ADMIN_PASSWORD` env var (required in production).

---

### Option B — Manual (Recommended for Development)

#### Prerequisites

- Python 3.11+
- Node.js 18+
- The `llm-guard` source at `../llmguard/llm-guard` (relative to backend)

#### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and edit environment variables
cp .env.example .env
# → Set SECRET_KEY, TURNSTILE_SECRET_KEY, SMTP settings, etc.

uvicorn app.main:app --reload --port 8000
```

The DB (`project73.db`) is created automatically on first start.

#### 2. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

#### 3. Chatbot (optional)

```bash
cd chatbot
# Activate the backend venv or create a separate one
pip install flask python-dotenv openai requests

# Set env vars (or add to .env):
# OPENAI_API_KEY=sk-...
# TALIX_API_URL=http://localhost:8000
# TALIX_CONNECTION_KEY=<your api key>

python server.py   # http://localhost:3001
```

---

## Environment Variables

Create `backend/.env` (never commit this file):

```env
# Security — generate with: openssl rand -hex 32
SECRET_KEY=your-random-32-char-secret

# Database (default: SQLite)
DATABASE_URL=sqlite+aiosqlite:///./project73.db

# CORS — comma-separated list of allowed frontend origins
CORS_ORIGINS=["http://localhost:3000","https://project73.ai"]

# Cloudflare Turnstile (use test keys in dev)
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA

# Frontend URL (used in password-reset emails)
FRONTEND_URL=http://localhost:3000

# SMTP (leave smtp_host blank to disable email)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app-password
SMTP_FROM=noreply@project73.ai
SMTP_TLS=true

# Admin seed password (required in production — used by seed.py to create the admin account)
ADMIN_PASSWORD=your-strong-password

# JWT expiry in minutes (default: 1440 = 24h)
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Stripe billing (leave blank to disable billing features)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PRO=price_...
```

Create `chatbot/.env`:

```env
OPENAI_API_KEY=sk-...
TALIX_API_URL=http://localhost:8000
TALIX_CONNECTION_KEY=<connection key from dashboard>
OPENAI_MODEL=gpt-4o-mini
PORT=3001
```

---

## API Overview

All endpoints are prefixed with `/api`. Swagger UI available at `http://localhost:8000/docs`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/login` | — | Get JWT token |
| `POST` | `/api/auth/register` | — | Register new user |
| `GET` | `/api/auth/me` | JWT | Current user info |
| `POST` | `/api/auth/api-token` | JWT | Generate API key |
| `POST` | `/api/scan/prompt` | API key | Scan user input |
| `POST` | `/api/scan/output` | API key | Scan AI output |
| `GET` | `/api/guardrails` | JWT | List all guardrail configs |
| `PATCH` | `/api/guardrails/{id}` | JWT | Update guardrail settings |
| `GET` | `/api/connections` | JWT | List API connections |
| `POST` | `/api/connections` | JWT | Create new connection |
| `GET` | `/api/connections/{id}/guardrails` | JWT | Get per-connection guardrails |
| `PUT` | `/api/connections/{id}/guardrails` | JWT | Set per-connection guardrails |
| `GET` | `/api/audit` | JWT | Audit log |
| `GET` | `/api/analytics/summary` | JWT | Scan statistics |
| `GET` | `/api/public/platform-info` | — | Company name, chatbot status |
| `POST` | `/api/billing/checkout` | JWT | Start Stripe Checkout session |
| `GET` | `/api/billing/portal` | JWT | Open Stripe Billing Portal |
| `POST` | `/api/billing/cancel` | JWT | Cancel subscription at period end |
| `POST` | `/api/billing/webhook` | Stripe sig | Stripe event webhook (unauthenticated) |

### Scan Example

```bash
# Get your API key from the dashboard → Connections
curl -X POST https://your-project73.ai/api/scan/prompt \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "User message to screen"}'
```

Response:
```json
{
  "is_valid": true,
  "sanitized_text": "User message to screen",
  "scanner_results": {
    "PromptInjection": {"is_valid": true, "score": 0.02},
    "Toxicity": {"is_valid": true, "score": 0.01}
  },
  "violation_scanners": []
}
```

---

## Scanners Reference

### Input Scanners (16)

| Scanner | Purpose |
|---------|---------|
| PromptInjection | Detects jailbreak / instruction override attempts |
| Toxicity | Offensive or harmful language |
| BanTopics | Block configurable off-limits topics |
| BanSubstrings | Exact phrase/keyword blocklist |
| BanCompetitors | Block competitor name mentions |
| Code | Detect code submissions |
| Gibberish | Filter nonsense inputs |
| InvisibleText | Hidden Unicode / zero-width chars |
| Language | Enforce allowed languages |
| LanguageSame | Input/output language consistency |
| MaliciousURLs | URLs in prompts |
| NoRefusal | Detect refusal-bypass attempts |
| Regex | Custom regex patterns |
| Secrets | API keys, tokens in prompts |
| Sentiment | Negative sentiment threshold |
| TokenLimit | Enforce max token count |

### Output Scanners (24)

| Scanner | Purpose |
|---------|---------|
| Bias | Discriminatory content in responses |
| Code | Code blocks in output |
| Deanonymize | PII re-insertion into responses |
| FactualConsistency | Hallucination / contradiction detection |
| Gibberish | Nonsense output filter |
| JSON | Enforce JSON schema compliance |
| Language | Output language enforcement |
| LanguageSame | Match input language |
| MaliciousURLs | URLs in AI responses |
| NoRefusal | Refusal detection in output |
| ReadingTime | Long response throttle |
| Regex | Custom pattern matching |
| Relevance | On-topic response check |
| Secrets | Sensitive data in output |
| Sentiment | Negative tone in responses |
| Toxicity | Harmful language in output |
| URLReachability | Check if output URLs resolve |
| BanCompetitors | Block competitor mentions in output |
| BanSubstrings | Keyword blocklist in output |
| BanTopics | Off-limits topics in output |
| PIITagger | Tag/redact personal data |
| Refusal | Detect and allow AI refusals |
| Sensitive | Configurable sensitive data patterns |
| Groundedness | Response grounded in context |

---

## User Roles

| Role | Access |
|------|--------|
| `admin` | Super-admin — full platform access, all orgs, platform settings |
| `org_admin` | Org-level admin — manage members, invites, org connections |
| `viewer` | Regular member — view dashboards, create scans |

---

## Security

- JWT tokens expire in 1440 minutes / 24 h by default (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- Password minimum 12 characters (enforced at API + schema level)
- Password reset tokens are SHA-256 hashed before storage
- Request body capped at 1 MB
- Security headers on all responses (`X-Frame-Options`, `X-Content-Type-Options`, etc.)
- CORS restricted to explicit origin list
- Search/query params length-limited to prevent abuse
- Maintenance mode bypasses restricted to `/api/admin`, `/api/auth`, `/api/public`, `/health`

---

## License

MIT
