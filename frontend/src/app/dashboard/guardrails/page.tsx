"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { SCANNER_INTEL, MODEL_TYPE_META } from "@/lib/scanner-intel";

interface Guardrail {
  id: number; name: string; scanner_type: string; direction: string;
  is_active: boolean; on_fail_action: string; params: Record<string, unknown>; order: number;
}

const ON_FAIL_META: Record<string, { label: string; color: string; bg: string }> = {
  block:   { label: "block",   color: "#f87171", bg: "rgba(248,113,113,0.08)" },
  fix:     { label: "fix",     color: "#34d399", bg: "rgba(52,211,153,0.08)"  },
  monitor: { label: "monitor", color: "#fbbf24", bg: "rgba(251,191,36,0.08)"  },
  reask:   { label: "reask",   color: "#60a5fa", bg: "rgba(96,165,250,0.08)"  },
};

// ── Scanner catalog ────────────────────────────────────────────────────────────

interface ScannerTemplate {
  scanner_type: string;
  direction: "input" | "output";
  tagline: string;          // one-liner shown on the picker card
  description: string;      // longer description shown on the guardrail row
  defaultName: string;
  defaultParams: Record<string, unknown>;
}

const CATALOG: ScannerTemplate[] = [
  // ─── Input ───────────────────────────────────────────────────────────────
  {
    scanner_type: "PromptInjection",
    direction: "input",
    tagline: "Block jailbreaks and instruction overrides",
    description: "Detects adversarial prompts that attempt to hijack the model's behaviour or override system instructions.",
    defaultName: "Prompt Injection Filter",
    defaultParams: { threshold: 0.5 },
  },
  {
    scanner_type: "BanTopics",
    direction: "input",
    tagline: "Block specific topics using AI classification",
    description: "Uses zero-shot classification to block prompts that discuss restricted topics such as violence or weapons.",
    defaultName: "Ban Topics",
    defaultParams: { topics: ["violence", "weapons"], threshold: 0.5 },
  },
  {
    scanner_type: "Toxicity",
    direction: "input",
    tagline: "Detect hate speech and harmful language",
    description: "Flags prompts containing hate speech, threats, or other harmful content before they reach the model.",
    defaultName: "Toxicity Filter",
    defaultParams: { threshold: 0.7 },
  },
  {
    scanner_type: "CustomRule",
    direction: "input",
    tagline: "Build your own rules — keywords, patterns, or AI topics",
    description: "Block prompts using your own rules: forbidden keywords, regex patterns, and AI-classified topics. No scanner knowledge required — combine all three in one guardrail.",
    defaultName: "Custom Rule",
    defaultParams: { blocked_keywords: [], blocked_patterns: [], blocked_topics: [], topics_threshold: 0.5 },
  },
  {
    scanner_type: "BanSubstrings",
    direction: "input",
    tagline: "Hard-block specific words or phrases",
    description: "Rejects prompts containing specific forbidden words or phrases. Fast, exact, no AI required.",
    defaultName: "Banned Phrases",
    defaultParams: { substrings: [], match_type: "str", case_sensitive: false, redact: false },
  },
  {
    scanner_type: "BanCompetitors",
    direction: "input",
    tagline: "Prevent competitor mentions from reaching the model",
    description: "Flags prompts that mention competitor products or services by name.",
    defaultName: "Competitor Guard",
    defaultParams: { competitors: [], threshold: 0.5 },
  },
  {
    scanner_type: "Secrets",
    direction: "input",
    tagline: "Catch leaked API keys and credentials",
    description: "Detects and redacts API keys, passwords, and other credentials accidentally included in prompts.",
    defaultName: "Secrets Detector",
    defaultParams: { redact_mode: "all" },
  },
  {
    scanner_type: "TokenLimit",
    direction: "input",
    tagline: "Reject oversized prompts",
    description: "Rejects prompts that exceed the configured token limit, preventing context-window abuse.",
    defaultName: "Token Limit",
    defaultParams: { limit: 4096, encoding_name: "cl100k_base" },
  },
  {
    scanner_type: "Language",
    direction: "input",
    tagline: "Accept only approved languages",
    description: "Restricts accepted input to a configured set of languages.",
    defaultName: "Language Filter",
    defaultParams: { valid_languages: ["en"], threshold: 0.7 },
  },
  {
    scanner_type: "Sentiment",
    direction: "input",
    tagline: "Block strongly negative or hostile prompts",
    description: "Flags prompts with strongly negative sentiment that may indicate hostile intent.",
    defaultName: "Sentiment Filter",
    defaultParams: { threshold: -0.1 },
  },
  {
    scanner_type: "Gibberish",
    direction: "input",
    tagline: "Reject incoherent or nonsensical input",
    description: "Rejects incoherent or nonsensical text that is unlikely to be a legitimate request.",
    defaultName: "Gibberish Detector",
    defaultParams: { threshold: 0.7 },
  },
  {
    scanner_type: "InvisibleText",
    direction: "input",
    tagline: "Detect hidden Unicode injection characters",
    description: "Detects hidden Unicode characters often used to smuggle instructions into prompts.",
    defaultName: "Invisible Text Detector",
    defaultParams: {},
  },
  {
    scanner_type: "Regex",
    direction: "input",
    tagline: "Block prompts matching custom patterns",
    description: "Blocks prompts that match one or more custom regular expression patterns.",
    defaultName: "Regex Filter",
    defaultParams: { patterns: [], is_blocked: true },
  },
  {
    scanner_type: "BanCode",
    direction: "input",
    tagline: "Block prompts containing code snippets",
    description: "Blocks prompts that contain or explicitly request code in restricted programming languages.",
    defaultName: "Code Block",
    defaultParams: { languages: [] },
  },
  // ─── Output ──────────────────────────────────────────────────────────────
  {
    scanner_type: "Toxicity",
    direction: "output",
    tagline: "Block toxic or offensive model responses",
    description: "Flags model responses containing hate speech, threats, or harmful content before returning to the user.",
    defaultName: "Output Toxicity Filter",
    defaultParams: { threshold: 0.7 },
  },
  {
    scanner_type: "NoRefusal",
    direction: "output",
    tagline: "Detect when the model refuses legitimate requests",
    description: "Detects when the model inappropriately refuses a legitimate request, ensuring availability.",
    defaultName: "No Refusal Check",
    defaultParams: { threshold: 0.5 },
  },
  {
    scanner_type: "Bias",
    direction: "output",
    tagline: "Catch biased or discriminatory responses",
    description: "Identifies biased or discriminatory language in model responses before they reach the user.",
    defaultName: "Bias Detector",
    defaultParams: { threshold: 0.7 },
  },
  {
    scanner_type: "FactualConsistency",
    direction: "output",
    tagline: "Verify the response matches the prompt",
    description: "Checks that the model's response is factually consistent with the source prompt.",
    defaultName: "Factual Consistency",
    defaultParams: { threshold: 0.5 },
  },
  {
    scanner_type: "Relevance",
    direction: "output",
    tagline: "Ensure responses stay on-topic",
    description: "Checks that the model's response is semantically relevant to the original prompt.",
    defaultName: "Relevance Check",
    defaultParams: { threshold: 0.5 },
  },
  {
    scanner_type: "MaliciousURLs",
    direction: "output",
    tagline: "Scan URLs in responses for malware",
    description: "Scans URLs in the model's response against known malicious domain lists.",
    defaultName: "Malicious URL Scanner",
    defaultParams: { threshold: 0.5 },
  },
  {
    scanner_type: "BanTopics",
    direction: "output",
    tagline: "Block topic mentions in responses",
    description: "Prevents the model from discussing restricted topics in its responses.",
    defaultName: "Output Topic Filter",
    defaultParams: { topics: [], threshold: 0.5 },
  },
  {
    scanner_type: "BanCompetitors",
    direction: "output",
    tagline: "Stop the model promoting competitors",
    description: "Prevents the model from mentioning or recommending competitor products in its responses.",
    defaultName: "Output Competitor Guard",
    defaultParams: { competitors: [], threshold: 0.5 },
  },
  {
    scanner_type: "Sentiment",
    direction: "output",
    tagline: "Block negative or hostile model responses",
    description: "Flags model responses with strongly negative sentiment before returning them to the user.",
    defaultName: "Output Sentiment Filter",
    defaultParams: { threshold: -0.1 },
  },
  {
    scanner_type: "ReadingTime",
    direction: "output",
    tagline: "Limit response length by reading time",
    description: "Flags responses that would take longer than a configured time to read.",
    defaultName: "Reading Time Limit",
    defaultParams: { max_time: 5 },
  },
  {
    scanner_type: "LanguageSame",
    direction: "output",
    tagline: "Ensure response matches prompt language",
    description: "Ensures the model responds in the same language as the user's prompt.",
    defaultName: "Same Language Check",
    defaultParams: { threshold: 0.7 },
  },
  {
    scanner_type: "CustomRule",
    direction: "output",
    tagline: "Build your own rules — keywords, patterns, or AI topics",
    description: "Block model responses using your own rules: forbidden keywords, regex patterns, and AI-classified topics. No scanner knowledge required.",
    defaultName: "Custom Output Rule",
    defaultParams: { blocked_keywords: [], blocked_patterns: [], blocked_topics: [], topics_threshold: 0.5 },
  },
  {
    scanner_type: "Regex",
    direction: "output",
    tagline: "Block responses matching custom patterns",
    description: "Blocks model responses that match one or more custom regular expression patterns.",
    defaultName: "Output Regex Filter",
    defaultParams: { patterns: [], is_blocked: true },
  },
];

// ── Helpers ────────────────────────────────────────────────────────────────────

function Toggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0"
      style={{ background: active ? "#515594" : "#1a2236" }}
    >
      <span className="inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform"
        style={{ transform: active ? "translateX(18px)" : "translateX(2px)" }} />
    </button>
  );
}

const inputStyle = {
  background: "var(--bg)",
  border: "1px solid var(--border-input)",
  color: "var(--text)",
};

// ── Scanner catalog picker ────────────────────────────────────────────────────

function ScannerCatalog({
  onSelect,
  onClose,
}: {
  onSelect: (tpl: ScannerTemplate) => void;
  onClose: () => void;
}) {
  const [dirTab, setDirTab] = useState<"input" | "output">("input");
  const visible = CATALOG.filter((t) => t.direction === dirTab);

  return (
    <div className="rounded border border-white/5 p-6 space-y-5" style={{ background: "var(--card)" }}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-white">Choose a scanner</p>
          <p className="text-xs text-slate-500 mt-0.5">Pick the type of protection you want to add.</p>
        </div>
        <button onClick={onClose} className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Cancel</button>
      </div>

      {/* Direction tabs */}
      <div className="flex gap-1 p-1 rounded w-fit" style={{ background: "var(--bg)" }}>
        {(["input", "output"] as const).map((d) => (
          <button key={d} onClick={() => setDirTab(d)}
            className="px-4 py-1.5 rounded text-xs font-medium transition-colors capitalize"
            style={dirTab === d ? { background: "#515594", color: "#0A0F1F" } : { color: "var(--text-dim)" }}>
            {d === "input" ? "Input — scan prompts" : "Output — scan responses"}
          </button>
        ))}
      </div>

      {/* Scanner grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {visible.filter((t) => t.scanner_type !== "CustomRule").map((tpl) => (
          <button
            key={`${tpl.direction}-${tpl.scanner_type}`}
            type="button"
            onClick={() => onSelect(tpl)}
            className="text-left rounded border px-4 py-3.5 transition-all group"
            style={{ background: "var(--bg)", borderColor: "var(--border)" }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(81,85,148,0.3)")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.05)")}
          >
            <div className="flex items-start justify-between gap-2 mb-1">
              <span className="text-xs font-mono font-medium text-white">{tpl.scanner_type}</span>
              <span className="text-xs text-slate-700 group-hover:text-[#515594] transition-colors shrink-0">Select →</span>
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">{tpl.tagline}</p>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Code reference panel (Custom Rule) ───────────────────────────────────────

const CODE_TAB_STYLES = {
  active: { background: "#515594", color: "#0A0F1F" },
  inactive: { color: "var(--text-dim)" },
};

function CodeReference({ direction, threshold }: { direction: "input" | "output"; threshold: number }) {
  const [tab, setTab] = useState<"api" | "python">("api");
  const [open, setOpen] = useState(false);

  const apiJson = JSON.stringify(
    {
      name: "My Custom Rule",
      scanner_type: "CustomRule",
      direction,
      params: {
        blocked_keywords: ["forbidden phrase", "competitor name"],
        blocked_patterns: ["\\b\\d{16}\\b"],
        blocked_topics: ["how to make weapons", "illegal activity"],
        topics_threshold: threshold,
        _description: "Describe what this guardrail blocks and why.",
      },
      order: 1,
    },
    null,
    2
  );

  const pythonCode = `# Drop this file in: backend/app/services/my_scanner.py
#
# Requirements:
#   scan(prompt, output="") must return (text, is_valid, score)
#     is_valid = False  → blocked
#     score    = 0–1    → risk level (1 = highest risk)

class MyScanner:
    \"\"\"Custom scanner compatible with the llm-guard Scanner protocol.\"\"\"

    def __init__(self, *, direction: str = "${direction}", **kwargs):
        self._direction = direction
        # initialise your model or rule set here

    def scan(self, prompt: str, output: str = "") -> tuple[str, bool, float]:
        # Pick the text to inspect based on direction
        text = output if (self._direction == "output" and output) else prompt

        # ── Your detection logic ──────────────────────────────────
        if "forbidden" in text.lower():
            return text, False, 1.0   # blocked, risk = 100 %

        # You can also call an ML model here:
        # score = my_model.predict(text)
        # if score > ${threshold}:
        #     return text, False, score

        return text, True, 0.0        # passed, no risk
        # ─────────────────────────────────────────────────────────


# Register it in scanner_engine.py → _import_scanner():
#
#   elif config.scanner_type == "MyScanner":
#       from app.services.my_scanner import MyScanner
#       return MyScanner(direction=direction, **params)`;

  return (
    <div className="rounded border border-white/5 overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-xs text-slate-500 hover:text-slate-300 transition-colors"
      >
        <span className="font-medium">Developer reference — API &amp; Python examples</span>
        <span className="font-mono text-slate-700">{open ? "▲ hide" : "▼ show"}</span>
      </button>

      {open && (
        <div className="border-t border-white/5">
          {/* Tab bar */}
          <div className="flex gap-1 p-2" style={{ background: "var(--card)" }}>
            {(["api", "python"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className="px-3 py-1 rounded text-xs font-medium transition-colors"
                style={tab === t ? CODE_TAB_STYLES.active : CODE_TAB_STYLES.inactive}
              >
                {t === "api" ? "REST API (JSON)" : "Python class"}
              </button>
            ))}
          </div>

          {/* Code block */}
          <div className="relative">
            {tab === "api" && (
              <div className="px-4 pb-2 pt-1 text-xs text-slate-500 font-mono">
                POST /api/guardrails
              </div>
            )}
            <pre
              className="overflow-x-auto px-4 pb-4 text-xs leading-relaxed"
              style={{ color: "var(--text-muted)", fontFamily: "ui-monospace, SFMono-Regular, monospace", whiteSpace: "pre" }}
            >
              {tab === "api" ? apiJson : pythonCode}
            </pre>
          </div>

          {/* Footer note */}
          <div className="px-4 pb-4 text-xs text-slate-700 leading-relaxed border-t border-white/5 pt-3">
            {tab === "api"
              ? "Use this payload with your API token (Authorization: Bearer <token>) to create a guardrail programmatically. All fields in params are optional — omit any you don't need."
              : "Place your scanner class in the backend, then register it in scanner_engine.py. The scan() signature is the only contract — everything else is yours to define."}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Confirm / configure form ──────────────────────────────────────────────────

function NewGuardrailForm({
  template,
  existingCount,
  onCreated,
  onBack,
}: {
  template: ScannerTemplate;
  existingCount: number;
  onCreated: (id: number) => void;
  onBack: () => void;
}) {
  const isCustom = template.scanner_type === "CustomRule";
  const [name, setName] = useState(template.defaultName);
  const [description, setDescription] = useState("");
  const [direction, setDirection] = useState<"input" | "output">(template.direction);
  const [threshold, setThreshold] = useState(0.5);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const params = {
        ...template.defaultParams,
        ...(isCustom ? { topics_threshold: threshold } : {}),
        ...(description.trim() ? { _description: description.trim() } : {}),
      };
      const created = await api.post<Guardrail>("/guardrails", {
        name,
        scanner_type: template.scanner_type,
        direction: isCustom ? direction : template.direction,
        params,
        order: existingCount + 1,
      });
      onCreated(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create guardrail");
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleCreate} className="rounded border border-white/5 p-6 space-y-5" style={{ background: "var(--card)" }}>
      <div className="flex items-center gap-3">
        <button type="button" onClick={onBack} className="text-xs text-slate-600 hover:text-slate-400 transition-colors">← Back</button>
        <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ background: "rgba(81,85,148,0.1)", color: "#515594" }}>
          {template.scanner_type}
        </span>
        {!isCustom && <span className="text-xs text-slate-600 capitalize">{template.direction} scanner</span>}
      </div>

      <p className="text-xs text-slate-500 leading-relaxed border-l-2 pl-3" style={{ borderColor: "rgba(81,85,148,0.3)" }}>
        {template.description}
      </p>

      <div className="space-y-4">
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Display name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="w-full rounded px-3 py-2 text-sm outline-none"
            style={inputStyle}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">
            Description <span className="normal-case text-slate-700">(optional)</span>
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="Describe what this guardrail protects against and why it was added…"
            className="w-full rounded px-3 py-2 text-sm outline-none resize-none"
            style={{ ...inputStyle, fontFamily: "inherit" }}
          />
        </div>

        {/* Custom rule extras */}
        {isCustom && (
          <>
            {/* Direction */}
            <div>
              <label className="block text-xs text-slate-500 mb-2 uppercase tracking-wider">Scan direction</label>
              <div className="flex gap-2">
                {(["input", "output"] as const).map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDirection(d)}
                    className="flex-1 py-2 rounded text-xs font-medium transition-colors capitalize"
                    style={
                      direction === d
                        ? { background: "#515594", color: "#0A0F1F" }
                        : { background: "var(--bg)", color: "var(--text-dim)", border: "1px solid rgba(255,255,255,0.06)" }
                    }
                  >
                    {d === "input" ? "Input — scan prompts" : "Output — scan responses"}
                  </button>
                ))}
              </div>
              <p className="text-xs text-slate-600 mt-1.5">
                {direction === "input"
                  ? "This guardrail will run on every user prompt before it reaches the model."
                  : "This guardrail will run on every model response before it reaches the user."}
              </p>
            </div>

            {/* Detection threshold */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs text-slate-500 uppercase tracking-wider">Detection threshold</label>
                <span className="text-sm font-mono font-semibold tabular-nums" style={{ color: "#515594" }}>{threshold.toFixed(2)}</span>
              </div>
              <input
                type="range" min={0} max={1} step={0.05}
                value={threshold}
                onChange={(e) => setThreshold(parseFloat(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                style={{
                  background: `linear-gradient(to right, #515594 ${threshold * 100}%, #1a2236 ${threshold * 100}%)`,
                  outline: "none",
                }}
              />
              <div className="flex justify-between mt-1">
                <span className="text-xs text-slate-700 font-mono">0 — stricter</span>
                <span className="text-xs text-slate-700 font-mono">1 — looser</span>
              </div>
              <p className="text-xs text-slate-600 mt-2">Applies to AI topic classification. Keyword and pattern rules always block regardless of this value.</p>
            </div>
          </>
        )}
      </div>

      {!isCustom && (
        <div className="rounded px-4 py-3 text-xs text-slate-500 leading-relaxed" style={{ background: "var(--bg)" }}>
          Default settings will be applied. You can fine-tune thresholds, topics, and keywords on the next screen.
        </div>
      )}

      {isCustom && (
        <CodeReference direction={direction} threshold={threshold} />
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}

      <div className="flex gap-3">
        <button type="submit" disabled={saving}
          className="text-sm font-medium px-5 py-2 rounded disabled:opacity-50"
          style={{ background: "#515594", color: "#0A0F1F" }}>
          {saving ? "Creating…" : "Create guardrail →"}
        </button>
        <button type="button" onClick={onBack} className="text-xs px-4 py-2 rounded border border-white/10 text-slate-400">
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type AddStep = "closed" | "catalog" | "configure";

export default function GuardrailsPage() {
  const router = useRouter();
  const { data, error, mutate } = useSWR<Guardrail[]>("/guardrails", () => api.get<Guardrail[]>("/guardrails"));
  const [tab, setTab] = useState<"input" | "output">("input");
  const [addStep, setAddStep] = useState<AddStep>("closed");
  const [selectedTemplate, setSelectedTemplate] = useState<ScannerTemplate | null>(null);

  async function handleToggle(id: number) {
    await api.patch(`/guardrails/${id}/toggle`);
    mutate();
  }

  function handleSelectTemplate(tpl: ScannerTemplate) {
    setSelectedTemplate(tpl);
    setAddStep("configure");
  }

  function handleCreated(id: number) {
    mutate();
    setAddStep("closed");
    setSelectedTemplate(null);
    router.push(`/dashboard/guardrails/${id}`);
  }

  const filtered = (data ?? []).filter((g) => g.direction === tab);
  const existingCount = data?.length ?? 0;

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Tabs + add button */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 p-1 rounded" style={{ background: "var(--card)" }}>
          {(["input", "output"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className="px-4 py-1.5 rounded text-xs font-medium transition-colors capitalize"
              style={tab === t ? { background: "#515594", color: "#0A0F1F" } : { color: "var(--text-dim)" }}>
              {t}
            </button>
          ))}
        </div>
        {addStep === "closed" && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                const tpl = CATALOG.find(
                  (t) => t.scanner_type === "CustomRule" && t.direction === tab
                )!;
                setSelectedTemplate(tpl);
                setAddStep("configure");
              }}
              className="text-xs font-medium px-3 py-1.5 rounded transition-colors"
              style={{ background: "rgba(81,85,148,0.1)", color: "#515594", border: "1px solid rgba(81,85,148,0.2)" }}
            >
              + Build custom rule
            </button>
          </div>
        )}
      </div>

      {/* Step 1 — scanner catalog */}
      {addStep === "catalog" && (
        <ScannerCatalog
          onSelect={handleSelectTemplate}
          onClose={() => setAddStep("closed")}
        />
      )}

      {/* Step 2 — configure + create */}
      {addStep === "configure" && selectedTemplate && (
        <NewGuardrailForm
          template={selectedTemplate}
          existingCount={existingCount}
          onCreated={handleCreated}
          onBack={() => { setAddStep("closed"); setSelectedTemplate(null); }}
        />
      )}

      {error && <p className="text-xs text-red-400">Failed to load guardrails.</p>}

      {/* Scanner list */}
      <div className="rounded border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
        {!data ? (
          <div className="p-6 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-14 rounded animate-pulse" style={{ background: "var(--card2)" }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="px-6 py-8 text-sm text-slate-600 text-center">
            No {tab} guardrails configured.
          </p>
        ) : filtered.map((g, idx) => {
          const customDesc = typeof g.params?._description === "string" ? g.params._description : null;
          const autoDesc = CATALOG.find(
            (t) => t.scanner_type === g.scanner_type && t.direction === g.direction
          )?.description ?? "No description available.";
          const intel = SCANNER_INTEL[g.scanner_type];
          const typeMeta = intel ? MODEL_TYPE_META[intel.modelType] : null;

          return (
            <div key={g.id} className="flex items-start gap-4 px-6 py-4 transition-colors"
              style={{ borderTop: idx > 0 ? "1px solid rgba(255,255,255,0.04)" : undefined }}>
              <div className="pt-0.5">
                <Toggle active={g.is_active} onToggle={() => handleToggle(g.id)} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                  <p className="text-sm text-white truncate">{g.name}</p>
                  <span className="text-xs font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{ background: "rgba(81,85,148,0.08)", color: "#515594" }}>
                    {g.scanner_type}
                  </span>
                  {typeMeta && (
                    <span className="text-xs font-medium px-1.5 py-0.5 rounded shrink-0"
                      style={{ background: typeMeta.bg, color: typeMeta.color }}>
                      {typeMeta.label}
                    </span>
                  )}
                  {(() => {
                    const action = g.on_fail_action ?? "block";
                    const m = ON_FAIL_META[action] ?? ON_FAIL_META.block;
                    return (
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded shrink-0"
                        style={{ background: m.bg, color: m.color }}>
                        {m.label}
                      </span>
                    );
                  })()}
                </div>
                <p className="text-xs text-slate-500 leading-relaxed mb-1">
                  {customDesc ?? autoDesc}
                </p>
                {intel?.model && (
                  <p className="text-xs font-mono" style={{ color: "var(--text-dim)" }}>
                    {intel.model}
                  </p>
                )}
              </div>
              <span className="text-xs text-slate-700 font-mono shrink-0 mt-0.5">#{g.order}</span>
              <a href={`/dashboard/guardrails/${g.id}`}
                className="text-xs text-slate-500 hover:text-white transition-colors shrink-0 mt-0.5">
                Details →
              </a>
            </div>
          );
        })}
      </div>
    </div>
  );
}
