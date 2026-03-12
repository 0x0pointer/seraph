"use client";

import { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { SCANNER_INTEL, MODEL_TYPE_META } from "@/lib/scanner-intel";

interface Guardrail {
  id: number; name: string; scanner_type: string; direction: string;
  is_active: boolean; on_fail_action: string; params: Record<string, unknown>; order: number;
}

// ── Param schema definitions ──────────────────────────────────────────────────

type FieldType = "slider" | "number" | "boolean" | "tags" | "select";

interface FieldDef {
  key: string;
  label: string;
  description: string;
  type: FieldType;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  options?: { label: string; value: string }[];
}

const SCANNER_PARAMS: Record<string, FieldDef[]> = {
  PromptInjection: [
    { key: "threshold", label: "Detection threshold", type: "slider", default: 0.5, min: 0, max: 1, step: 0.05,
      description: "The AI assigns a 0–1 confidence score to each prompt for injection attempts. Prompts scoring above this threshold are blocked. Lower values catch more attacks but may produce false positives on unusual-but-legitimate prompts. The default of 0.5 is a good starting point." },
  ],
  BanTopics: [
    { key: "topics", label: "Banned topics", type: "tags", default: [],
      description: "Descriptive phrases for topics to block. Use natural language — e.g. \"how to make weapons\", \"physical violence and assault\"." },
    { key: "threshold", label: "Detection threshold", type: "slider", default: 0.5, min: 0, max: 1, step: 0.05,
      description: "Classification confidence required to block the prompt. Lower catches more but risks false positives." },
  ],
  Toxicity: [
    { key: "threshold", label: "Toxicity threshold", type: "slider", default: 0.7, min: 0, max: 1, step: 0.05,
      description: "Risk score above which the prompt is blocked. Higher values only catch clearly toxic content." },
  ],
  TokenLimit: [
    { key: "limit", label: "Maximum tokens", type: "number", default: 4096, min: 1, max: 128000, step: 1,
      description: "Prompts longer than this number of tokens will be rejected." },
    { key: "encoding_name", label: "Tokeniser encoding", type: "select", default: "cl100k_base",
      description: "The tokeniser used to count tokens. Match this to your LLM provider.",
      options: [
        { label: "cl100k_base — GPT-4 / GPT-3.5", value: "cl100k_base" },
        { label: "p50k_base — Codex", value: "p50k_base" },
        { label: "r50k_base — GPT-3", value: "r50k_base" },
      ] },
  ],
  Secrets: [
    { key: "redact_mode", label: "What to do when a secret is detected", type: "select", default: "all",
      description: "Choose whether to block the prompt outright or redact the sensitive value.",
      options: [
        { label: "Block the prompt", value: "all" },
        { label: "Partial redaction — show first and last characters", value: "partial" },
        { label: "Full redaction — replace with [REDACTED]", value: "none" },
      ] },
  ],
  BanSubstrings: [
    { key: "substrings", label: "Banned words or phrases", type: "tags", default: [],
      description: "Exact strings that must not appear in the prompt. Add each phrase separately." },
    { key: "match_type", label: "Matching mode", type: "select", default: "str",
      description: "Controls how strictly the phrase must match.",
      options: [
        { label: "Substring — match anywhere in the text", value: "str" },
        { label: "Whole word — only match full words", value: "word" },
        { label: "Exact — entire prompt must equal the phrase", value: "str_exact" },
      ] },
    { key: "case_sensitive", label: "Case sensitive matching", type: "boolean", default: false,
      description: "Turn on to require exact casing. Off means \"hello\" also blocks \"Hello\" and \"HELLO\"." },
    { key: "redact", label: "Redact instead of block", type: "boolean", default: false,
      description: "Replace the matched phrase with [REDACTED] rather than rejecting the entire prompt." },
  ],
  BanCompetitors: [
    { key: "competitors", label: "Competitor names", type: "tags", default: [],
      description: "Company or product names to detect. Add each name separately." },
    { key: "threshold", label: "Detection threshold", type: "slider", default: 0.5, min: 0, max: 1, step: 0.05,
      description: "The AI assigns a 0–1 confidence score to each detected competitor mention. Lower values catch borderline or implicit references; higher values only block clear, unambiguous mentions. Raise this if you see too many false positives." },
  ],
  Language: [
    { key: "valid_languages", label: "Allowed languages", type: "tags", default: ["en"],
      description: "ISO 639-1 language codes (e.g. en, de, fr, es). Prompts in other languages are blocked." },
    { key: "threshold", label: "Detection confidence", type: "slider", default: 0.7, min: 0, max: 1, step: 0.05,
      description: "Minimum confidence required before the detected language is acted upon." },
  ],
  Gibberish: [
    { key: "threshold", label: "Gibberish threshold", type: "slider", default: 0.7, min: 0, max: 1, step: 0.05,
      description: "Risk score above which the input is classified as gibberish and rejected. Set higher (0.8+) to only catch obvious nonsense; lower (0.5–0.6) to also block thinly disguised junk input. Prompts with unusual technical terminology may score high — tune accordingly." },
  ],
  Sentiment: [
    { key: "threshold", label: "Minimum acceptable sentiment", type: "slider", default: -0.1, min: -1, max: 0, step: 0.05,
      description: "Prompts scoring below this value are blocked. −1 = very negative, 0 = neutral. Set to −0.5 to only block strongly negative content." },
  ],
  Code: [
    { key: "languages", label: "Blocked programming languages", type: "tags", default: [],
      description: "Languages whose code should be detected (e.g. python, javascript, bash). Leave empty to detect all code." },
  ],
  BanCode: [
    { key: "languages", label: "Blocked programming languages", type: "tags", default: [],
      description: "Languages whose code snippets should be blocked in prompts." },
  ],
  Regex: [
    { key: "patterns", label: "Regular expression patterns", type: "tags", default: [],
      description: "Patterns to match against the prompt. Add each pattern separately." },
    { key: "is_blocked", label: "Block on match", type: "boolean", default: true,
      description: "Block the prompt when a pattern matches. Disable to log only." },
  ],
  InvisibleText: [],
  CustomRule: [
    {
      key: "blocked_keywords",
      label: "Blocked keywords & phrases",
      type: "tags",
      default: [],
      description: "Any text containing one of these words or phrases is blocked immediately. Case-insensitive. Add each entry separately.",
    },
    {
      key: "blocked_patterns",
      label: "Blocked patterns (advanced)",
      type: "tags",
      default: [],
      description: "Regular expressions matched case-insensitively against the full text. E.g. \\bpassword\\b blocks the whole word \"password\". Add each pattern separately.",
    },
    {
      key: "blocked_topics",
      label: "Blocked topics (AI classification)",
      type: "tags",
      default: [],
      description: "Describe topics to block in plain English — e.g. \"how to make weapons\" or \"financial advice\". Uses AI to detect these topics. Leave empty to skip AI classification (much faster).",
    },
    {
      key: "topics_threshold",
      label: "Topic detection sensitivity",
      type: "slider",
      default: 0.5,
      min: 0,
      max: 1,
      step: 0.05,
      description: "How confident the AI must be before blocking. Lower = stricter. Only applies when blocked topics are configured.",
    },
  ],
  // Output scanners
  NoRefusal: [
    { key: "threshold", label: "Refusal detection threshold", type: "slider", default: 0.5, min: 0, max: 1, step: 0.05,
      description: "Confidence above which a response is flagged as an inappropriate refusal (e.g. the model declining to answer a legitimate question). Lower values catch more refusals including subtle ones; higher values only flag clear-cut refusals. Tune this if you want to detect when your LLM is being overly cautious." },
  ],
  Bias: [
    { key: "threshold", label: "Bias threshold", type: "slider", default: 0.7, min: 0, max: 1, step: 0.05,
      description: "Risk score above which the response is considered biased and blocked." },
  ],
  FactualConsistency: [
    { key: "threshold", label: "Consistency threshold", type: "slider", default: 0.5, min: 0, max: 1, step: 0.05,
      description: "Minimum factual consistency score required between the prompt and the response." },
  ],
  MaliciousURLs: [
    { key: "threshold", label: "Malicious URL threshold", type: "slider", default: 0.5, min: 0, max: 1, step: 0.05,
      description: "Confidence above which a URL is classified as malicious." },
  ],
  Relevance: [
    { key: "threshold", label: "Relevance threshold", type: "slider", default: 0.5, min: 0, max: 1, step: 0.05,
      description: "Minimum semantic similarity between the prompt and response required to pass." },
  ],
  ReadingTime: [
    { key: "max_time", label: "Maximum reading time (minutes)", type: "number", default: 5, min: 0.5, max: 60, step: 0.5,
      description: "Responses that would take longer than this to read are flagged." },
  ],
  LanguageSame: [
    { key: "threshold", label: "Language match confidence", type: "slider", default: 0.7, min: 0, max: 1, step: 0.05,
      description: "Minimum confidence that the response language matches the prompt language." },
  ],
};

// ── Field components ──────────────────────────────────────────────────────────

const fieldBg = { background: "var(--bg)", border: "1px solid var(--border-input)", color: "var(--text)" };

function SliderField({ field, value, onChange }: { field: FieldDef; value: number; onChange: (v: number) => void }) {
  const pct = ((value - (field.min ?? 0)) / ((field.max ?? 1) - (field.min ?? 0))) * 100;

  // Show the strictness band guide only for standard 0–1 threshold sliders
  const isThresholdSlider = (field.min ?? 0) === 0 && (field.max ?? 1) === 1;
  const strictLabel = value < 0.35 ? "strict" : value < 0.65 ? "balanced" : "permissive";
  const strictColor = value < 0.35 ? "#f87171" : value < 0.65 ? "#fbbf24" : "#515594";

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs text-slate-500 uppercase tracking-wider">{field.label}</label>
        <div className="flex items-center gap-2">
          {isThresholdSlider && (
            <span className="text-xs font-mono capitalize" style={{ color: strictColor }}>{strictLabel}</span>
          )}
          <span className="text-sm font-mono font-semibold tabular-nums" style={{ color: "#515594" }}>{value.toFixed(2)}</span>
        </div>
      </div>
      <input
        type="range"
        min={field.min ?? 0} max={field.max ?? 1} step={field.step ?? 0.05}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
        style={{
          background: `linear-gradient(to right, #515594 ${pct}%, #1a2236 ${pct}%)`,
          outline: "none",
        }}
      />
      {isThresholdSlider ? (
        <div className="mt-2">
          <div className="flex h-1 rounded-full overflow-hidden">
            <div className="flex-[35]" style={{ background: "rgba(248,113,113,0.35)" }} />
            <div className="flex-[30]" style={{ background: "rgba(251,191,36,0.35)" }} />
            <div className="flex-[35]" style={{ background: "rgba(81,85,148,0.35)" }} />
          </div>
          <div className="flex justify-between mt-0.5">
            <span className="text-xs font-mono" style={{ color: "rgba(248,113,113,0.55)" }}>0 · strict</span>
            <span className="text-xs text-slate-700 font-mono">0.5</span>
            <span className="text-xs font-mono" style={{ color: "rgba(81,85,148,0.55)" }}>1 · permissive</span>
          </div>
        </div>
      ) : (
        <div className="flex justify-between mt-1">
          <span className="text-xs text-slate-700 font-mono">{field.min ?? 0}</span>
          <span className="text-xs text-slate-700 font-mono">{field.max ?? 1}</span>
        </div>
      )}
      <p className="text-xs text-slate-600 mt-2 leading-relaxed">{field.description}</p>
    </div>
  );
}

function NumberField({ field, value, onChange }: { field: FieldDef; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">{field.label}</label>
      <input
        type="number"
        min={field.min} max={field.max} step={field.step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full rounded px-3 py-2 text-sm outline-none"
        style={fieldBg}
      />
      <p className="text-xs text-slate-600 mt-2 leading-relaxed">{field.description}</p>
    </div>
  );
}

function BooleanField({ field, value, onChange }: { field: FieldDef; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start gap-4">
      <button
        type="button"
        onClick={() => onChange(!value)}
        className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 mt-0.5"
        style={{ background: value ? "#515594" : "#1a2236" }}
      >
        <span className="inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform"
          style={{ transform: value ? "translateX(18px)" : "translateX(2px)" }} />
      </button>
      <div>
        <p className="text-sm text-white leading-tight">{field.label}</p>
        <p className="text-xs text-slate-600 mt-1 leading-relaxed">{field.description}</p>
      </div>
    </div>
  );
}

function TagsField({ field, value, onChange }: { field: FieldDef; value: string[]; onChange: (v: string[]) => void }) {
  const [input, setInput] = useState("");

  function add() {
    const trimmed = input.trim();
    if (trimmed && !value.includes(trimmed)) onChange([...value, trimmed]);
    setInput("");
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") { e.preventDefault(); add(); }
    if (e.key === "Backspace" && input === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <div>
      <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">{field.label}</label>
      <div
        className="w-full rounded px-3 py-2 min-h-[42px] flex flex-wrap gap-1.5 cursor-text"
        style={fieldBg}
        onClick={() => document.getElementById(`tags-input-${field.key}`)?.focus()}
      >
        {value.map((tag) => (
          <span key={tag} className="flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded"
            style={{ background: "rgba(81,85,148,0.12)", color: "#515594" }}>
            {tag}
            <button type="button" onClick={() => onChange(value.filter((t) => t !== tag))}
              className="opacity-60 hover:opacity-100 transition-opacity leading-none">
              ×
            </button>
          </span>
        ))}
        <input
          id={`tags-input-${field.key}`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => { if (input.trim()) add(); }}
          placeholder={value.length === 0 ? "Type and press Enter to add…" : ""}
          className="flex-1 min-w-[140px] bg-transparent text-sm outline-none text-slate-300 placeholder-slate-700"
        />
      </div>
      <p className="text-xs text-slate-600 mt-2 leading-relaxed">{field.description}</p>
    </div>
  );
}

function SelectField({ field, value, onChange }: { field: FieldDef; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">{field.label}</label>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded px-3 py-2 text-sm outline-none appearance-none pr-8"
          style={fieldBg}
        >
          {field.options?.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none text-xs">▾</span>
      </div>
      <p className="text-xs text-slate-600 mt-2 leading-relaxed">{field.description}</p>
    </div>
  );
}

function ParamField({ field, params, setParams }: {
  field: FieldDef;
  params: Record<string, unknown>;
  setParams: (p: Record<string, unknown>) => void;
}) {
  const raw = params[field.key] ?? field.default;
  const set = (v: unknown) => setParams({ ...params, [field.key]: v });

  if (field.type === "slider") return <SliderField field={field} value={Number(raw ?? 0)} onChange={set} />;
  if (field.type === "number") return <NumberField field={field} value={Number(raw ?? 0)} onChange={set} />;
  if (field.type === "boolean") return <BooleanField field={field} value={Boolean(raw)} onChange={set} />;
  if (field.type === "tags") return <TagsField field={field} value={Array.isArray(raw) ? (raw as string[]) : []} onChange={set} />;
  if (field.type === "select") return <SelectField field={field} value={String(raw ?? "")} onChange={set} />;
  return null;
}

// ── Custom blocked phrases ────────────────────────────────────────────────────

function CustomBlockedPhrases({
  params,
  setParams,
}: {
  params: Record<string, unknown>;
  setParams: (p: Record<string, unknown>) => void;
}) {
  const phrases: string[] = Array.isArray(params.custom_blocked_phrases)
    ? (params.custom_blocked_phrases as string[])
    : [];
  const [input, setInput] = useState("");

  function add() {
    const trimmed = input.trim();
    if (trimmed && !phrases.includes(trimmed)) {
      setParams({ ...params, custom_blocked_phrases: [...phrases, trimmed] });
    }
    setInput("");
  }

  function remove(phrase: string) {
    setParams({ ...params, custom_blocked_phrases: phrases.filter((p) => p !== phrase) });
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") { e.preventDefault(); add(); }
    if (e.key === "Backspace" && input === "" && phrases.length > 0) {
      setParams({ ...params, custom_blocked_phrases: phrases.slice(0, -1) });
    }
  }

  return (
    <div className="rounded border p-6 space-y-4" style={{ background: "var(--card)", borderColor: "rgba(81,85,148,0.12)" }}>
      <div>
        <p className="text-xs text-slate-400 uppercase tracking-widest font-mono mb-1">
          Custom blocked keywords &amp; phrases
        </p>
        <p className="text-xs text-slate-600 leading-relaxed">
          Any prompt or response containing these words or phrases will always be blocked — regardless of what the scanner's model decides.
          Matching is case-insensitive. Add each entry separately.
        </p>
      </div>

      {/* Tag input */}
      <div
        className="w-full rounded px-3 py-2.5 min-h-[48px] flex flex-wrap gap-1.5 cursor-text"
        style={fieldBg}
        onClick={() => document.getElementById("custom-phrases-input")?.focus()}
      >
        {phrases.map((phrase) => (
          <span
            key={phrase}
            className="flex items-center gap-1.5 text-xs font-mono px-2 py-1 rounded"
            style={{ background: "rgba(248,113,113,0.1)", color: "#f87171", border: "1px solid rgba(248,113,113,0.2)" }}
          >
            {phrase}
            <button
              type="button"
              onClick={() => remove(phrase)}
              className="opacity-60 hover:opacity-100 transition-opacity leading-none"
            >
              ×
            </button>
          </span>
        ))}
        <input
          id="custom-phrases-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => { if (input.trim()) add(); }}
          placeholder={phrases.length === 0 ? "Type a word or phrase and press Enter…" : "Add another…"}
          className="flex-1 min-w-[180px] bg-transparent text-sm outline-none text-slate-300 placeholder-slate-700"
        />
      </div>

      {phrases.length > 0 && (
        <p className="text-xs text-slate-700 font-mono">
          {phrases.length} phrase{phrases.length !== 1 ? "s" : ""} · exact substring match
        </p>
      )}
    </div>
  );
}

// ── Scanner intelligence card ─────────────────────────────────────────────────

const DATASET_COLORS: Record<string, { color: string; bg: string }> = {
  "SecLists + Arcanum":    { color: "#f87171", bg: "rgba(248,113,113,0.08)" },
  "SecLists (LLM_Testing)":{ color: "#f87171", bg: "rgba(248,113,113,0.08)" },
  "Garak (NVIDIA)":        { color: "#34d399", bg: "rgba(52,211,153,0.08)"  },
  "Promptfoo":             { color: "#60a5fa", bg: "rgba(96,165,250,0.08)"  },
  "Deck of Many Prompts":  { color: "#fbbf24", bg: "rgba(251,191,36,0.08)"  },
};

function ScannerIntelCard({ scannerType }: { scannerType: string }) {
  const intel = SCANNER_INTEL[scannerType];
  if (!intel) return null;

  const typeMeta = MODEL_TYPE_META[intel.modelType];

  return (
    <div className="rounded border space-y-0 overflow-hidden" style={{ background: "var(--card)", borderColor: "var(--border)" }}>
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b" style={{ borderColor: "var(--border)" }}>
        <span className="text-xs font-medium px-2 py-1 rounded"
          style={{ background: typeMeta.bg, color: typeMeta.color }}>
          {typeMeta.label}
        </span>
        <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">How it works</p>
      </div>

      <div className="px-6 py-5 space-y-5">
        {/* How it works */}
        <p className="text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
          {intel.howItWorks}
        </p>

        {/* Model */}
        {intel.model && (
          <div className="rounded px-4 py-3 space-y-1" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
            <p className="text-xs text-slate-600 uppercase tracking-wider">
              {intel.modelType === "rule" ? "Library" : "Model"}
            </p>
            <p className="text-sm font-mono" style={{ color: "#515594" }}>{intel.model}</p>
          </div>
        )}

        {/* Trained on — summary */}
        {intel.trainedOn && !intel.trainingDatasets && (
          <div className="space-y-1.5">
            <p className="text-xs text-slate-600 uppercase tracking-wider font-mono">
              {intel.modelType === "rule" ? "Rule sources" : "Trained on"}
            </p>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-dim)" }}>
              {intel.trainedOn}
            </p>
          </div>
        )}

        {/* Training dataset breakdown */}
        {intel.trainingDatasets && intel.trainingDatasets.length > 0 && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-600 uppercase tracking-wider font-mono">Training datasets</p>
              <p className="text-xs font-mono" style={{ color: "var(--text-dim)" }}>
                {intel.trainingDatasets.reduce((s, d) => s + d.count, 0)} {intel.trainingDatasets[0].unit} total
              </p>
            </div>

            <div className="space-y-2">
              {intel.trainingDatasets.map((ds) => {
                const dsColor = DATASET_COLORS[ds.name] ?? { color: "#94a3b8", bg: "rgba(148,163,184,0.08)" };
                return (
                  <div key={ds.name} className="rounded border overflow-hidden"
                    style={{ borderColor: "var(--border)", background: "var(--bg)" }}>
                    <div className="flex items-center justify-between px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: dsColor.color }} />
                        <span className="text-xs font-medium" style={{ color: dsColor.color }}>{ds.name}</span>
                      </div>
                      <span className="text-xs font-mono px-2 py-0.5 rounded"
                        style={{ background: dsColor.bg, color: dsColor.color }}>
                        {ds.count} {ds.unit}
                      </span>
                    </div>
                    <div className="px-4 pb-3 border-t" style={{ borderColor: "var(--border)" }}>
                      <p className="text-xs leading-relaxed pt-2.5" style={{ color: "var(--text-dim)" }}>
                        {ds.contribution}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>

            {intel.trainedOn && (
              <p className="text-xs leading-relaxed" style={{ color: "var(--text-dimmest)" }}>
                {intel.trainedOn}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const DIRECTION_LABEL: Record<string, string> = { input: "Input scanner", output: "Output scanner" };

export default function EditGuardrailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { data: guardrails, mutate } = useSWR<Guardrail[]>("/guardrails", () => api.get<Guardrail[]>("/guardrails"));
  const guardrail = guardrails?.find((g) => g.id === parseInt(id));

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [onFailAction, setOnFailAction] = useState("block");
  const [editParams, setEditParams] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (guardrail) {
      setName(guardrail.name);
      setIsActive(guardrail.is_active);
      setOnFailAction(guardrail.on_fail_action ?? "block");
      const p = guardrail.params ?? {};
      setDescription(typeof p._description === "string" ? p._description : "");
      setEditParams(p);
    }
  }, [guardrail]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setSaving(true);
    try {
      const params = { ...editParams, _description: description.trim() || undefined };
      await api.put(`/guardrails/${id}`, { name, is_active: isActive, on_fail_action: onFailAction, params, order: guardrail!.order });
      await mutate();
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/guardrails/${id}`);
      router.push("/dashboard/guardrails");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  if (!guardrails) return <div className="h-64 rounded animate-pulse" style={{ background: "var(--card)" }} />;
  if (!guardrail) return (
    <div className="text-center py-20">
      <p className="text-slate-500 text-sm mb-4">Guardrail not found.</p>
      <button onClick={() => router.push("/dashboard/guardrails")} style={{ color: "#515594" }} className="text-sm">← Back</button>
    </div>
  );

  const fields = SCANNER_PARAMS[guardrail.scanner_type] ?? [];

  return (
    <div className="max-w-xl">
      <button onClick={() => router.push("/dashboard/guardrails")}
        className="text-xs text-slate-500 hover:text-white transition-colors mb-8 block">
        ← Guardrails
      </button>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Header card */}
        <div className="rounded border border-white/5 p-6" style={{ background: "var(--card)" }}>
          <div className="flex items-center gap-2 mb-5">
            <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ background: "rgba(81,85,148,0.1)", color: "#515594" }}>
              {guardrail.scanner_type}
            </span>
            <span className="text-xs text-slate-600">{DIRECTION_LABEL[guardrail.direction] ?? guardrail.direction}</span>
          </div>

          <div className="space-y-5">
            {/* Name */}
            <div>
              <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Display name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="w-full rounded px-3 py-2 text-sm outline-none"
                style={fieldBg}
              />
            </div>

            {/* Description */}
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
                style={{ ...fieldBg, fontFamily: "inherit" }}
              />
            </div>

            {/* Active toggle */}
            <div className="flex items-start gap-4">
              <button
                type="button"
                onClick={() => setIsActive(!isActive)}
                className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 mt-0.5"
                style={{ background: isActive ? "#515594" : "#1a2236" }}
              >
                <span className="inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform"
                  style={{ transform: isActive ? "translateX(18px)" : "translateX(2px)" }} />
              </button>
              <div>
                <p className="text-sm text-white leading-tight">
                  {isActive ? "Scanner is active" : "Scanner is inactive"}
                </p>
                <p className="text-xs text-slate-600 mt-1 leading-relaxed">
                  {isActive
                    ? "All prompts are being scanned by this guardrail."
                    : "This guardrail is disabled and will not scan any prompts."}
                </p>
              </div>
            </div>

            {/* On-fail action */}
            <div>
              <label className="block text-xs text-slate-500 mb-2 uppercase tracking-wider">On violation</label>
              <div className="grid grid-cols-2 gap-2">
                {([
                  { value: "block",   label: "Block",   desc: "Reject the request immediately.",                          color: "#f87171", bg: "rgba(248,113,113,0.08)" },
                  { value: "fix",     label: "Fix",     desc: "Use the scanner's sanitized output instead of blocking.",  color: "#34d399", bg: "rgba(52,211,153,0.08)"  },
                  { value: "monitor", label: "Monitor", desc: "Log the violation but let the request through.",           color: "#fbbf24", bg: "rgba(251,191,36,0.08)"  },
                  { value: "reask",   label: "Reask",   desc: "Reject and return correction hints for LLM retries.",      color: "#60a5fa", bg: "rgba(96,165,250,0.08)"  },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setOnFailAction(opt.value)}
                    className="text-left rounded border px-3 py-2.5 transition-all"
                    style={{
                      background: onFailAction === opt.value ? opt.bg : "var(--bg)",
                      borderColor: onFailAction === opt.value ? opt.color : "rgba(255,255,255,0.06)",
                    }}
                  >
                    <p className="text-xs font-mono font-semibold mb-0.5" style={{ color: opt.color }}>{opt.label}</p>
                    <p className="text-xs text-slate-600 leading-snug">{opt.desc}</p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Scanner intelligence card */}
        <ScannerIntelCard scannerType={guardrail.scanner_type} />

        {/* Params card */}
        {fields.length > 0 && (
          <div className="rounded border border-white/5 p-6 space-y-6" style={{ background: "var(--card)" }}>
            <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">Settings</p>
            {fields.map((field) => (
              <ParamField key={field.key} field={field} params={editParams} setParams={setEditParams} />
            ))}
          </div>
        )}

        {fields.length === 0 && (
          <div className="rounded border border-white/5 px-6 py-5" style={{ background: "var(--card)" }}>
            <p className="text-xs text-slate-600">This scanner has no configurable settings.</p>
          </div>
        )}

        {/* Custom blocked phrases — universal, works on top of any scanner */}
        <CustomBlockedPhrases params={editParams} setParams={setEditParams} />

        {/* Errors + actions */}
        {error && <p className="text-xs text-red-400 px-1">{error}</p>}

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className="text-sm font-medium px-5 py-2 rounded disabled:opacity-50 transition-opacity"
              style={{ background: "#515594", color: "#0A0F1F" }}
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
            {saved && (
              <span className="text-xs font-mono" style={{ color: "#515594" }}>✓ Saved</span>
            )}
          </div>
          <button
            type="button"
            onClick={handleDelete}
            className="text-xs text-red-400/50 hover:text-red-400 transition-colors"
          >
            Delete guardrail
          </button>
        </div>
      </form>
    </div>
  );
}
