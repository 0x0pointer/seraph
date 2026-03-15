-- seraph_pre.lua
-- Kong pre-function plugin — scans the incoming user prompt through Seraph
-- before forwarding the request to the upstream LLM provider.
--
-- Phase: access
--
-- Environment variables (set in Kong's environment):
--   SERAPH_URL  — base URL of Seraph, e.g. http://seraph:8000
--   SERAPH_KEY  — connection key, e.g. ts_conn_abc123
--
-- Behaviour:
--   is_valid=true  → request passes through unchanged
--   is_valid=false → request is terminated with HTTP 400 and the guardrail
--                    violation detail is returned to the caller
--   Seraph unreachable → request is terminated with HTTP 503 (fail-closed)
--                           Change to `return` to fail-open if preferred.

local http  = require("resty.http")
local cjson = require("cjson.safe")

-- ── Config ────────────────────────────────────────────────────────────────────
local SERAPH_URL = os.getenv("SERAPH_URL") or "http://seraph:8000"
local SERAPH_KEY = os.getenv("SERAPH_KEY") or ""
local TIMEOUT_MS    = 10000   -- 10 s; tune to your p99 scan latency

-- ── Extract last user message from OpenAI-compatible body ─────────────────────
local function last_user_message(messages)
    if not messages then return "" end
    for i = #messages, 1, -1 do
        if messages[i].role == "user" then
            return messages[i].content or ""
        end
    end
    return ""
end

-- ── Main ──────────────────────────────────────────────────────────────────────
local raw_body = kong.request.get_raw_body()
if not raw_body or raw_body == "" then
    return  -- nothing to scan
end

local body, err = cjson.decode(raw_body)
if err or not body then
    kong.log.warn("Seraph pre-function: could not parse request body — skipping scan")
    return
end

local text = last_user_message(body.messages)
if text == "" then
    return  -- no user message found (e.g. system-only prompt)
end

-- ── Call Seraph ─────────────────────────────────────────────────────────────
local httpc = http.new()
httpc:set_timeout(TIMEOUT_MS)

local res, req_err = httpc:request_uri(SERAPH_URL .. "/api/scan/prompt", {
    method  = "POST",
    body    = cjson.encode({ text = text }),
    headers = {
        ["Content-Type"]  = "application/json",
        ["Authorization"] = "Bearer " .. SERAPH_KEY,
    },
})

-- Fail-closed: block request if Seraph is unreachable
if req_err or not res then
    kong.log.err("Seraph unreachable: ", req_err or "no response")
    return kong.response.exit(503, cjson.encode({
        error  = "safety_scanner_unavailable",
        detail = "Seraph did not respond. Request blocked (fail-closed).",
    }), { ["Content-Type"] = "application/json" })
end

-- ── Act on scan result ─────────────────────────────────────────────────────────
if res.status == 200 then
    local result = cjson.decode(res.body) or {}

    -- If Seraph applied a fix (e.g. PII redaction), replace the prompt text
    -- in the forwarded request so the LLM receives the sanitized version.
    if result.fix_applied and result.sanitized_text and result.sanitized_text ~= text then
        -- Replace the last user message content with the sanitized version
        for i = #body.messages, 1, -1 do
            if body.messages[i].role == "user" then
                body.messages[i].content = result.sanitized_text
                break
            end
        end
        local new_body = cjson.encode(body)
        kong.service.request.set_raw_body(new_body)
        kong.service.request.set_header("Content-Length", tostring(#new_body))
    end

    -- Pass the Seraph audit log ID downstream as a request header
    -- so it can be correlated in application logs.
    if result.audit_log_id then
        kong.service.request.set_header("X-SKF-Audit-ID", tostring(result.audit_log_id))
    end

    return  -- allow request through
end

-- Non-200 = blocked by guardrail
local result = cjson.decode(res.body) or {}
local detail = result.detail or "Request blocked by Seraph guardrail"

kong.log.warn("Seraph blocked request — status: ", res.status, " detail: ", detail)

return kong.response.exit(400, cjson.encode({
    error  = "guardrail_violation",
    detail = detail,
}), { ["Content-Type"] = "application/json" })
