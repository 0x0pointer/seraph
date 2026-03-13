# SKF Guard — Gateway Integration Guide

This guide covers every way to connect SKF Guard to an external API gateway or proxy so that guardrails are enforced at the infrastructure level, without changing application code.

---

## Integration Patterns

Three patterns are available. Pick the one that fits your stack.

| Pattern | Endpoint | Best for | Effort |
|---|---|---|---|
| **Universal Hook** | `POST /api/integrations/hook` | Any gateway with HTTP callbacks (Nginx, Traefik, Envoy, AWS, Apigee, Tyk) | Low |
| **Transparent Proxy** | `POST /api/integrations/proxy/{path}` | OpenAI SDK, LangChain, or any OpenAI-compatible client | Minimal |
| **LiteLLM Guardrail** | `POST /api/integrations/litellm/*` | LiteLLM proxy deployments | Low |
| **Kong Plugins** | Lua pre-function + post-function | Kong API Gateway | Medium |

All patterns share the same authentication, the same `on_fail_action` lifecycle, and write to the same audit log. Every blocked or monitored request appears in the SKF Guard dashboard.

---

## Authentication

Every integration endpoint uses the same connection key as the core scan API. Create a dedicated connection in the SKF Guard dashboard for each gateway environment (prod, staging) to get isolated audit logs and per-connection guardrail configs.

```
Authorization: Bearer ts_conn_<your_connection_key>
```

Set it once in your gateway's environment:

```bash
SKF_GUARD_KEY=ts_conn_<your_connection_key>
```

---

## 1. Universal Hook

The simplest integration. One endpoint, minimal JSON payload. Works with **any** gateway that can make an HTTP POST callback.

### Endpoint

```
POST /api/integrations/hook
```

### Request

```http
POST /api/integrations/hook
Authorization: Bearer ts_conn_<key>
Content-Type: application/json

{
  "text":      "the text to scan",
  "direction": "input",
  "prompt":    ""
}
```

| Field | Required | Values | Description |
|---|---|---|---|
| `text` | Yes | string | The user message or LLM output to scan |
| `direction` | No | `input` \| `output` | Defaults to `input` |
| `prompt` | No | string | Original user prompt — pass for output scans so relevance/consistency scanners have context |

### Response

| Status | Meaning | Body |
|---|---|---|
| `200` | Allowed | `{"status": "allowed", "sanitized_text": "...", "fix_applied": false, "audit_log_id": 42}` |
| `400` | Blocked | `{"detail": "Request blocked by guardrail(s): PromptInjection"}` |
| `429` | Plan limit reached | `{"detail": "Monthly scan limit reached."}` |

**Gateway rule:** treat `200` as allow, anything else as deny.

When `fix_applied: true`, `sanitized_text` contains the clean version (PII redacted, secrets removed). Replace the original text with it before forwarding to the LLM.

---

## 2. Transparent Proxy

An OpenAI-compatible reverse proxy. Zero changes to existing clients — just change `base_url`. SKF Guard scans the input, forwards to the upstream LLM, scans the output, and returns an identical response.

### Endpoint

```
POST /api/integrations/proxy/{path}
```

### Required headers

| Header | Example | Purpose |
|---|---|---|
| `Authorization` | `Bearer ts_conn_<key>` | SKF Guard authentication |
| `X-Upstream-URL` | `https://api.openai.com` | Where to forward the request |
| `X-Upstream-Auth` | `Bearer sk-...` | Credentials for the upstream LLM |

### Python — OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://skf-guard:8000/api/integrations/proxy/v1",
    default_headers={
        "Authorization":   "Bearer ts_conn_<key>",
        "X-Upstream-URL":  "https://api.openai.com",
        "X-Upstream-Auth": "Bearer sk-...",
    }
)

# Everything else is unchanged
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Summarise the Q3 earnings report."}]
)
```

### Node.js — OpenAI SDK

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://skf-guard:8000/api/integrations/proxy/v1",
  defaultHeaders: {
    "Authorization":   "Bearer ts_conn_<key>",
    "X-Upstream-URL":  "https://api.openai.com",
    "X-Upstream-Auth": "Bearer sk-...",
  },
});
```

### Request flow

```
1. Extract last user message from messages[]
2. Run input scan → block immediately if invalid (LLM never called)
3. If fix_applied → replace message with sanitized_text before forwarding
4. Forward full request to X-Upstream-URL using X-Upstream-Auth
5. Extract assistant reply from upstream response
6. Run output scan → replace with safe fallback if invalid
7. If fix_applied → replace assistant content with sanitized_text
8. Return response to caller (identical OpenAI shape)
```

---

## 3. LiteLLM

Native custom guardrail hooks for [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/guardrails).

### Endpoints

| Endpoint | LiteLLM mode | Scans |
|---|---|---|
| `POST /api/integrations/litellm/pre_call` | `pre_call` | Last user message — before the LLM call |
| `POST /api/integrations/litellm/post_call` | `post_call` | Assistant reply — before returning to caller |
| `POST /api/integrations/litellm/during_call` | `during_call` | Last user message (streaming; same as pre_call) |

### litellm_config.yaml

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY

guardrails:
  - guardrail_name: skf-guard-input
    litellm_params:
      guardrail: custom
      mode: pre_call
      guardrail_endpoint: http://skf-guard:8000/api/integrations/litellm/pre_call
      default_headers:
        Authorization: "Bearer ${SKF_GUARD_KEY}"

  - guardrail_name: skf-guard-output
    litellm_params:
      guardrail: custom
      mode: post_call
      guardrail_endpoint: http://skf-guard:8000/api/integrations/litellm/post_call
      default_headers:
        Authorization: "Bearer ${SKF_GUARD_KEY}"
```

```bash
# Environment variable
SKF_GUARD_KEY=ts_conn_your_connection_key
```

LiteLLM treats `HTTP 200` as allowed and any `4xx` as a guardrail block. The `detail` field from SKF Guard is surfaced directly to the caller.

---

## 4. Kong API Gateway

Uses Kong's built-in `pre-function` and `post-function` serverless Lua plugins — no custom plugin development required.

### Files

| File | Purpose |
|---|---|
| `kong/skf_guard_pre.lua` | `access` phase — scans prompt, blocks or rewrites sanitized text |
| `kong/skf_guard_post.lua` | `body_filter` phase — buffers full response, scans output |
| `kong/kong.yml` | Declarative Kong config |

### Enable in docker-compose.yml

Uncomment the `kong:` service block in `docker-compose.yml` and set your environment variables:

```bash
SKF_GUARD_KEY=ts_conn_your_connection_key
```

```yaml
# docker-compose.yml — uncomment to enable
kong:
  image: kong:3.7-ubuntu
  environment:
    KONG_DATABASE: "off"
    KONG_DECLARATIVE_CONFIG: /etc/kong/kong.yml
    SKF_GUARD_URL: http://backend:8000
    SKF_GUARD_KEY: ${SKF_GUARD_KEY}
  volumes:
    - ./kong/kong.yml:/etc/kong/kong.yml:ro
    - ./kong/skf_guard_pre.lua:/usr/local/kong/skf_guard_pre.lua:ro
    - ./kong/skf_guard_post.lua:/usr/local/kong/skf_guard_post.lua:ro
  ports:
    - "8080:8000"   # Kong proxy — point LLM clients here
    - "8081:8001"   # Kong Admin API
```

Point your LLM clients at `http://localhost:8080` instead of the LLM provider directly.

### What the Lua plugins do

**`skf_guard_pre.lua` (input):**
1. Reads the request body and extracts the last user message
2. POSTs to `/api/scan/prompt` on SKF Guard
3. If blocked → returns `400` to the caller, request never reaches the LLM
4. If `fix_applied` → rewrites the request body with `sanitized_text` before forwarding
5. Adds `X-SKF-Audit-ID` header to the upstream request

**`skf_guard_post.lua` (output):**
1. Buffers the full LLM response across chunks
2. Extracts assistant content and POSTs to `/api/scan/output`
3. If blocked → replaces the response body with a safe error message
4. If `fix_applied` → replaces assistant content with `sanitized_text`

Both plugins are **fail-closed** — if SKF Guard is unreachable, the request is terminated with `503`.

---

## 5. Nginx (OpenResty)

Uses `access_by_lua_block` to call the universal hook before proxying to the upstream LLM.

**Requires:** OpenResty (Nginx + lua-nginx-module + lua-resty-http)

```nginx
location /v1/chat/completions {
    lua_need_request_body on;

    access_by_lua_block {
        local http  = require("resty.http")
        local cjson = require("cjson.safe")

        local body   = ngx.req.get_body_data()
        local parsed = cjson.decode(body)

        -- Extract last user message
        local text = ""
        for i = #parsed.messages, 1, -1 do
            if parsed.messages[i].role == "user" then
                text = parsed.messages[i].content
                break
            end
        end
        if text == "" then return end

        local httpc = http.new()
        httpc:set_timeout(10000)

        local res = httpc:request_uri("http://skf-guard:8000/api/integrations/hook", {
            method  = "POST",
            body    = cjson.encode({ text = text, direction = "input" }),
            headers = {
                ["Content-Type"]  = "application/json",
                ["Authorization"] = "Bearer " .. os.getenv("SKF_GUARD_KEY"),
            },
        })

        if not res or res.status ~= 200 then
            ngx.status = (res and res.status ~= 200) and 400 or 503
            ngx.say(res and res.body or '{"error":"scanner unavailable"}')
            ngx.exit(ngx.status)
        end
    }

    proxy_pass https://api.openai.com;
}
```

Full config with `fix_applied` body rewriting: [`gateway-examples/nginx.conf`](../gateway-examples/nginx.conf)

---

## 6. Traefik v3

### Option B — Transparent Proxy (recommended)

Route traffic through SKF Guard's proxy endpoint. Traefik injects the auth headers via middleware.

```yaml
# traefik.yml
http:
  routers:
    llm-with-guardrails:
      rule: "PathPrefix(`/llm`)"
      service: skf-guard-proxy
      middlewares: [inject-skf-headers, strip-llm-prefix]

  middlewares:
    inject-skf-headers:
      headers:
        customRequestHeaders:
          Authorization:   "Bearer {{ env \"SKF_GUARD_KEY\" }}"
          X-Upstream-URL:  "https://api.openai.com"
          X-Upstream-Auth: "Bearer {{ env \"OPENAI_API_KEY\" }}"

    strip-llm-prefix:
      stripPrefix:
        prefixes: ["/llm"]

  services:
    skf-guard-proxy:
      loadBalancer:
        servers:
          - url: "http://skf-guard:8000/api/integrations/proxy"
```

Clients call `http://traefik/llm/v1/chat/completions` — Traefik strips the prefix, injects headers, and routes to SKF Guard's proxy, which scans and forwards to OpenAI.

### Option A — forwardAuth

Traefik's `forwardAuth` middleware forwards the original request to an auth service. **Limitation:** Traefik only forwards headers, not the request body. Use this only if your upstream service sets an `X-SKF-Text` header with the content to scan.

Full config: [`gateway-examples/traefik.yml`](../gateway-examples/traefik.yml)

---

## 7. Envoy

Uses the `ext_authz` HTTP filter with `with_request_body: true` to forward the full request body to SKF Guard for scanning.

**Requires:** Envoy >= 1.14

```yaml
http_filters:
  - name: envoy.filters.http.ext_authz
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz
      http_service:
        server_uri:
          uri: http://skf-guard:8000
          cluster: skf_guard
          timeout: 10s
        path_prefix: /api/integrations/hook
        authorization_request:
          headers_to_add:
            - header: {key: Content-Type, value: application/json}
          allowed_headers:
            patterns: [{exact: authorization}]
      # Forward request body so SKF Guard can read the user message
      with_request_body:
        max_request_bytes: 65536
        allow_partial_message: false
      # Fail-closed: deny if SKF Guard is unreachable
      failure_mode_allow: false
```

Full static config with clusters: [`gateway-examples/envoy.yaml`](../gateway-examples/envoy.yaml)

---

## 8. AWS API Gateway + Lambda

Uses a Lambda **REQUEST authorizer** that calls the universal hook and returns an IAM policy.

**Setup:**
1. Deploy `gateway-examples/aws-lambda.py` as a Python 3.12 Lambda function
2. Set environment variables: `SKF_GUARD_URL`, `SKF_GUARD_KEY`
3. In API Gateway → Authorizers → create a REQUEST authorizer pointing at the Lambda
4. Set **Authorization caching TTL to 0** — guardrails must re-run on every request

```python
def lambda_handler(event, context):
    body      = json.loads(event.get("body") or "{}")
    user_text = last_user_message(body.get("messages", []))

    result = call_skf_hook(user_text, direction="input")

    if result["status_code"] == 503:
        return deny_policy(method_arn, "Scanner unavailable")   # fail-closed

    if result["status_code"] != 200:
        return deny_policy(method_arn, result["body"].get("detail"))

    return allow_policy(method_arn, context={
        "skf_audit_log_id": str(result["body"].get("audit_log_id", "")),
        "skf_fix_applied":  str(result["body"].get("fix_applied", False)),
    })
```

Full implementation: [`gateway-examples/aws-lambda.py`](../gateway-examples/aws-lambda.py)

---

## Quick Reference

| Gateway | Pattern | Body scan | Output scan | Fix rewrite | Fail mode |
|---|---|---|---|---|---|
| Any | Universal Hook | Yes | Yes (separate call) | Manual | Gateway decides |
| Any OpenAI client | Transparent Proxy | Yes | Yes (automatic) | Yes (automatic) | 502 |
| LiteLLM | pre_call + post_call | Yes | Yes | No | 400 to caller |
| Kong | Lua pre + post | Yes | Yes | Yes (Lua rewrite) | 503 |
| Nginx | lua_block | Yes | No† | Yes (Lua rewrite) | 400/503 |
| Traefik | Proxy route | Yes | Yes (automatic) | Yes (automatic) | 502 |
| Traefik | forwardAuth | No‡ | No | No | 4xx = deny |
| Envoy | ext_authz | Yes | No† | No | 403 |
| AWS | Lambda authorizer | Yes | No† | No | Deny policy |

† Output scanning requires an additional filter/hook on the response path.
‡ Traefik forwardAuth forwards headers only, not the request body.

---

## Choosing the Right Pattern

| You have... | Use |
|---|---|
| An OpenAI SDK client (Python, JS, Go) | **Transparent Proxy** — change `base_url`, done |
| LiteLLM as your LLM proxy | **LiteLLM pre_call + post_call** |
| Kong as your API gateway | **Kong Lua plugins** |
| Nginx / OpenResty as your reverse proxy | **Universal Hook** via `access_by_lua_block` |
| Traefik as your ingress | **Transparent Proxy route** (Option B) |
| Envoy / Istio service mesh | **ext_authz filter** |
| AWS API Gateway | **Lambda REQUEST authorizer** |
| Any other gateway / custom middleware | **Universal Hook** — POST `/hook`, 200 = allow, 4xx = deny |
| Maximum throughput, lowest overhead | **Transparent Proxy** — one round trip, both directions |
