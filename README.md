# Seraph — LLM Guardrail Proxy

A single-binary, YAML-configured LLM guardrail proxy. Scans inputs and outputs using [llm-guard](https://llm-guard.com/) scanners with parallel execution, text canonicalization for evasion resistance, and semantic embedding detection.

## Quick Start

```bash
# 1. Configure
cp config.yaml config.local.yaml
# Edit config.local.yaml with your settings

# 2. Run
SERAPH_CONFIG=config.local.yaml uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker compose up
```

## Configuration

Everything is configured via a single `config.yaml`:

```yaml
listen: "0.0.0.0:8000"
upstream: "https://api.openai.com"
api_keys:
  - "sk_seraph_abc123"

logging:
  level: info
  audit: true
  audit_file: null  # null = stdout JSON, path = SQLite

scanners:
  input:
    - type: PromptInjection
      threshold: 0.8
      on_fail: block
    - type: BanSubstrings
      params:
        substrings: ["ignore previous"]
      on_fail: block
  output:
    - type: Toxicity
      threshold: 0.7
      on_fail: block
```

Remove the `scanners` section entirely to use the built-in guardrail catalog defaults (29 input + 15 output scanners with trained ban lists, regex patterns, and topic classifiers).

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/scan/prompt` | Scan input text |
| `POST /api/scan/output` | Scan output text |
| `POST /api/scan/guard` | Scan full conversation |
| `POST /api/integrations/hook` | Universal gateway hook |
| `POST /api/integrations/proxy` | Transparent OpenAI-compatible reverse proxy |
| `POST /api/integrations/litellm/*` | LiteLLM custom guardrail hooks |
| `GET /health` | Health check |
| `POST /reload` | Hot-reload config |

## Integration Patterns

### 1. Direct Scan API

```bash
curl -X POST http://localhost:8000/api/scan/prompt \
  -H "Authorization: Bearer sk_seraph_abc123" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, how are you?"}'
```

### 2. Universal Gateway Hook

Works with Nginx (`auth_request`), Traefik (`forwardAuth`), Envoy (`ext_authz`), AWS API Gateway, etc.

```bash
curl -X POST http://localhost:8000/api/integrations/hook \
  -H "Authorization: Bearer sk_seraph_abc123" \
  -H "Content-Type: application/json" \
  -d '{"text": "user input", "direction": "input"}'
```

### 3. Transparent Proxy

Point your OpenAI SDK at Seraph — zero code changes:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/api/integrations/proxy/v1",
    api_key="sk_seraph_abc123",
    default_headers={
        "X-Upstream-URL": "https://api.openai.com",
        "X-Upstream-Auth": "Bearer sk-your-openai-key",
    },
)
```

## on_fail Actions

Each scanner supports configurable failure actions (inspired by Guardrails AI):

| Action | Behavior |
|--------|----------|
| `block` | Reject the request (default) |
| `fix` | Use scanner's sanitized output instead of blocking |
| `monitor` | Log violation but allow through |
| `reask` | Reject with structured correction hints |

## Hot Reload

Reload config without restarting:

```bash
# Via HTTP
curl -X POST http://localhost:8000/reload -H "Authorization: Bearer sk_seraph_abc123"

# Via signal
kill -HUP <pid>
```

## Development

```bash
pip install poetry
poetry install
poetry run pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE).
