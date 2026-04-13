# Seraph — LLM Guardrail Proxy

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=0x0pointer_seraph&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=0x0pointer_seraph)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=0x0pointer_seraph&metric=bugs)](https://sonarcloud.io/summary/new_code?id=0x0pointer_seraph)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=0x0pointer_seraph&metric=coverage)](https://sonarcloud.io/summary/new_code?id=0x0pointer_seraph)

Seraph is a transparent security proxy for LLM applications. Point your app at Seraph instead of the LLM — it scans every request and response through a two-tier guardrail pipeline, then blocks or logs threats.

- **Drop-in replacement** for any LLM API endpoint — zero code changes
- Works with **any LLM provider** (OpenAI, Anthropic, Azure, Ollama, vLLM, etc.)
- **Two-tier defense-in-depth** — semantic allow-list + local Mistral 7B evaluation
- Configured with a **single YAML file** — no database, no frontend

## Architecture

```mermaid
flowchart LR
    App["Your App"] -->|"user prompt"| Seraph
    Seraph -->|"1. scan input"| T1["Tier 1: NeMo\nGuardrails"]
    T1 -->|"pass"| T2["Tier 2: LLM\nJudge"]
    T2 -->|"safe"| Seraph
    Seraph -->|"2. forward"| LLM["LLM Provider\n(OpenAI, Anthropic, etc.)"]
    LLM -->|"response"| Seraph
    Seraph -->|"3. scan output"| T1
    T1 -->|"pass"| T2
    T2 -->|"safe"| Seraph
    Seraph -->|"clean response"| App

    style Seraph fill:#e67e22,stroke:#d35400,color:#fff
    style T1 fill:#2ecc71,stroke:#27ae60,color:#fff
    style T2 fill:#3498db,stroke:#2980b9,color:#fff
```

**Tier 1** uses [NVIDIA NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) as a semantic allow-list firewall — you define what users *are allowed* to ask via Colang flows; everything else is blocked. **Tier 2** runs a local [Mistral 7B](https://mistral.ai/) model via [LangGraph](https://langchain-ai.github.io/langgraph/) to evaluate requests for prompt injection, jailbreaks, data exfiltration, and policy violations.

## How it works

```mermaid
sequenceDiagram
    participant App
    participant Seraph
    participant NeMo as Tier 1: NeMo Guardrails
    participant Judge as Tier 2: Mistral 7B Judge
    participant LLM as LLM Provider

    App->>Seraph: POST /v1/chat/completions

    Seraph->>Seraph: Auth check
    Seraph->>NeMo: Scan input
    NeMo-->>Seraph: Pass
    Seraph->>Judge: Deep evaluation (Mistral 7B)
    Judge-->>Seraph: Safe

    Seraph->>LLM: Forward request

    LLM-->>Seraph: Response

    Seraph->>NeMo: Scan output
    NeMo-->>Seraph: Pass
    Seraph->>Judge: Evaluate output
    Judge-->>Seraph: Safe

    Seraph-->>App: Return response
```

## Quick Start

```bash
git clone https://github.com/0x0pointer/seraph.git
cd seraph
pip install poetry && poetry install

export UPSTREAM_API_KEY=sk-your-openai-key
SERAPH_CONFIG=config.yaml uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker compose up
```

## Configuration

Edit `config.yaml`:

```yaml
listen: "0.0.0.0:8000"
upstream: "https://api.openai.com"

api_keys:
  - "your-seraph-key-here"

nemo_tier:
  enabled: true
  embedding_threshold: 0.85
  model: "gpt-4o-mini"

judge:
  enabled: true
  model: "mistral"                       # local Mistral 7B via Ollama
  base_url: "http://localhost:11434/v1"
  risk_threshold: 0.7
```

Customize allowed intents in `app/services/nemo_config/input_rails.co` and the judge evaluation rubric in `app/services/judge_prompt.txt`.

## Usage

Point your LLM client at Seraph instead of the provider:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-seraph-key",
    default_headers={"X-Upstream-Auth": "Bearer sk-your-openai-key"},
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

### Auth Headers

| Header | Purpose |
|--------|---------|
| `Authorization: Bearer <seraph-key>` | Seraph authenticates the client, then strips it |
| `X-Upstream-Auth: Bearer <provider-key>` | Forwarded as `Authorization` to the LLM provider |
| `X-Upstream-URL: <url>` | Optional — overrides `upstream` from config |

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/{path}` | POST | Transparent proxy with scanning |
| `/{path}` | GET/PUT/DELETE/PATCH | Pass-through (no scanning) |
| `/health` | GET | Health check |
| `/reload` | POST | Hot-reload config and all tiers |

Streaming (`"stream": true`) is supported — input is scanned before forwarding; the SSE stream is passed through transparently.

## Development

```bash
poetry install
poetry run pytest tests/ -v
```

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).
