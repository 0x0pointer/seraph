"use client";

import { useState } from "react";

// ── Shared primitives ─────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>
      {children}
    </p>
  );
}

function CodeBlock({
  lang,
  children,
}: {
  lang: string;
  children: string;
}) {
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(children.trim());
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/5">
        <span className="text-xs text-slate-600 font-mono">{lang}</span>
        <button
          onClick={copy}
          className="text-xs font-mono transition-colors"
          style={{ color: copied ? "#14B8A6" : "#475569" }}
        >
          {copied ? "copied!" : "copy"}
        </button>
      </div>
      <pre
        className="px-5 py-4 text-sm font-mono leading-relaxed overflow-x-auto text-slate-400 whitespace-pre"
        style={{ fontFamily: "ui-monospace, SFMono-Regular, monospace" }}
      >
        {children.trim()}
      </pre>
    </div>
  );
}

function TabBar({
  tabs,
  active,
  onChange,
}: {
  tabs: string[];
  active: string;
  onChange: (t: string) => void;
}) {
  return (
    <div className="flex gap-1 p-1 rounded w-fit mb-4" style={{ background: "#0d1426" }}>
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className="px-3 py-1.5 rounded text-xs font-medium transition-colors"
          style={
            active === t
              ? { background: "#14B8A6", color: "#0A0F1F" }
              : { color: "#64748b" }
          }
        >
          {t}
        </button>
      ))}
    </div>
  );
}

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded border-l-2 px-4 py-3 text-sm text-slate-400 leading-relaxed"
      style={{ background: "#0d1426", borderColor: "#14B8A6", borderLeftWidth: 2 }}
    >
      {children}
    </div>
  );
}

function ResponseField({
  field,
  type,
  desc,
}: {
  field: string;
  type: string;
  desc: string;
}) {
  return (
    <div className="flex gap-4 py-3 border-t border-white/5 first:border-0">
      <div className="w-44 shrink-0">
        <span className="text-xs font-mono text-white">{field}</span>
        <span className="ml-2 text-xs font-mono text-slate-600">{type}</span>
      </div>
      <p className="text-sm text-slate-500 leading-relaxed">{desc}</p>
    </div>
  );
}

function FirstScanTabs() {
  const [tab, setTab] = useState("Python");
  const code: Record<string, string> = {
    Python: FIRST_SCAN_PYTHON,
    TypeScript: FIRST_SCAN_TS,
    cURL: FIRST_SCAN_CURL,
  };
  return (
    <>
      <TabBar tabs={["Python", "TypeScript", "cURL"]} active={tab} onChange={setTab} />
      <CodeBlock lang={tab}>{code[tab]}</CodeBlock>
    </>
  );
}

// ── Code snippets ─────────────────────────────────────────────────────────────

const AUTH_CURL = `curl -X POST https://your-project73.ai/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username": "youruser", "password": "yourpassword"}'

# Response:
# { "access_token": "eyJhbGci...", "token_type": "bearer" }`;

const QUICKSTART: Record<string, string> = {
  Python: `import os
import httpx
from openai import OpenAI

API_BASE  = "https://your-project73.ai/api"
TOKEN  = os.environ["P73_TOKEN"]          # from /api/auth/login
openai = OpenAI()

headers = {"Authorization": f"Bearer {TOKEN}"}


def chat(user_prompt: str) -> str:
    # 1 ── Scan the incoming prompt
    scan = httpx.post(f"{API_BASE}/scan/prompt",
                      json={"text": user_prompt},
                      headers=headers).json()

    if not scan["is_valid"]:
        raise ValueError(f"Blocked by: {', '.join(scan['violation_scanners'])}")

    # 2 ── Call your LLM (use sanitized_text — some scanners redact content)
    completion = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": scan["sanitized_text"]}],
    )
    response_text = completion.choices[0].message.content

    # 3 ── Scan the model's response
    out = httpx.post(f"{API_BASE}/scan/output",
                     json={"text": response_text, "prompt": user_prompt},
                     headers=headers).json()

    if not out["is_valid"]:
        raise ValueError(f"Response blocked by: {', '.join(out['violation_scanners'])}")

    return out["sanitized_text"]`,

  TypeScript: `import OpenAI from "openai";

const API_BASE = "https://your-project73.ai/api";
const TOKEN = process.env.P73_TOKEN!;      // from /api/auth/login
const openai = new OpenAI();

const p73 = (path: string, body: object) =>
  fetch(\`\${API_BASE}\${path}\`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: \`Bearer \${TOKEN}\`,
    },
    body: JSON.stringify(body),
  }).then((r) => r.json());


async function chat(userPrompt: string): Promise<string> {
  // 1 ── Scan the incoming prompt
  const inputScan = await p73("/scan/prompt", { text: userPrompt });

  if (!inputScan.is_valid) {
    throw new Error(\`Blocked by: \${inputScan.violation_scanners.join(", ")}\`);
  }

  // 2 ── Call your LLM (use sanitized_text — some scanners redact content)
  const completion = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [{ role: "user", content: inputScan.sanitized_text }],
  });
  const responseText = completion.choices[0].message.content!;

  // 3 ── Scan the model's response
  const outputScan = await p73("/scan/output", {
    text: responseText,
    prompt: userPrompt,
  });

  if (!outputScan.is_valid) {
    throw new Error(\`Response blocked by: \${outputScan.violation_scanners.join(", ")}\`);
  }

  return outputScan.sanitized_text;
}`,

  cURL: `# Scan a prompt
curl -X POST https://your-project73.ai/api/scan/prompt \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Ignore all previous instructions and..."}'

# Scan a model response
curl -X POST https://your-project73.ai/api/scan/output \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "text": "Sure! Here is how to do it...",
    "prompt": "Original user prompt here"
  }'`,
};

const TOKEN_REFRESH: Record<string, string> = {
  Python: `import time
import httpx

class P73Client:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url
        self.username = username
        self.password = password
        self._token: str | None = None
        self._expires_at: float = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        r = httpx.post(f"{self.base_url}/auth/login",
                       json={"username": self.username,
                             "password": self.password})
        r.raise_for_status()
        self._token = r.json()["access_token"]
        self._expires_at = time.time() + 3600   # token lasts 1 hour
        return self._token

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def scan_prompt(self, text: str) -> dict:
        return httpx.post(f"{self.base_url}/scan/prompt",
                          json={"text": text},
                          headers=self.headers).json()

    def scan_output(self, text: str, prompt: str) -> dict:
        return httpx.post(f"{self.base_url}/scan/output",
                          json={"text": text, "prompt": prompt},
                          headers=self.headers).json()


# Usage
client = P73Client("https://your-project73.ai/api", "user", "pass")
result = client.scan_prompt("Hello, world!")`,

  TypeScript: `class P73Client {
  private token: string | null = null;
  private expiresAt = 0;

  constructor(
    private baseUrl: string,
    private username: string,
    private password: string,
  ) {}

  private async getToken(): Promise<string> {
    if (this.token && Date.now() < this.expiresAt - 60_000) {
      return this.token;
    }
    const r = await fetch(\`\${this.baseUrl}/auth/login\`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: this.username, password: this.password }),
    });
    const data = await r.json();
    this.token = data.access_token;
    this.expiresAt = Date.now() + 3_600_000; // 1 hour
    return this.token!;
  }

  private async post(path: string, body: object) {
    const token = await this.getToken();
    const r = await fetch(\`\${this.baseUrl}\${path}\`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: \`Bearer \${token}\`,
      },
      body: JSON.stringify(body),
    });
    return r.json();
  }

  scanPrompt(text: string) {
    return this.post("/scan/prompt", { text });
  }

  scanOutput(text: string, prompt: string) {
    return this.post("/scan/output", { text, prompt });
  }
}

// Usage
const p73 = new P73Client("https://your-project73.ai/api", "user", "pass");
const result = await p73.scanPrompt("Hello, world!");`,
};

const SCAN_RESPONSE = `{
  "is_valid": false,
  "sanitized_text": "Ignore all previous [REDACTED]",
  "scanner_results": {
    "PromptInjection": 0.97,
    "Toxicity": 0.04
  },
  "violation_scanners": ["PromptInjection"],
  "audit_log_id": 142
}`;

const FIRST_SCAN_PYTHON = `import httpx

API_BASE = "https://api.project73.ai"   # your Project 73 endpoint
TOKEN = "YOUR_TOKEN"                   # from the dashboard → Settings → API token

headers = {"Authorization": f"Bearer {TOKEN}"}

# Scan a prompt before sending to your model
response = httpx.post(
    f"{API_BASE}/scan/prompt",
    json={"text": "Hello, how do I reset my password?"},
    headers=headers,
)
print(response.json())
# { "is_valid": true, "sanitized_text": "Hello, how do I reset my password?", ... }`;

const FIRST_SCAN_TS = `const API_BASE = "https://api.project73.ai"; // your Project 73 endpoint
const TOKEN = "YOUR_TOKEN";               // from the dashboard → Settings → API token

const response = await fetch(\`\${API_BASE}/scan/prompt\`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: \`Bearer \${TOKEN}\`,
  },
  body: JSON.stringify({ text: "Hello, how do I reset my password?" }),
});

const result = await response.json();
console.log(result);
// { is_valid: true, sanitized_text: "Hello, how do I reset my password?", ... }`;

const FIRST_SCAN_CURL = `curl -X POST https://api.project73.ai/scan/prompt \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Hello, how do I reset my password?"}'

# { "is_valid": true, "sanitized_text": "Hello, ...", "scanner_results": {}, ... }`;

const INPUT_SCANNERS = [
  { name: "PromptInjection", desc: "Detects attempts to override system instructions or jailbreak the model." },
  { name: "BanTopics", desc: "Zero-shot AI classification — block prompts discussing restricted topics." },
  { name: "Toxicity", desc: "Flags hate speech, threats, and harmful language before they reach the model." },
  { name: "BanSubstrings", desc: "Hard-block specific words or phrases. Exact match, no AI required." },
  { name: "BanCompetitors", desc: "Prevent competitor names from being sent to your model." },
  { name: "Secrets", desc: "Detect and redact API keys, tokens, and credentials in prompts." },
  { name: "TokenLimit", desc: "Reject prompts that exceed a configured token count." },
  { name: "Language", desc: "Accept only prompts written in approved languages." },
  { name: "Sentiment", desc: "Block strongly negative or hostile prompts." },
  { name: "Gibberish", desc: "Reject incoherent or nonsensical input." },
  { name: "InvisibleText", desc: "Detect hidden Unicode characters used to smuggle instructions." },
  { name: "Regex", desc: "Block prompts matching one or more custom regular expressions." },
  { name: "BanCode", desc: "Block prompts that contain or request code snippets." },
  { name: "CustomRule", desc: "Combine keywords, regex patterns, and AI topic classification into one rule." },
];

const OUTPUT_SCANNERS = [
  { name: "Toxicity", desc: "Flag toxic or offensive content in model responses before delivery." },
  { name: "Bias", desc: "Catch biased or discriminatory language in responses." },
  { name: "NoRefusal", desc: "Detect when the model refuses a legitimate request." },
  { name: "FactualConsistency", desc: "Verify the response is consistent with the source prompt." },
  { name: "Relevance", desc: "Ensure the response stays on topic relative to the prompt." },
  { name: "MaliciousURLs", desc: "Scan URLs in responses against known malicious domain lists." },
  { name: "BanTopics", desc: "Prevent the model from discussing restricted topics in its responses." },
  { name: "BanCompetitors", desc: "Stop the model from mentioning competitor products." },
  { name: "Sentiment", desc: "Block responses with strongly negative sentiment." },
  { name: "ReadingTime", desc: "Flag responses that exceed a configured reading time." },
  { name: "LanguageSame", desc: "Ensure the response is in the same language as the prompt." },
  { name: "Regex", desc: "Block responses matching custom regular expression patterns." },
  { name: "CustomRule", desc: "Apply your own keyword, pattern, or AI topic rules to responses." },
];

// ── Connection key snippets ────────────────────────────────────────────────────

const CONNECTION_ENV = `# chatbot/.env  (or your app's environment)
TALIX_API_URL=https://your-project73.ai          # base URL of your Project 73 Security instance
TALIX_CONNECTION_KEY=ts_conn_abc123...         # from Dashboard → APIs → copy key
OPENAI_API_KEY=sk-...                          # your LLM provider key
OPENAI_MODEL=gpt-4o-mini                       # optional — model to use`;

const CONNECTION_CHATBOT = `# 1. Enter the chatbot directory
cd chatbot/

# 2. Create your .env file from the example
cp .env.example .env

# 3. Fill in the values (TALIX_API_URL, TALIX_CONNECTION_KEY, OPENAI_API_KEY)
#    Open .env in your editor and paste in your connection key from the APIs page.

# 4. Start the chatbot — it auto-creates a venv and installs deps
./run.sh

# ✓ Chat interface available at http://localhost:3001`;

const CONNECTION_PYTHON = `import os
import httpx

API_BASE = os.environ["TALIX_API_URL"]          # e.g. https://your-project73.ai
KEY   = os.environ["TALIX_CONNECTION_KEY"]   # ts_conn_...

headers = {
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}


def chat(user_message: str) -> str:
    # 1 — Scan the incoming prompt
    scan = httpx.post(
        f"{API_BASE}/api/scan/prompt",
        json={"text": user_message},
        headers=headers,
        timeout=30,
    ).json()

    if not scan["is_valid"]:
        return "Sorry, your message was blocked by content guardrails."

    # 2 — Call your LLM (use sanitized_text — Secrets scanner may redact content)
    llm_response = call_your_llm(scan["sanitized_text"])

    # 3 — Scan the AI response before returning it
    out = httpx.post(
        f"{API_BASE}/api/scan/output",
        json={"text": llm_response, "prompt": user_message},
        headers=headers,
        timeout=30,
    ).json()

    if not out["is_valid"]:
        return "Sorry, I can't provide that response."

    return out["sanitized_text"]`;

const CONNECTION_TS = `const API_BASE = process.env.TALIX_API_URL!;         // e.g. https://your-project73.ai
const KEY   = process.env.TALIX_CONNECTION_KEY!;   // ts_conn_...

const p73 = async (path: string, body: object) => {
  const res = await fetch(\`\${API_BASE}\${path}\`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: \`Bearer \${KEY}\`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(\`Project 73 \${res.status}\`);
  return res.json();
};

async function chat(userMessage: string): Promise<string> {
  // 1 — Scan the incoming prompt
  const scan = await p73("/api/scan/prompt", { text: userMessage });

  if (!scan.is_valid) {
    return "Sorry, your message was blocked by content guardrails.";
  }

  // 2 — Call your LLM (use sanitized_text — Secrets scanner may redact content)
  const llmResponse = await callYourLLM(scan.sanitized_text);

  // 3 — Scan the AI response
  const out = await p73("/api/scan/output", {
    text: llmResponse,
    prompt: userMessage,
  });

  if (!out.is_valid) {
    return "Sorry, I can't provide that response.";
  }

  return out.sanitized_text;
}`;

const CONNECTION_CURL = `# Scan a user prompt with a connection key
curl -X POST https://your-project73.ai/api/scan/prompt \\
  -H "Authorization: Bearer ts_conn_abc123..." \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Tell me about your pricing"}'

# Response:
# { "is_valid": true, "sanitized_text": "Tell me about your pricing", ... }

# Scan an AI response (include the original prompt for context-aware scanners)
curl -X POST https://your-project73.ai/api/scan/output \\
  -H "Authorization: Bearer ts_conn_abc123..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "text": "Our plans start at $0 per month...",
    "prompt": "Tell me about your pricing"
  }'`;

const navItems = [
  { id: "how-it-works", label: "How it works" },
  { id: "setup", label: "Quick start" },
  { id: "authentication", label: "Authentication" },
  { id: "integration", label: "Integration guide" },
  { id: "response", label: "Response reference" },
  { id: "token-refresh", label: "Token refresh" },
  { id: "roles", label: "Roles & access" },
  { id: "organizations", label: "Organizations & teams" },
  { id: "connections", label: "API connections" },
  { id: "connection-setup", label: "Connection setup" },
  { id: "notifications", label: "Notifications" },
  { id: "input-scanners", label: "Input scanners" },
  { id: "output-scanners", label: "Output scanners" },
  { id: "deployment", label: "Going to production" },
];

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DocsPage() {
  const [integrationTab, setIntegrationTab] = useState("Python");
  const [refreshTab, setRefreshTab] = useState("Python");
  const [connTab, setConnTab] = useState("Python");

  const connCode: Record<string, string> = {
    Python: CONNECTION_PYTHON,
    TypeScript: CONNECTION_TS,
    cURL: CONNECTION_CURL,
  };

  return (
    <div style={{ background: "#0A0F1F" }} className="min-h-screen">
      <div className="max-w-6xl mx-auto px-6 py-16 flex gap-14">

        {/* Sidebar */}
        <aside className="hidden lg:block w-48 shrink-0 pt-1">
          <nav className="sticky top-20 space-y-0.5">
            <p className="text-xs font-mono tracking-widest uppercase mb-4 px-3" style={{ color: "#14B8A6" }}>
              Docs
            </p>
            {navItems.map((item) => (
              <a
                key={item.id}
                href={`#${item.id}`}
                className="block px-3 py-1.5 text-sm text-slate-500 hover:text-white transition-colors rounded"
              >
                {item.label}
              </a>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <main className="flex-1 min-w-0 space-y-16">

          {/* ── How it works ── */}
          <section id="how-it-works">
            <SectionLabel>Overview</SectionLabel>
            <h1 className="text-3xl font-bold text-white tracking-tight mb-4">How it works</h1>
            <p className="text-slate-400 leading-relaxed mb-8">
              Project 73 Security sits between your users and your AI model. Every prompt passes through
              the input scanner pipeline before reaching the model, and every response passes through
              the output pipeline before reaching the user. You control which scanners run and at
              what sensitivity — all from the dashboard, with no redeployment needed.
            </p>

            {/* Pipeline diagram */}
            <div
              className="rounded border border-white/5 p-6 space-y-3"
              style={{ background: "#0d1426" }}
            >
              {[
                { step: "User", desc: "Sends a prompt to your application" },
                { step: "POST /scan/prompt", desc: "Project 73 checks the prompt against all active input scanners", highlight: true },
                { step: "is_valid: false", desc: "→ Return an error to the user immediately. The model is never called.", warn: true },
                { step: "is_valid: true", desc: "→ Forward sanitized_text to your AI model" },
                { step: "AI model", desc: "Generates a response" },
                { step: "POST /scan/output", desc: "Project 73 checks the response against all active output scanners", highlight: true },
                { step: "is_valid: false", desc: "→ Suppress the response. Return a safe fallback to the user.", warn: true },
                { step: "is_valid: true", desc: "→ Return sanitized_text to the user" },
              ].map((row, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span
                    className="shrink-0 text-xs font-mono px-2 py-0.5 rounded mt-0.5"
                    style={
                      row.highlight
                        ? { background: "rgba(20,184,166,0.1)", color: "#14B8A6" }
                        : row.warn
                        ? { background: "rgba(248,113,113,0.08)", color: "#f87171" }
                        : { background: "rgba(255,255,255,0.04)", color: "#64748b" }
                    }
                  >
                    {row.step}
                  </span>
                  <p className="text-sm text-slate-500 leading-relaxed">{row.desc}</p>
                </div>
              ))}
            </div>

            <p className="text-sm text-slate-500 leading-relaxed mt-6">
              The integration is <strong className="text-slate-300">two HTTP calls</strong> — one before your LLM call and one after.
              Nothing else changes in your code. Scanner configuration, thresholds, and rules are all managed
              from the Project 73 dashboard.
            </p>
          </section>

          {/* ── Quick start ── */}
          <section id="setup">
            <SectionLabel>Getting started</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Quick start</h2>
            <p className="text-slate-400 leading-relaxed mb-8">
              Three steps and you're protecting your AI app. No infrastructure to manage — Project 73
              Shield runs as a hosted service and you call it over HTTP.
            </p>

            {/* Steps */}
            <div className="space-y-8">

              {/* Step 1 */}
              <div className="flex gap-5">
                <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>
                  1
                </div>
                <div className="flex-1 pt-0.5">
                  <h3 className="text-sm font-semibold text-white mb-1">Create your account</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-3">
                    <a href="/register" className="text-teal-400 hover:underline">Sign up</a> for a Project 73 Security account.
                    Once you're in, head to <strong className="text-slate-300">Settings → API token</strong> to
                    generate your token. Keep it secret — treat it like a password.
                  </p>
                </div>
              </div>

              {/* Step 2 */}
              <div className="flex gap-5">
                <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>
                  2
                </div>
                <div className="flex-1 pt-0.5">
                  <h3 className="text-sm font-semibold text-white mb-1">Configure your guardrails</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-3">
                    Open the <strong className="text-slate-300">Guardrails</strong> dashboard and enable the scanners
                    you need. Each scanner has sensible defaults — you can fine-tune thresholds and add custom
                    keyword or topic rules without writing any code.
                  </p>
                  <div className="rounded border border-white/5 p-4 text-sm text-slate-500 leading-relaxed space-y-1"
                    style={{ background: "#0A0F1F" }}>
                    {[
                      "Enable Prompt Injection to block jailbreak attempts",
                      "Enable Toxicity to filter harmful language",
                      "Add a Custom Rule with your own banned keywords",
                      "Enable output scanners to screen model responses",
                    ].map((tip) => (
                      <div key={tip} className="flex items-start gap-2">
                        <span style={{ color: "#14B8A6" }}>→</span>
                        <span>{tip}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Step 3 */}
              <div className="flex gap-5">
                <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>
                  3
                </div>
                <div className="flex-1 pt-0.5">
                  <h3 className="text-sm font-semibold text-white mb-3">Make your first scan</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-4">
                    Call <code className="text-teal-400 font-mono text-xs">/scan/prompt</code> with your
                    API token. If <code className="text-teal-400 font-mono text-xs">is_valid</code> is{" "}
                    <code className="text-teal-400 font-mono text-xs">true</code>, forward the prompt to
                    your model. That's it.
                  </p>
                  <FirstScanTabs />
                </div>
              </div>

            </div>
          </section>

          {/* ── Authentication ── */}
          <section id="authentication">
            <SectionLabel>Auth</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Authentication</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Every API request requires a <code className="text-teal-400 font-mono text-xs">Bearer</code> token
              in the <code className="text-teal-400 font-mono text-xs">Authorization</code> header.
              Tokens are issued at login and expire after <strong className="text-slate-300">1 hour</strong>.
            </p>

            <CodeBlock lang="bash">{AUTH_CURL}</CodeBlock>

            <div className="mt-6">
              <Callout>
                Store the token in an environment variable — never hard-code it in your application.
                See the <a href="#token-refresh" className="text-teal-400 hover:underline">Token refresh</a> section
                for how to handle expiry automatically in production.
              </Callout>
            </div>
          </section>

          {/* ── Integration guide ── */}
          <section id="integration">
            <SectionLabel>Integration</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-2">Integration guide</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              The full integration is three steps: scan the prompt, call your model, scan the response.
              If either scan fails, stop immediately — never forward a blocked prompt to your model,
              and never return a blocked response to the user.
            </p>

            <TabBar
              tabs={["Python", "TypeScript", "cURL"]}
              active={integrationTab}
              onChange={setIntegrationTab}
            />
            <CodeBlock lang={integrationTab}>
              {QUICKSTART[integrationTab]}
            </CodeBlock>

            <div className="mt-6 space-y-4">
              <h3 className="text-sm font-semibold text-white">Key points</h3>
              <div className="space-y-3">
                {[
                  {
                    label: "Use sanitized_text, not the original",
                    desc: "Some scanners (like Secrets) redact sensitive content. Always forward sanitized_text to your model and return sanitized_text to your user.",
                  },
                  {
                    label: "Pass prompt to scan/output",
                    desc: "The output scanner pipeline uses the original prompt for context-aware checks (e.g. relevance, factual consistency). Always include the prompt field.",
                  },
                  {
                    label: "Handle is_valid: false gracefully",
                    desc: "Show a user-friendly message rather than a raw error. Avoid leaking which scanner fired — that information should stay in your audit log.",
                  },
                ].map((item) => (
                  <div key={item.label} className="flex gap-3">
                    <span className="text-xs mt-0.5" style={{ color: "#14B8A6" }}>→</span>
                    <div>
                      <p className="text-sm font-medium text-white mb-0.5">{item.label}</p>
                      <p className="text-sm text-slate-500 leading-relaxed">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* ── Response reference ── */}
          <section id="response">
            <SectionLabel>API reference</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Response reference</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Both <code className="text-teal-400 font-mono text-xs">/scan/prompt</code> and{" "}
              <code className="text-teal-400 font-mono text-xs">/scan/output</code> return the same shape:
            </p>

            <CodeBlock lang="json">{SCAN_RESPONSE}</CodeBlock>

            <div
              className="rounded border border-white/5 overflow-hidden mt-6"
              style={{ background: "#0d1426" }}
            >
              <div className="px-5 py-3 border-b border-white/5">
                <p className="text-xs font-mono text-slate-500">Response fields</p>
              </div>
              <div className="px-5 divide-y divide-white/5">
                <ResponseField field="is_valid" type="bool" desc="True means the text passed all active scanners and is safe to use. False means it was blocked — do not proceed." />
                <ResponseField field="sanitized_text" type="string" desc="The text after sanitization. Some scanners redact content (e.g. Secrets replaces API keys with [REDACTED]). Always use this instead of the original." />
                <ResponseField field="scanner_results" type="object" desc="A map of scanner name → risk score (0.0–1.0). Scores above a scanner's configured threshold trigger a violation." />
                <ResponseField field="violation_scanners" type="string[]" desc="Names of scanners that flagged the text. Empty array when is_valid is true." />
                <ResponseField field="audit_log_id" type="number" desc="The ID of the audit log entry for this scan. Use it to pull up the full record in your Project 73 dashboard." />
              </div>
            </div>

            <div className="mt-6 space-y-4">
              <h3 className="text-sm font-semibold text-white mb-3">Endpoints</h3>
              <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
                {[
                  { method: "POST",  path: "/api/auth/login",                   desc: "Exchange username + password for a JWT token" },
                  { method: "POST",  path: "/api/auth/register",                 desc: "Create a new account (viewer role)" },
                  { method: "GET",   path: "/api/auth/me",                       desc: "Return the authenticated user's profile" },
                  { method: "PATCH", path: "/api/auth/me",                       desc: "Update username, full name, or email" },
                  { method: "POST",  path: "/api/auth/change-password",          desc: "Change the authenticated user's password" },
                  { method: "POST",  path: "/api/scan/prompt",                   desc: "Scan a user prompt through all active input scanners" },
                  { method: "POST",  path: "/api/scan/output",                   desc: "Scan a model response through all active output scanners" },
                  { method: "GET",   path: "/api/guardrails",                    desc: "List all guardrail configurations" },
                  { method: "GET",   path: "/api/audit",                         desc: "Retrieve paginated audit logs (filters: direction, scanner, date)" },
                  { method: "GET",   path: "/api/audit/abuse",                   desc: "Audit logs where is_valid=false only" },
                  { method: "GET",   path: "/api/analytics/summary",             desc: "Total scans, violations, average risk score" },
                  { method: "GET",   path: "/api/analytics/trends",              desc: "Violations per day for the last 30 days" },
                  { method: "GET",   path: "/api/connections",                   desc: "List the user's API connections" },
                  { method: "POST",  path: "/api/connections",                   desc: "Create a new API connection" },
                  { method: "GET",   path: "/api/org",                           desc: "Get the current user's organization" },
                  { method: "POST",  path: "/api/org/invite",                    desc: "Invite a member to the organization by email" },
                  { method: "GET",   path: "/api/support/tickets",               desc: "List support tickets (staff: all; user: own tickets)" },
                  { method: "POST",  path: "/api/support/tickets",               desc: "Create a new support ticket" },
                  { method: "POST",  path: "/api/support/tickets/{id}/responses","desc": "Add a reply to a ticket thread" },
                  { method: "GET",   path: "/api/notifications",                 desc: "Unified notification feed (personal + announcements)" },
                  { method: "GET",   path: "/api/notifications/unread-count",    desc: "Number of unread notifications" },
                  { method: "PATCH", path: "/api/notifications/read-all/mark",   desc: "Mark all notifications and announcements as read" },
                ].map((ep, i) => (
                  <div
                    key={ep.path}
                    className="flex items-start gap-4 px-5 py-3"
                    style={{ borderTop: i > 0 ? "1px solid rgba(255,255,255,0.04)" : undefined }}
                  >
                    <span
                      className="shrink-0 text-xs font-mono px-1.5 py-0.5 rounded mt-0.5 w-14 text-center"
                      style={
                        ep.method === "POST"
                          ? { background: "rgba(20,184,166,0.1)", color: "#14B8A6" }
                          : ep.method === "PATCH"
                          ? { background: "rgba(251,191,36,0.1)", color: "#fbbf24" }
                          : { background: "rgba(255,255,255,0.04)", color: "#64748b" }
                      }
                    >
                      {ep.method}
                    </span>
                    <div>
                      <p className="text-xs font-mono text-white mb-0.5">{ep.path}</p>
                      <p className="text-xs text-slate-500">{ep.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* ── Token refresh ── */}
          <section id="token-refresh">
            <SectionLabel>Production</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Token refresh</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Tokens expire after 1 hour. In a long-running service you should cache the token and
              re-fetch it automatically when it nears expiry. The examples below show a simple client
              class that handles this transparently.
            </p>

            <TabBar
              tabs={["Python", "TypeScript"]}
              active={refreshTab}
              onChange={setRefreshTab}
            />
            <CodeBlock lang={refreshTab}>{TOKEN_REFRESH[refreshTab]}</CodeBlock>
          </section>

          {/* ── Roles & access ── */}
          <section id="roles">
            <SectionLabel>Access control</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Roles &amp; access</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Every user has a role that controls what they can see and do. Roles are assigned by an admin
              and cannot be self-upgraded.
            </p>
            <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
              {[
                {
                  role: "viewer",
                  color: "#14B8A6",
                  bg: "rgba(20,184,166,0.08)",
                  desc: "Can scan prompts and responses via the API, view their own audit logs, and submit support tickets. Default role for new accounts.",
                },
                {
                  role: "org_admin",
                  color: "#a78bfa",
                  bg: "rgba(167,139,250,0.08)",
                  desc: "Inherits viewer permissions plus: manage org members and teams, view all audit data scoped to the organization, and manage org-level API connections.",
                },
                {
                  role: "support",
                  color: "#fbbf24",
                  bg: "rgba(251,191,36,0.08)",
                  desc: "Can read and respond to all support tickets, and impersonate viewer and org_admin accounts for debugging. Cannot access admin-only settings.",
                },
                {
                  role: "admin",
                  color: "#f87171",
                  bg: "rgba(248,113,113,0.08)",
                  desc: "Full platform access. Manage all users, roles, guardrail configurations, API connections, and platform-wide analytics. Can broadcast announcements to all users.",
                },
              ].map((r, i) => (
                <div key={r.role} className="flex items-start gap-4 px-5 py-4"
                  style={{ borderTop: i > 0 ? "1px solid rgba(255,255,255,0.04)" : undefined }}>
                  <span className="shrink-0 text-xs font-mono px-2 py-0.5 rounded mt-0.5"
                    style={{ background: r.bg, color: r.color }}>{r.role}</span>
                  <p className="text-sm text-slate-500 leading-relaxed">{r.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* ── Organizations & teams ── */}
          <section id="organizations">
            <SectionLabel>Multi-tenancy</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Organizations &amp; teams</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Project 73 Security is multi-tenant by design. An organization groups users, teams, and API connections
              under one roof. Data is automatically scoped — members only see their org's audit logs and analytics
              unless they're an admin.
            </p>
            <div className="space-y-3">
              {[
                {
                  title: "Creating an organization",
                  desc: "Any admin can create an organization from the Admin Panel. Once created, the admin becomes the org owner and can invite members by email.",
                },
                {
                  title: "Inviting members",
                  desc: "Go to Organization → Invite Member. Enter the user's email and their role within the org. They'll receive an email invite valid for 7 days. Once they accept, they're automatically scoped to the org.",
                },
                {
                  title: "Teams",
                  desc: "Inside an organization you can create teams and assign members. API connections and audit data can be scoped to a team, giving team leads visibility into their own usage without exposing other teams' data.",
                },
                {
                  title: "Data scoping",
                  desc: "Org members see only their org's data. Org admins see the entire org. Platform admins see everything, with a per-org filter available on all analytics and audit pages.",
                },
              ].map((item) => (
                <div key={item.title} className="rounded border border-white/5 p-5 space-y-1.5" style={{ background: "#0d1426" }}>
                  <p className="text-sm font-semibold text-white">{item.title}</p>
                  <p className="text-sm text-slate-500 leading-relaxed">{item.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* ── API connections ── */}
          <section id="connections">
            <SectionLabel>Connections</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">API connections</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              An API connection is a named, authenticated entry point into Project 73 Security. Each connection gets
              its own key (prefixed <code className="text-teal-400 font-mono text-xs">ts_conn_</code>), which you use
              instead of your personal JWT for scan requests. This separates your dashboard identity from your
              application traffic.
            </p>
            <div className="space-y-3">
              {[
                { title: "Why use connections?", desc: "Connections let you attribute scan traffic to a specific environment (production, staging, development) or service. Usage metrics are tracked per connection and visible in the APIs dashboard page." },
                { title: "Creating a connection", desc: "Go to APIs in the dashboard sidebar → Create connection. Give it a name and environment tag. You'll receive a connection key — save it immediately, it's only shown once." },
                { title: "Using a connection key in requests", desc: "Pass the connection key as your Bearer token when calling /scan/prompt or /scan/output. Project 73 will automatically attribute the scan to that connection." },
                { title: "Rotating a connection key", desc: "If a key is compromised, delete the connection and create a new one. Past audit logs for that connection are retained." },
              ].map((item) => (
                <div key={item.title} className="rounded border border-white/5 p-5 space-y-1.5" style={{ background: "#0d1426" }}>
                  <p className="text-sm font-semibold text-white">{item.title}</p>
                  <p className="text-sm text-slate-500 leading-relaxed">{item.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* ── Connection key setup ── */}
          <section id="connection-setup">
            <SectionLabel>Connection keys</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Connection key setup</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              For production applications, use a <strong className="text-slate-300">connection key</strong> (
              <code className="text-teal-400 font-mono text-xs">ts_conn_...</code>) instead of a user JWT.
              Connection keys never expire, are scoped to a named environment, and give each application
              its own independent metrics, spend tracking, and guardrail configuration.
            </p>

            {/* Comparison table */}
            <div className="rounded border border-white/5 overflow-hidden mb-10" style={{ background: "#0d1426" }}>
              <div className="grid grid-cols-3 px-5 py-2.5 border-b border-white/5">
                <span className="text-xs font-mono text-slate-600 uppercase tracking-wider"></span>
                <span className="text-xs font-mono text-slate-600 uppercase tracking-wider">JWT token</span>
                <span className="text-xs font-mono text-teal-500 uppercase tracking-wider">Connection key</span>
              </div>
              {[
                { feature: "Expiry", jwt: "1 hour — must refresh", key: "Never expires" },
                { feature: "Setup", jwt: "Call /auth/login each deploy", key: "Paste key in .env once" },
                { feature: "Traffic attribution", jwt: "Attributed to the user account", key: "Attributed to the named connection" },
                { feature: "Per-app guardrails", jwt: "Not supported", key: "Override which guardrails run per key" },
                { feature: "Spend & token tracking", jwt: "Not supported", key: "Monthly spend limits + alerts" },
                { feature: "Auto-block on abuse", jwt: "Not supported", key: "Block the key when violation rate spikes" },
                { feature: "Best for", jwt: "Dashboard, one-off scripts", key: "Production apps, chatbots, API services" },
              ].map((row, i) => (
                <div
                  key={row.feature}
                  className="grid grid-cols-3 px-5 py-3 text-xs"
                  style={{ borderTop: i > 0 ? "1px solid rgba(255,255,255,0.04)" : undefined }}
                >
                  <span className="text-slate-500 font-mono">{row.feature}</span>
                  <span className="text-slate-600">{row.jwt}</span>
                  <span className="text-teal-400">{row.key}</span>
                </div>
              ))}
            </div>

            {/* Step-by-step */}
            <div className="space-y-10">

              {/* Step 1 */}
              <div className="flex gap-5">
                <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>1</div>
                <div className="flex-1 pt-0.5">
                  <h3 className="text-sm font-semibold text-white mb-2">Create a connection in the dashboard</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-3">
                    Go to <strong className="text-slate-300">Dashboard → APIs</strong> and click{" "}
                    <strong className="text-slate-300">+ New connection</strong>. Give it a descriptive name
                    (e.g. <em className="text-slate-400">production-chatbot</em> or{" "}
                    <em className="text-slate-400">customer-portal-staging</em>) and choose the environment tag.
                  </p>
                  <div className="space-y-1.5">
                    {[
                      "Copy the generated key immediately — it's only shown in full once.",
                      "Optionally set per-token pricing ($/1M tokens) to track monthly spend.",
                      "Optionally set an alert or hard cap to auto-block the key when monthly spend is reached.",
                      "Optionally set an auto-block violation threshold — the key becomes blocked automatically if the violation rate spikes.",
                    ].map((tip) => (
                      <div key={tip} className="flex items-start gap-2 text-sm text-slate-500">
                        <span style={{ color: "#14B8A6" }}>→</span>
                        <span>{tip}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Step 2 */}
              <div className="flex gap-5">
                <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>2</div>
                <div className="flex-1 pt-0.5">
                  <h3 className="text-sm font-semibold text-white mb-2">Add the key to your environment</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-3">
                    Store the connection key in an environment variable — never hard-code it in source code.
                    Treat it with the same care as a database password.
                  </p>
                  <CodeBlock lang="bash">{CONNECTION_ENV}</CodeBlock>
                </div>
              </div>

              {/* Step 3 */}
              <div className="flex gap-5">
                <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>3</div>
                <div className="flex-1 pt-0.5">
                  <h3 className="text-sm font-semibold text-white mb-2">Integrate into your application</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-4">
                    Use the connection key exactly where you would have used a JWT token. The scan API is
                    identical — only the token format changes.
                  </p>
                  <TabBar tabs={["Python", "TypeScript", "cURL"]} active={connTab} onChange={setConnTab} />
                  <CodeBlock lang={connTab}>{connCode[connTab]}</CodeBlock>
                  <div className="mt-4 space-y-2">
                    {[
                      { label: "Use sanitized_text, not the original", desc: "Some scanners redact content (e.g. Secrets replaces API keys with [REDACTED]). Always forward sanitized_text to your model and back to the user." },
                      { label: "Pass prompt to /scan/output", desc: "Output scanners use the original prompt for context-aware checks like relevance and factual consistency. Always include it." },
                      { label: "Don't expose violation_scanners to users", desc: "Log scanner details internally but show users a generic safe message. Leaking which scanner fired helps adversaries tune their bypass attempts." },
                    ].map((item) => (
                      <div key={item.label} className="flex gap-3 pt-2">
                        <span className="text-xs mt-0.5 shrink-0" style={{ color: "#14B8A6" }}>→</span>
                        <div>
                          <p className="text-sm font-medium text-white mb-0.5">{item.label}</p>
                          <p className="text-sm text-slate-500 leading-relaxed">{item.desc}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Step 4 — Reference chatbot */}
              <div className="flex gap-5">
                <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>4</div>
                <div className="flex-1 pt-0.5">
                  <h3 className="text-sm font-semibold text-white mb-2">Starting the reference chatbot</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-3">
                    The Project 73 Security repository includes a ready-to-run reference chatbot (Python + Flask +
                    OpenAI) in the <code className="text-teal-400 font-mono text-xs">chatbot/</code> directory.
                    The Project 73 integration is already wired in — supply your keys and run:
                  </p>
                  <CodeBlock lang="bash">{CONNECTION_CHATBOT}</CodeBlock>
                  <div className="mt-4">
                    <Callout>
                      The reference chatbot <strong>fails open</strong> — if Project 73 Security is unreachable it
                      logs the error and lets the message through. To fail closed instead, edit the fallback
                      return value in{" "}
                      <code className="text-teal-400 font-mono text-xs">chatbot/server.py</code> inside{" "}
                      <code className="text-teal-400 font-mono text-xs">scan_input()</code> and{" "}
                      <code className="text-teal-400 font-mono text-xs">scan_output()</code> to raise an
                      exception instead of returning a pass-through result.
                    </Callout>
                  </div>
                </div>
              </div>

            </div>

            {/* Per-connection guardrails */}
            <div className="mt-12 space-y-4">
              <h3 className="text-sm font-semibold text-white">Per-connection guardrail overrides</h3>
              <p className="text-sm text-slate-500 leading-relaxed">
                By default every connection inherits the globally-active guardrail set you configured in the
                Guardrails dashboard. You can override this per connection — for example, enabling a Regex
                password scanner for one app without turning it on globally.
              </p>
              <div className="space-y-2 mt-3">
                {[
                  { step: "Open Dashboard → APIs", desc: "Find the connection card and click the Guardrails button." },
                  { step: "Enable 'Use guardrails'", desc: "When on, only the guardrails you choose here run for this connection key. The global active set is ignored for this key." },
                  { step: "Toggle scanners on or off", desc: "Use the Input / Output tabs to select individual scanners. Scanners marked 'globally off' can still be enabled per-connection." },
                  { step: "Optionally adjust thresholds", desc: "For scanners with a numeric sensitivity (Toxicity, PromptInjection, BanTopics, etc.) you can override the threshold per connection without changing the global default." },
                  { step: "Test your configuration", desc: "Use the Test scan panel at the bottom of the dialog. It runs the exact guardrail set configured for this connection — no need to use the ts_conn_ key separately." },
                  { step: "Save and deploy", desc: "Changes apply immediately. All in-flight scan requests continue using the previous configuration until the save completes." },
                ].map((item, i) => (
                  <div key={i} className="flex gap-4 rounded border border-white/5 px-5 py-3.5" style={{ background: "#0d1426" }}>
                    <span
                      className="shrink-0 text-xs font-bold mt-0.5 w-5 h-5 rounded-full flex items-center justify-center"
                      style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}
                    >
                      {i + 1}
                    </span>
                    <div>
                      <p className="text-sm font-medium text-white mb-0.5">{item.step}</p>
                      <p className="text-sm text-slate-500 leading-relaxed">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* ── Notifications ── */}
          <section id="notifications">
            <SectionLabel>Notifications</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Notifications</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              The dashboard notification bell combines two streams: personal activity notifications and
              platform-wide announcements from admins. Both are available through the unified
              <code className="text-teal-400 font-mono text-xs mx-1">GET /api/notifications</code> endpoint.
            </p>
            <div className="rounded border border-white/5 overflow-hidden mb-6" style={{ background: "#0d1426" }}>
              {[
                { type: "ticket_new", color: "#14B8A6", bg: "rgba(20,184,166,0.08)", desc: "Fired when a user submits a new support ticket. Delivered to all staff (admin + support roles)." },
                { type: "ticket_response", color: "#a78bfa", bg: "rgba(167,139,250,0.08)", desc: "Fired when a staff member replies to a ticket. Delivered to the ticket owner." },
                { type: "ticket_followup", color: "#fbbf24", bg: "rgba(251,191,36,0.08)", desc: "Fired when a user adds a follow-up to their own ticket. Delivered to staff." },
                { type: "announcement", color: "#f97316", bg: "rgba(249,115,22,0.08)", desc: "Broadcast by admins to all users. Tracked per-user via a read-receipt table." },
                { type: "news", color: "#a78bfa", bg: "rgba(167,139,250,0.08)", desc: "Product updates and changelogs broadcast by admins to all users." },
              ].map((n, i) => (
                <div key={n.type} className="flex items-start gap-4 px-5 py-3.5"
                  style={{ borderTop: i > 0 ? "1px solid rgba(255,255,255,0.04)" : undefined }}>
                  <span className="shrink-0 text-xs font-mono px-1.5 py-0.5 rounded mt-0.5"
                    style={{ background: n.bg, color: n.color, whiteSpace: "nowrap" }}>{n.type}</span>
                  <p className="text-sm text-slate-500 leading-relaxed">{n.desc}</p>
                </div>
              ))}
            </div>
            <Callout>
              The unread count endpoint (<code className="text-teal-400 font-mono text-xs">/api/notifications/unread-count</code>)
              is polled every 20 seconds by the dashboard. Use{" "}
              <code className="text-teal-400 font-mono text-xs">PATCH /api/notifications/read-all/mark</code> to
              mark all personal notifications and all active announcements as read in a single request.
            </Callout>
          </section>

          {/* ── Input scanners ── */}
          <section id="input-scanners">
            <SectionLabel>Scanners</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-2">Input scanners</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Input scanners run on every user prompt before it reaches your model. Enable, disable,
              and tune them from the Guardrails section of the dashboard.
            </p>
            <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
              {INPUT_SCANNERS.map((s, i) => (
                <div
                  key={s.name}
                  className="flex items-start gap-4 px-5 py-3.5"
                  style={{ borderTop: i > 0 ? "1px solid rgba(255,255,255,0.04)" : undefined }}
                >
                  <span
                    className="shrink-0 text-xs font-mono px-1.5 py-0.5 rounded mt-0.5"
                    style={{ background: "rgba(20,184,166,0.08)", color: "#14B8A6", whiteSpace: "nowrap" }}
                  >
                    {s.name}
                  </span>
                  <p className="text-sm text-slate-500 leading-relaxed">{s.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* ── Output scanners ── */}
          <section id="output-scanners">
            <h2 className="text-2xl font-bold text-white tracking-tight mb-2 mt-2">Output scanners</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Output scanners run on every model response before it reaches your user. They operate
              with awareness of the original prompt for context-sensitive checks.
            </p>
            <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
              {OUTPUT_SCANNERS.map((s, i) => (
                <div
                  key={s.name}
                  className="flex items-start gap-4 px-5 py-3.5"
                  style={{ borderTop: i > 0 ? "1px solid rgba(255,255,255,0.04)" : undefined }}
                >
                  <span
                    className="shrink-0 text-xs font-mono px-1.5 py-0.5 rounded mt-0.5"
                    style={{ background: "rgba(167,139,250,0.08)", color: "#a78bfa", whiteSpace: "nowrap" }}
                  >
                    {s.name}
                  </span>
                  <p className="text-sm text-slate-500 leading-relaxed">{s.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* ── Deployment best practices ── */}
          <section id="deployment">
            <SectionLabel>Best practices</SectionLabel>
            <h2 className="text-2xl font-bold text-white tracking-tight mb-4">Going to production</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Once your integration is working locally, here's what to review before going live.
            </p>

            <div className="space-y-5">
              {[
                {
                  title: "Store your token securely",
                  desc: "Keep your Project 73 API token in an environment variable or a secrets manager (e.g. AWS Secrets Manager, Doppler, Vault). Never commit it to your repository or expose it client-side.",
                  code: `# .env (server-side only — never ship this to the browser)
P73_TOKEN=eyJhbGci...`,
                  lang: "bash",
                },
                {
                  title: "Handle token expiry",
                  desc: "Tokens expire after 1 hour. Build automatic refresh into your client — see the Token refresh section above. On a 401 response, re-authenticate and retry once.",
                },
                {
                  title: "Always use sanitized_text",
                  desc: "Some scanners redact sensitive content before returning it. Always forward sanitized_text to your model and return sanitized_text to your user — never the original input.",
                  code: `# Wrong — may contain redacted content
model.chat(user_prompt)

# Correct — safe, post-scan text
scan = p73.scan_prompt(user_prompt)
model.chat(scan["sanitized_text"])`,
                  lang: "python",
                },
                {
                  title: "Don't leak scanner details to users",
                  desc: "violation_scanners tells you which rules fired — useful for your logs, not for your users. Show a generic message instead.",
                  code: `if not scan["is_valid"]:
    # Log internally
    logger.warning("blocked", scanners=scan["violation_scanners"])
    # Show user a safe message
    return "I'm sorry, I can't help with that."`,
                  lang: "python",
                },
                {
                  title: "Set a request timeout",
                  desc: "Scanners run fast, but always set a timeout on your HTTP client so a slow response never blocks your application.",
                  code: `# Python
httpx.post(url, json=body, headers=headers, timeout=5.0)

# TypeScript (fetch doesn't have native timeout — use AbortSignal)
const controller = new AbortController();
setTimeout(() => controller.abort(), 5000);
fetch(url, { signal: controller.signal, ... });`,
                  lang: "python",
                },
              ].map((item) => (
                <div
                  key={item.title}
                  className="rounded border border-white/5 p-5 space-y-3"
                  style={{ background: "#0d1426" }}
                >
                  <p className="text-sm font-semibold text-white">{item.title}</p>
                  <p className="text-sm text-slate-500 leading-relaxed">{item.desc}</p>
                  {item.code && <CodeBlock lang={item.lang ?? "bash"}>{item.code}</CodeBlock>}
                </div>
              ))}
            </div>
          </section>

        </main>
      </div>
    </div>
  );
}
