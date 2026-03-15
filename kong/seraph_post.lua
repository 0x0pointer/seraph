-- seraph_post.lua
-- Kong post-function plugin — scans the LLM response through Seraph
-- before returning it to the caller.
--
-- Phase: body_filter
--
-- The body_filter phase runs once per chunk. We buffer the full response
-- in ngx.ctx and scan it on the final chunk (ngx.arg[2] == true).
--
-- Environment variables (same as pre-function):
--   SERAPH_URL  — base URL of Seraph
--   SERAPH_KEY  — connection key

local http  = require("resty.http")
local cjson = require("cjson.safe")

local SERAPH_URL = os.getenv("SERAPH_URL") or "http://seraph:8000"
local SERAPH_KEY = os.getenv("SERAPH_KEY") or ""
local TIMEOUT_MS    = 10000

-- ── Buffer chunks ──────────────────────────────────────────────────────────────
-- ngx.arg[1] = current chunk body, ngx.arg[2] = is_last_chunk (bool)
local chunk    = ngx.arg[1]
local is_last  = ngx.arg[2]

-- Accumulate chunks in context
ngx.ctx.skf_response_buf = (ngx.ctx.skf_response_buf or "") .. (chunk or "")

-- Only scan + decide on the final chunk
if not is_last then
    ngx.arg[1] = ""   -- suppress intermediate chunks (will re-emit at the end)
    return
end

local full_body = ngx.ctx.skf_response_buf

-- ── Extract assistant content ──────────────────────────────────────────────────
local function assistant_content(raw)
    local parsed, err = cjson.decode(raw)
    if err or not parsed then return "" end
    local choices = parsed.choices
    if not choices or #choices == 0 then return "" end
    return (choices[1].message or {}).content or ""
end

local assistant_text = assistant_content(full_body)
if assistant_text == "" then
    ngx.arg[1] = full_body   -- emit original body unchanged
    return
end

-- Retrieve the original prompt from the header set by the pre-function
-- (so we can pass it to the output scanner for relevance/consistency checks).
local prompt_text = kong.request.get_header("X-SKF-Original-Prompt") or ""

-- ── Call Seraph output scan ─────────────────────────────────────────────────
local httpc = http.new()
httpc:set_timeout(TIMEOUT_MS)

local res, req_err = httpc:request_uri(SERAPH_URL .. "/api/scan/output", {
    method  = "POST",
    body    = cjson.encode({ text = assistant_text, prompt = prompt_text }),
    headers = {
        ["Content-Type"]  = "application/json",
        ["Authorization"] = "Bearer " .. SERAPH_KEY,
    },
})

-- Fail-closed on unreachable scanner
if req_err or not res then
    kong.log.err("Seraph output scan unreachable: ", req_err or "no response")
    ngx.arg[1] = cjson.encode({
        error  = "safety_scanner_unavailable",
        detail = "Seraph did not respond. Response blocked (fail-closed).",
    })
    kong.response.set_header("Content-Type", "application/json")
    kong.response.set_status(503)
    return
end

-- ── Act on scan result ─────────────────────────────────────────────────────────
if res.status == 200 then
    local result = cjson.decode(res.body) or {}

    -- Propagate audit log ID to caller in a response header
    if result.audit_log_id then
        kong.response.set_header("X-SKF-Output-Audit-ID", tostring(result.audit_log_id))
    end

    -- If Seraph applied a fix, swap the assistant content in the response body
    if result.fix_applied and result.sanitized_text and result.sanitized_text ~= assistant_text then
        local parsed = cjson.decode(full_body)
        if parsed and parsed.choices and parsed.choices[1] then
            parsed.choices[1].message.content = result.sanitized_text
            full_body = cjson.encode(parsed)
        end
    end

    ngx.arg[1] = full_body
    return
end

-- Blocked by output guardrail
local result = cjson.decode(res.body) or {}
local detail = result.detail or "Response blocked by Seraph output guardrail"

kong.log.warn("Seraph blocked output — status: ", res.status, " detail: ", detail)

ngx.arg[1] = cjson.encode({
    error  = "output_guardrail_violation",
    detail = detail,
})
kong.response.set_header("Content-Type", "application/json")
kong.response.set_status(400)
