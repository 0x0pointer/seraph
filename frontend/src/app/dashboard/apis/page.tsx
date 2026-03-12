"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

// ─── Types ───────────────────────────────────────────────────────────────────

interface ApiConnection {
  id: number;
  name: string;
  environment: string;
  api_key: string;
  status: string;
  org_id: number | null;
  created_by_username: string | null;
  alert_enabled: boolean;
  alert_threshold: number | null;
  total_requests: number;
  total_violations: number;
  violation_rate: number;
  estimated_cost: number;
  cost_per_input_token: number;
  cost_per_output_token: number;
  monthly_alert_spend: number | null;
  max_monthly_spend: number | null;
  month_spend: number;
  month_input_tokens: number;
  month_output_tokens: number;
  month_started_at: string | null;
  spend_percentage: number | null;
  alert_spend_active: boolean;
  spend_limit_reached: boolean;
  max_spend_reached: boolean;
  use_custom_guardrails: boolean;
  created_at: string;
  last_active_at: string | null;
}

interface ConnectionGuardrailItem {
  id: number;
  name: string;
  scanner_type: string;
  direction: string;
  is_active: boolean;
  enabled_for_conn: boolean;
  threshold_override: number | null;
}

// Scanners that accept a numeric threshold parameter
const THRESHOLD_SCANNERS = new Set([
  "PromptInjection", "Toxicity", "BanTopics", "BanCompetitors",
  "Gibberish", "Sentiment", "Bias", "Relevance", "FactualConsistency",
]);

const THRESHOLD_OPTIONS: { label: string; value: number | null }[] = [
  { label: "Default", value: null },
  { label: "0.60", value: 0.60 },
  { label: "0.70", value: 0.70 },
  { label: "0.80", value: 0.80 },
  { label: "0.90", value: 0.90 },
  { label: "0.95", value: 0.95 },
  { label: "0.99", value: 0.99 },
];

// ─── Presets ($/1M tokens) ───────────────────────────────────────────────────

const MODEL_PRESETS: { label: string; group: string; input: number; output: number }[] = [
  // OpenAI
  { label: "GPT-4o", group: "OpenAI", input: 2.5, output: 10 },
  { label: "GPT-4o mini", group: "OpenAI", input: 0.15, output: 0.6 },
  { label: "GPT-4.1", group: "OpenAI", input: 2, output: 8 },
  { label: "o3", group: "OpenAI", input: 2, output: 8 },
  { label: "o3-mini", group: "OpenAI", input: 1.1, output: 4.4 },
  { label: "o4-mini", group: "OpenAI", input: 1.1, output: 4.4 },
  // Anthropic
  { label: "Claude Sonnet 4.6", group: "Anthropic", input: 3, output: 15 },
  { label: "Claude Haiku 4.5", group: "Anthropic", input: 1, output: 5 },
  { label: "Claude Opus 4.6", group: "Anthropic", input: 5, output: 25 },
  // Google
  { label: "Gemini 2.5 Pro", group: "Google", input: 1.25, output: 10 },
  { label: "Gemini 2.5 Flash", group: "Google", input: 0.3, output: 2.5 },
  { label: "Gemini 2.0 Flash", group: "Google", input: 0.1, output: 0.4 },
  { label: "Gemini 2.0 Flash-Lite", group: "Google", input: 0.08, output: 0.3 },
  // Other
  { label: "Custom", group: "", input: 0, output: 0 },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

const ENV_COLORS: Record<string, { background: string; color: string }> = {
  production: { background: "rgba(81,85,148,0.1)", color: "#515594" },
  development: { background: "rgba(251,191,36,0.1)", color: "#fbbf24" },
  staging: { background: "rgba(148,163,184,0.1)", color: "var(--text-muted)" },
};

const inputStyle = {
  background: "var(--bg)",
  border: "1px solid var(--border-input)",
  color: "var(--text)",
};

function fmtUSD(n: number) {
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.001) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(6)}`;
}

function fmtTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function maskKey(key: string) {
  if (key.length <= 20) return key;
  return key.slice(0, 14) + "••••••••••••" + key.slice(-4);
}

function formatDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ─── Form ─────────────────────────────────────────────────────────────────────

interface FormState {
  name: string;
  environment: string;
  alert_enabled: boolean;
  alert_threshold: string;
  preset: string;
  cost_per_input_1m: string;
  cost_per_output_1m: string;
  monthly_alert_spend: string;
  max_monthly_spend: string;
}

const BLANK_FORM: FormState = {
  name: "",
  environment: "production",
  alert_enabled: false,
  alert_threshold: "",
  preset: "Custom",
  cost_per_input_1m: "",
  cost_per_output_1m: "",
  monthly_alert_spend: "",
  max_monthly_spend: "",
};

function ConnectionForm({
  initial,
  onSave,
  onCancel,
  loading,
  error,
}: {
  initial: FormState;
  onSave: (f: FormState) => void;
  onCancel: () => void;
  loading: boolean;
  error: string;
}) {
  const [form, setForm] = useState<FormState>(initial);

  function set<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function applyPreset(label: string) {
    const preset = MODEL_PRESETS.find((p) => p.label === label);
    set("preset", label);
    if (preset && preset.input > 0) {
      setForm((f) => ({
        ...f,
        preset: label,
        cost_per_input_1m: String(preset.input),
        cost_per_output_1m: String(preset.output),
      }));
    } else {
      setForm((f) => ({ ...f, preset: label }));
    }
  }

  const hasPricing = form.cost_per_input_1m !== "" || form.cost_per_output_1m !== "";
  const maxBelowAlert =
    form.max_monthly_spend &&
    form.monthly_alert_spend &&
    parseFloat(form.max_monthly_spend) < parseFloat(form.monthly_alert_spend);

  const labelCls = "block text-xs text-slate-500 uppercase tracking-wider mb-1.5";

  return (
    <div className="space-y-5">
      {/* Name + Environment */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Connection name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="My production app"
            className="w-full rounded px-3 py-2 text-sm outline-none"
            style={inputStyle}
          />
        </div>
        <div>
          <label className={labelCls}>Environment</label>
          <select
            value={form.environment}
            onChange={(e) => set("environment", e.target.value)}
            className="w-full rounded px-3 py-2 text-sm outline-none"
            style={inputStyle}
          >
            <option value="production">Production</option>
            <option value="development">Development</option>
            <option value="staging">Staging</option>
          </select>
        </div>
      </div>

      {/* Auto-block alert (violation rate) */}
      <div className="rounded border border-white/5 p-4 space-y-3" style={{ background: "var(--bg)" }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-white font-medium">Auto-block on violations</p>
            <p className="text-xs text-slate-500 mt-0.5">
              Block this connection when violation rate reaches the threshold
            </p>
          </div>
          <button
            type="button"
            onClick={() => set("alert_enabled", !form.alert_enabled)}
            className="relative w-10 h-5 rounded-full transition-colors shrink-0"
            style={{ background: form.alert_enabled ? "#515594" : "rgba(255,255,255,0.1)" }}
          >
            <span
              className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
              style={{
                background: "white",
                left: form.alert_enabled ? "calc(100% - 1.125rem)" : "0.125rem",
              }}
            />
          </button>
        </div>
        {form.alert_enabled && (
          <div>
            <label className={labelCls}>Threshold (0–100%)</label>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={form.alert_threshold === "" ? 50 : Number(form.alert_threshold)}
                onChange={(e) => set("alert_threshold", e.target.value)}
                className="flex-1 accent-[#515594]"
              />
              <span className="text-sm font-mono text-white w-12 text-right">
                {form.alert_threshold === "" ? "50" : form.alert_threshold}%
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Spend tracking */}
      <div className="rounded border border-white/5 p-4 space-y-4" style={{ background: "var(--bg)" }}>
        <div>
          <p className="text-sm text-white font-medium">Spend tracking</p>
          <p className="text-xs text-slate-500 mt-0.5">
            Set per-token pricing and monthly spend limits. Pass{" "}
            <code className="font-mono text-slate-400">input_tokens</code> /{" "}
            <code className="font-mono text-slate-400">output_tokens</code> in scan requests, or
            SKF Guard estimates from text length.
          </p>
        </div>

        {/* Model preset */}
        <div>
          <label className={labelCls}>Model preset (auto-fills pricing)</label>
          <select
            value={form.preset}
            onChange={(e) => applyPreset(e.target.value)}
            className="w-full rounded px-3 py-2 text-sm outline-none"
            style={inputStyle}
          >
            {(["OpenAI", "Anthropic", "Google", ""] as const).map((group) => {
              const items = MODEL_PRESETS.filter((p) => p.group === group);
              if (items.length === 0) return null;
              const groupLabel = group || "Other";
              return (
                <optgroup key={groupLabel} label={groupLabel}>
                  {items.map((p) => (
                    <option key={p.label} value={p.label}>
                      {p.label}
                      {p.input > 0 ? ` — $${p.input}/$${p.output} per 1M` : ""}
                    </option>
                  ))}
                </optgroup>
              );
            })}
          </select>
        </div>

        {/* Pricing fields */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>$/1M input tokens</label>
            <input
              type="number"
              step="any"
              min="0"
              value={form.cost_per_input_1m}
              onChange={(e) => set("cost_per_input_1m", e.target.value)}
              placeholder="e.g. 2.5"
              className="w-full rounded px-3 py-2 text-sm outline-none font-mono"
              style={inputStyle}
            />
          </div>
          <div>
            <label className={labelCls}>$/1M output tokens</label>
            <input
              type="number"
              step="any"
              min="0"
              value={form.cost_per_output_1m}
              onChange={(e) => set("cost_per_output_1m", e.target.value)}
              placeholder="e.g. 10"
              className="w-full rounded px-3 py-2 text-sm outline-none font-mono"
              style={inputStyle}
            />
          </div>
        </div>

        {/* Spend limits — always shown */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>
              Monthly alert limit ($)
              <span className="ml-1 normal-case text-slate-700">— amber warning</span>
            </label>
            <input
              type="number"
              step="any"
              min="0"
              value={form.monthly_alert_spend}
              onChange={(e) => set("monthly_alert_spend", e.target.value)}
              placeholder="e.g. 40"
              className="w-full rounded px-3 py-2 text-sm outline-none font-mono"
              style={inputStyle}
            />
          </div>
          <div>
            <label className={labelCls}>
              Max spend limit ($)
              <span className="ml-1 normal-case" style={{ color: "#f87171" }}>
                — blocks scans
              </span>
            </label>
            <input
              type="number"
              step="any"
              min="0"
              value={form.max_monthly_spend}
              onChange={(e) => set("max_monthly_spend", e.target.value)}
              placeholder="e.g. 50"
              className="w-full rounded px-3 py-2 text-sm outline-none font-mono"
              style={{
                ...inputStyle,
                borderColor: form.max_monthly_spend
                  ? "rgba(248,113,113,0.3)"
                  : "rgba(255,255,255,0.08)",
              }}
            />
          </div>
        </div>

        {maxBelowAlert && (
          <p className="text-xs font-mono" style={{ color: "#fbbf24" }}>
            ⚠ Max limit is below alert limit — hard block triggers before the alert.
          </p>
        )}
      </div>

      {error && (
        <p
          className="text-xs px-3 py-2.5 rounded border font-mono"
          style={{ color: "#f87171", background: "rgba(248,113,113,0.05)", borderColor: "rgba(248,113,113,0.15)" }}
        >
          {error}
        </p>
      )}

      <div className="flex gap-3">
        <button
          onClick={() => onSave(form)}
          disabled={loading || !form.name.trim()}
          className="text-xs font-medium px-4 py-2 rounded transition-opacity disabled:opacity-40"
          style={{ background: "#515594", color: "#0A0F1F" }}
        >
          {loading ? "Saving…" : "Save connection"}
        </button>
        <button
          onClick={onCancel}
          className="text-xs font-medium px-4 py-2 rounded border border-white/10 text-slate-400 hover:text-white transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ─── Delete confirm modal ─────────────────────────────────────────────────────

function DeleteModal({
  connName,
  onConfirm,
  onCancel,
}: {
  connName: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.7)" }}
      onClick={onCancel}
    >
      <div
        className="relative w-full max-w-md mx-4 rounded-lg border p-6 space-y-4"
        style={{ background: "var(--card)", borderColor: "rgba(248,113,113,0.3)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Icon */}
        <div className="flex items-center justify-center w-12 h-12 rounded-full mx-auto"
          style={{ background: "rgba(248,113,113,0.1)" }}>
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="#f87171" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>

        {/* Title + body */}
        <div className="text-center space-y-2">
          <p className="text-base font-semibold text-white">Delete connection?</p>
          <p className="text-sm text-slate-400 leading-relaxed">
            You are about to permanently delete{" "}
            <span className="font-semibold text-white">{connName}</span>. This will invalidate the
            API key and erase all associated spend counters. This action{" "}
            <span style={{ color: "#f87171" }}>cannot be undone</span>.
          </p>
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-1">
          <button
            onClick={onCancel}
            className="flex-1 text-sm py-2 rounded border border-white/10 text-slate-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 text-sm py-2 rounded font-medium transition-opacity hover:opacity-90"
            style={{ background: "#f87171", color: "#0A0F1F" }}
          >
            Yes, delete permanently
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Spend bar ────────────────────────────────────────────────────────────────

function SpendBar({ pct, maxReached }: { pct: number; maxReached: boolean }) {
  const clamped = Math.min(pct, 100);
  const color = maxReached || pct >= 100 ? "#f87171" : pct >= 80 ? "#fbbf24" : "#515594";
  return (
    <div className="space-y-1">
      <div className="h-1.5 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
        <div
          className="h-1.5 rounded-full transition-all"
          style={{ width: `${clamped}%`, background: color }}
        />
      </div>
      <p className="text-xs font-mono" style={{ color }}>
        {pct.toFixed(1)}% of alert limit
      </p>
    </div>
  );
}

// ─── Guardrails panel ─────────────────────────────────────────────────────────

function GuardrailsPanel({
  conn,
  onClose,
  onSaved,
}: {
  conn: ApiConnection;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { data: items, mutate } = useSWR<ConnectionGuardrailItem[]>(
    `/connections/${conn.id}/guardrails`,
    () => api.get<ConnectionGuardrailItem[]>(`/connections/${conn.id}/guardrails`),
  );

  const [useCustom, setUseCustom] = useState(conn.use_custom_guardrails);
  const [enabled, setEnabled] = useState<Set<number>>(new Set());
  const [thresholds, setThresholds] = useState<Map<number, number | null>>(new Map());
  const [tab, setTab] = useState<"input" | "output">("input");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (items) {
      setEnabled(new Set(items.filter((g) => g.enabled_for_conn).map((g) => g.id)));
      const tMap = new Map<number, number | null>();
      for (const g of items) {
        if (g.threshold_override !== null) tMap.set(g.id, g.threshold_override);
      }
      setThresholds(tMap);
    }
  }, [items]);

  function toggleGuardrail(id: number) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function setThreshold(id: number, value: number | null) {
    setThresholds((prev) => {
      const next = new Map(prev);
      if (value === null) next.delete(id);
      else next.set(id, value);
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      await api.put(`/connections/${conn.id}/guardrails`, {
        use_custom_guardrails: useCustom,
        guardrails: Array.from(enabled).map((id) => ({
          id,
          threshold_override: thresholds.get(id) ?? null,
        })),
      });
      await mutate();
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<{
    is_valid: boolean;
    scanner_results: Record<string, number>;
    violation_scanners: string[];
    use_custom_guardrails: boolean;
    active_guardrail_count: number | null;
  } | null>(null);
  const [testing, setTesting] = useState(false);

  async function handleTest() {
    if (!testText.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.post<typeof testResult>(`/connections/${conn.id}/test-scan`, {
        text: testText,
        direction: tab,
      });
      setTestResult(res);
    } catch {
      // silently ignore
    } finally {
      setTesting(false);
    }
  }

  const filtered = items?.filter((g) => g.direction === tab) ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.7)" }}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-xl mx-4 rounded-lg border p-6 space-y-5"
        style={{ background: "var(--card)", borderColor: "rgba(81,85,148,0.25)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-white">Guardrails — {conn.name}</p>
            <p className="text-xs text-slate-500 mt-0.5">
              Choose which guardrails run for scans made with this connection key.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-600 hover:text-slate-400 transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Master toggle */}
        <div
          className="flex items-center justify-between rounded border px-4 py-3"
          style={{ background: "var(--bg)", borderColor: "rgba(255,255,255,0.06)" }}
        >
          <div>
            <p className="text-sm text-white font-medium">Use guardrails</p>
            <p className="text-xs text-slate-500 mt-0.5">
              When off, all globally-active guardrails apply.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setUseCustom((v) => !v)}
            className="relative w-10 h-5 rounded-full transition-colors shrink-0"
            style={{ background: useCustom ? "#515594" : "rgba(255,255,255,0.1)" }}
          >
            <span
              className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
              style={{
                background: "white",
                left: useCustom ? "calc(100% - 1.125rem)" : "0.125rem",
              }}
            />
          </button>
        </div>

        {/* Per-guardrail list */}
        {useCustom && (
          <div className="space-y-3">
            {/* Tabs */}
            <div className="flex gap-1 border-b border-white/5">
              {(["input", "output"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className="px-3 py-1.5 text-xs capitalize font-medium transition-colors"
                  style={{
                    color: tab === t ? "#515594" : "#64748b",
                    borderBottom: tab === t ? "2px solid #515594" : "2px solid transparent",
                  }}
                >
                  {t}
                </button>
              ))}
            </div>

            {/* Guardrail rows */}
            <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
              {!items ? (
                <p className="text-xs text-slate-600 py-4 text-center">Loading…</p>
              ) : filtered.length === 0 ? (
                <p className="text-xs text-slate-600 py-4 text-center">No {tab} guardrails configured.</p>
              ) : (
                filtered.map((g) => {
                  const isEnabled = enabled.has(g.id);
                  const showThreshold = isEnabled && THRESHOLD_SCANNERS.has(g.scanner_type);
                  const currentThreshold = thresholds.get(g.id) ?? null;
                  return (
                    <div
                      key={g.id}
                      className="flex items-center justify-between rounded px-3 py-2 gap-3"
                      style={{ background: "var(--bg)", border: "1px solid rgba(255,255,255,0.04)" }}
                    >
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <span className="text-xs text-slate-300 truncate">{g.name}</span>
                        {!g.is_active && (
                          <span
                            className="text-xs font-mono px-1.5 py-0.5 rounded-full shrink-0"
                            style={{
                              background: "rgba(248,113,113,0.1)",
                              color: "#f87171",
                              border: "1px solid rgba(248,113,113,0.2)",
                            }}
                          >
                            globally off
                          </span>
                        )}
                      </div>
                      {showThreshold && (
                        <select
                          value={currentThreshold ?? ""}
                          onChange={(e) => setThreshold(g.id, e.target.value === "" ? null : parseFloat(e.target.value))}
                          className="text-xs rounded px-2 py-1 shrink-0 font-mono"
                          style={{
                            background: "var(--card)",
                            border: "1px solid rgba(255,255,255,0.1)",
                            color: currentThreshold !== null ? "#515594" : "#64748b",
                            outline: "none",
                          }}
                        >
                          {THRESHOLD_OPTIONS.map((opt) => (
                            <option key={String(opt.value)} value={opt.value ?? ""}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      )}
                      <button
                        type="button"
                        onClick={() => toggleGuardrail(g.id)}
                        className="relative w-8 h-4 rounded-full transition-colors shrink-0"
                        style={{ background: isEnabled ? "#515594" : "rgba(255,255,255,0.1)" }}
                      >
                        <span
                          className="absolute top-0.5 w-3 h-3 rounded-full transition-all"
                          style={{
                            background: "white",
                            left: isEnabled ? "calc(100% - 0.875rem)" : "0.125rem",
                          }}
                        />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {error && (
          <p
            className="text-xs px-3 py-2 rounded border font-mono"
            style={{ color: "#f87171", background: "rgba(248,113,113,0.05)", borderColor: "rgba(248,113,113,0.15)" }}
          >
            {error}
          </p>
        )}

        {/* Test scan */}
        <div className="space-y-2 border-t pt-4" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
          <p className="text-xs text-slate-500 uppercase tracking-wider font-mono">Test scan</p>
          <div className="flex gap-2">
            <input
              type="text"
              value={testText}
              onChange={(e) => { setTestText(e.target.value); setTestResult(null); }}
              onKeyDown={(e) => e.key === "Enter" && handleTest()}
              placeholder={`Enter a ${tab} prompt to test…`}
              className="flex-1 text-xs rounded px-3 py-2 font-mono"
              style={{ background: "var(--bg)", border: "1px solid var(--border-input)", color: "var(--text)", outline: "none" }}
            />
            <button
              onClick={handleTest}
              disabled={testing || !testText.trim()}
              className="text-xs font-medium px-3 py-2 rounded border transition-colors disabled:opacity-40 shrink-0"
              style={{ borderColor: "rgba(81,85,148,0.3)", color: "#515594" }}
            >
              {testing ? "…" : "Run"}
            </button>
          </div>

          {testResult && (
            <div
              className="rounded border px-3 py-2.5 space-y-2"
              style={{
                background: testResult.is_valid ? "rgba(81,85,148,0.04)" : "rgba(248,113,113,0.04)",
                borderColor: testResult.is_valid ? "rgba(81,85,148,0.2)" : "rgba(248,113,113,0.25)",
              }}
            >
              <div className="flex items-center justify-between">
                <span
                  className="text-xs font-mono font-bold"
                  style={{ color: testResult.is_valid ? "#515594" : "#f87171" }}
                >
                  {testResult.is_valid ? "✓ PASS" : "✗ BLOCKED"}
                </span>
                <span className="text-xs font-mono text-slate-600">
                  {testResult.active_guardrail_count !== null
                    ? `${testResult.active_guardrail_count} guardrails active`
                    : "global guardrails"}
                </span>
              </div>
              {Object.entries(testResult.scanner_results).length > 0 && (
                <div className="space-y-1">
                  {Object.entries(testResult.scanner_results)
                    .sort(([, a], [, b]) => b - a)
                    .map(([name, score]) => {
                      const isViol = testResult.violation_scanners.includes(name);
                      return (
                        <div key={name} className="flex items-center justify-between text-xs font-mono">
                          <span style={{ color: isViol ? "#f87171" : "#64748b" }}>{name}</span>
                          <span style={{ color: isViol ? "#f87171" : "#475569" }}>
                            {score.toFixed(3)} {isViol ? "blocked" : "pass"}
                          </span>
                        </div>
                      );
                    })}
                </div>
              )}
              {!testResult.is_valid && testResult.violation_scanners.length === 0 && (
                <p className="text-xs text-slate-600 font-mono">No scanners ran — check your configuration.</p>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="text-xs font-medium px-4 py-2 rounded transition-opacity disabled:opacity-40"
            style={{ background: "#515594", color: "#0A0F1F" }}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            onClick={onClose}
            className="text-xs font-medium px-4 py-2 rounded border border-white/10 text-slate-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Connection card ──────────────────────────────────────────────────────────

function StatCell({
  label, value, sub, color, bar,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  bar?: { pct: number; color: string };
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-slate-600 uppercase tracking-wider font-mono">{label}</span>
      <span className="text-base font-bold tracking-tight mt-0.5" style={{ color: color ?? "#e2e8f0" }}>{value}</span>
      {bar && (
        <div className="h-0.5 rounded-full mt-1" style={{ background: "rgba(255,255,255,0.06)" }}>
          <div
            className="h-0.5 rounded-full transition-all"
            style={{ width: `${Math.min(bar.pct, 100)}%`, background: bar.color }}
          />
        </div>
      )}
      {sub && <span className="text-xs text-slate-600 mt-0.5">{sub}</span>}
    </div>
  );
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return formatDate(iso);
}

function ConnectionCard({
  conn,
  onToggle,
  onDelete,
  onEdit,
  onResetSpend,
  onGuardrails,
}: {
  conn: ApiConnection;
  onToggle: (id: number) => void;
  onDelete: (id: number) => void;
  onEdit: (conn: ApiConnection) => void;
  onResetSpend: (id: number) => void;
  onGuardrails: (conn: ApiConnection) => void;
}) {
  const [keyVisible, setKeyVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  const isActive = conn.status === "active";
  const envStyle = ENV_COLORS[conn.environment] ?? ENV_COLORS.staging;
  const hasSpendTracking = conn.cost_per_input_token > 0 || conn.cost_per_output_token > 0;

  async function copyKey() {
    await navigator.clipboard.writeText(conn.api_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div
      className="rounded border p-5 space-y-4"
      style={{
        background: "var(--card)",
        borderColor: conn.max_spend_reached
          ? "rgba(248,113,113,0.35)"
          : "rgba(255,255,255,0.05)",
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <span
            className="w-2 h-2 rounded-full shrink-0 mt-1"
            style={{
              background: isActive ? "#515594" : "#f87171",
              boxShadow: isActive ? "0 0 6px #51559440" : "0 0 6px #f8717140",
            }}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-white truncate">{conn.name}</p>
              {conn.max_spend_reached && (
                <span
                  className="text-xs font-mono px-1.5 py-0.5 rounded-full shrink-0"
                  style={{ background: "rgba(248,113,113,0.15)", color: "#f87171", border: "1px solid rgba(248,113,113,0.3)" }}
                >
                  ⛔ spend blocked
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <span className="text-xs px-1.5 py-0.5 rounded font-mono capitalize" style={envStyle}>
                {conn.environment}
              </span>
              <span
                className="text-xs px-1.5 py-0.5 rounded font-mono"
                style={
                  isActive
                    ? { background: "rgba(81,85,148,0.08)", color: "#515594" }
                    : { background: "rgba(248,113,113,0.08)", color: "#f87171" }
                }
              >
                {isActive ? "active" : "blocked"}
              </span>
              {conn.org_id && (
                <span className="text-xs px-1.5 py-0.5 rounded font-mono"
                  style={{ background: "rgba(99,102,241,0.1)", color: "#a5b4fc" }}>
                  org
                </span>
              )}
              {conn.created_by_username && (
                <span className="text-xs text-slate-600 font-mono">
                  by @{conn.created_by_username}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => onEdit(conn)}
            className="text-xs px-2.5 py-1.5 rounded border border-white/10 text-slate-400 hover:text-white transition-colors"
          >
            Edit
          </button>
          <button
            onClick={() => onGuardrails(conn)}
            className="text-xs px-2.5 py-1.5 rounded border transition-colors"
            style={
              conn.use_custom_guardrails
                ? { borderColor: "rgba(81,85,148,0.4)", color: "#515594" }
                : { borderColor: "rgba(255,255,255,0.1)", color: "var(--text-dim)" }
            }
          >
            Guardrails
          </button>
          {hasSpendTracking && (
            <button
              onClick={() => onResetSpend(conn.id)}
              className="text-xs px-2.5 py-1.5 rounded border border-white/10 text-slate-500 hover:text-slate-300 transition-colors"
            >
              Reset spend
            </button>
          )}
          <button
            onClick={() => onToggle(conn.id)}
            className="text-xs px-2.5 py-1.5 rounded border transition-colors"
            style={
              isActive
                ? { borderColor: "rgba(248,113,113,0.3)", color: "#f87171" }
                : { borderColor: "rgba(81,85,148,0.3)", color: "#515594" }
            }
          >
            {isActive ? "Block" : "Unblock"}
          </button>
        </div>
      </div>

      {/* Spend banners */}
      {conn.max_spend_reached ? (
        <div
          className="flex items-center gap-2 px-3 py-2 rounded text-xs font-mono"
          style={{ background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.25)", color: "#f87171" }}
        >
          <span>⛔</span>
          <span>
            Max spend of ${conn.max_monthly_spend?.toFixed(2)} reached — scans return HTTP 402.
            Reset the monthly counter to unblock.
          </span>
        </div>
      ) : conn.spend_limit_reached ? (
        <div
          className="flex items-center gap-2 px-3 py-2 rounded text-xs font-mono"
          style={{ background: "rgba(251,146,60,0.08)", border: "1px solid rgba(251,146,60,0.2)", color: "#fb923c" }}
        >
          <span>⚠</span>
          <span>Monthly alert limit reached — scans still proceed</span>
        </div>
      ) : conn.alert_spend_active ? (
        <div
          className="flex items-center gap-2 px-3 py-2 rounded text-xs font-mono"
          style={{ background: "rgba(251,191,36,0.08)", border: "1px solid rgba(251,191,36,0.2)", color: "#fbbf24" }}
        >
          <span>⚠</span>
          <span>Approaching monthly alert limit ({conn.spend_percentage?.toFixed(1)}% used)</span>
        </div>
      ) : null}

      {/* Spend progress bar */}
      {hasSpendTracking && conn.monthly_alert_spend !== null && conn.spend_percentage !== null && (
        <SpendBar pct={conn.spend_percentage} maxReached={conn.max_spend_reached} />
      )}

      {/* API Key row */}
      <div
        className="flex items-center gap-2 px-3 py-2 rounded font-mono text-xs"
        style={{ background: "var(--bg)", border: "1px solid var(--border)" }}
      >
        <span className="flex-1 text-slate-400 truncate">
          {keyVisible ? conn.api_key : maskKey(conn.api_key)}
        </span>
        <button
          onClick={() => setKeyVisible((v) => !v)}
          className="text-slate-600 hover:text-slate-400 transition-colors shrink-0"
        >
          {keyVisible ? (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
          )}
        </button>
        <button
          onClick={copyKey}
          className="text-slate-600 hover:text-slate-400 transition-colors shrink-0"
        >
          {copied ? (
            <svg className="w-3.5 h-3.5 text-[#515594]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          )}
        </button>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 py-3 border-t border-white/5">
        {/* Requests */}
        <StatCell
          label="Requests"
          value={conn.total_requests.toLocaleString()}
          color="#e2e8f0"
          sub={conn.total_requests === 0 ? "no traffic yet" : `${conn.total_violations} blocked`}
        />

        {/* Violation rate */}
        {(() => {
          const rate = conn.violation_rate;
          const rateColor = rate === 0 ? "#515594" : rate < 10 ? "#fbbf24" : "#f87171";
          return (
            <StatCell
              label="Violation rate"
              value={`${rate}%`}
              color={rateColor}
              bar={{ pct: rate, color: rateColor }}
              sub={`${conn.total_violations} of ${conn.total_requests} flagged`}
            />
          );
        })()}

        {/* Spend / cost */}
        {hasSpendTracking ? (
          <StatCell
            label="Month spend"
            value={fmtUSD(conn.month_spend)}
            color={conn.max_spend_reached ? "#f87171" : conn.alert_spend_active ? "#fbbf24" : "#515594"}
            sub={
              conn.month_input_tokens > 0 || conn.month_output_tokens > 0
                ? `${fmtTokens(conn.month_input_tokens)} in · ${fmtTokens(conn.month_output_tokens)} out`
                : "no token usage this month"
            }
          />
        ) : (
          <StatCell
            label="Est. cost"
            value={conn.total_requests > 0 ? `$${conn.estimated_cost.toFixed(4)}` : "—"}
            color="#94a3b8"
            sub="add pricing to track spend"
          />
        )}

        {/* Last active */}
        <StatCell
          label="Last active"
          value={timeAgo(conn.last_active_at)}
          color={conn.last_active_at ? "#e2e8f0" : "#475569"}
          sub={conn.last_active_at ? formatDate(conn.last_active_at) : "never used"}
        />
      </div>

      {/* Pricing + limit footer (when spend tracking is on) */}
      {hasSpendTracking && (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 rounded text-xs font-mono"
          style={{ background: "var(--bg)" }}
        >
          <span className="text-slate-600">Pricing:</span>
          <span className="text-slate-400">
            ${(conn.cost_per_input_token * 1_000_000).toFixed(4)}/1M in
          </span>
          <span className="text-slate-400">
            ${(conn.cost_per_output_token * 1_000_000).toFixed(4)}/1M out
          </span>
          <span className="ml-auto flex items-center gap-3">
            {conn.monthly_alert_spend !== null && (
              <span className="text-slate-600">alert at ${conn.monthly_alert_spend.toFixed(2)}</span>
            )}
            {conn.max_monthly_spend !== null && (
              <span style={{ color: conn.max_spend_reached ? "#f87171" : "#94a3b8" }}>
                hard cap ${conn.max_monthly_spend.toFixed(2)}
              </span>
            )}
          </span>
        </div>
      )}

      {/* Violation-rate alert badge */}
      {conn.alert_enabled && conn.alert_threshold !== null && (
        <div
          className="flex items-center gap-2 px-3 py-2 rounded text-xs"
          style={{ background: "rgba(251,191,36,0.05)", border: "1px solid rgba(251,191,36,0.15)" }}
        >
          <svg className="w-3.5 h-3.5 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span style={{ color: "#fbbf24" }}>
            Auto-block at {conn.alert_threshold}% violation rate
            {conn.status === "blocked" && " · currently blocked"}
          </span>
        </div>
      )}

      {/* Delete */}
      <div className="border-t border-white/5 pt-3 flex justify-end">
        <button
          onClick={() => setShowDeleteModal(true)}
          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded border transition-colors"
          style={{ borderColor: "rgba(248,113,113,0.3)", color: "#f87171", background: "rgba(248,113,113,0.06)" }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "rgba(248,113,113,0.14)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "rgba(248,113,113,0.06)";
          }}
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          Delete
        </button>
      </div>

      {/* Delete confirm modal */}
      {showDeleteModal && (
        <DeleteModal
          connName={conn.name}
          onConfirm={() => { setShowDeleteModal(false); onDelete(conn.id); }}
          onCancel={() => setShowDeleteModal(false)}
        />
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ApisPage() {
  const { data: connections, mutate } = useSWR<ApiConnection[]>(
    "/connections",
    () => api.get<ApiConnection[]>("/connections"),
  );

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<ApiConnection | null>(null);
  const [guardrailsConn, setGuardrailsConn] = useState<ApiConnection | null>(null);
  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState("");

  function buildPayload(form: FormState) {
    return {
      name: form.name.trim(),
      environment: form.environment,
      alert_enabled: form.alert_enabled,
      alert_threshold:
        form.alert_enabled && form.alert_threshold !== ""
          ? Number(form.alert_threshold)
          : null,
      cost_per_input_token:
        form.cost_per_input_1m !== "" ? parseFloat(form.cost_per_input_1m) / 1_000_000 : 0,
      cost_per_output_token:
        form.cost_per_output_1m !== "" ? parseFloat(form.cost_per_output_1m) / 1_000_000 : 0,
      monthly_alert_spend:
        form.monthly_alert_spend !== "" ? parseFloat(form.monthly_alert_spend) : null,
      max_monthly_spend:
        form.max_monthly_spend !== "" ? parseFloat(form.max_monthly_spend) : null,
    };
  }

  function connToForm(conn: ApiConnection): FormState {
    return {
      name: conn.name,
      environment: conn.environment,
      alert_enabled: conn.alert_enabled,
      alert_threshold: conn.alert_threshold !== null ? String(conn.alert_threshold) : "",
      preset: "Custom",
      cost_per_input_1m:
        conn.cost_per_input_token > 0
          ? String(conn.cost_per_input_token * 1_000_000)
          : "",
      cost_per_output_1m:
        conn.cost_per_output_token > 0
          ? String(conn.cost_per_output_token * 1_000_000)
          : "",
      monthly_alert_spend:
        conn.monthly_alert_spend !== null ? String(conn.monthly_alert_spend) : "",
      max_monthly_spend:
        conn.max_monthly_spend !== null ? String(conn.max_monthly_spend) : "",
    };
  }

  async function handleCreate(form: FormState) {
    setFormLoading(true);
    setFormError("");
    try {
      await api.post("/connections", buildPayload(form));
      await mutate();
      setShowCreate(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create connection");
    } finally {
      setFormLoading(false);
    }
  }

  async function handleEdit(form: FormState) {
    if (!editing) return;
    setFormLoading(true);
    setFormError("");
    try {
      await api.put(`/connections/${editing.id}`, buildPayload(form));
      await mutate();
      setEditing(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to update connection");
    } finally {
      setFormLoading(false);
    }
  }

  async function handleToggle(id: number) {
    try { await api.patch(`/connections/${id}/toggle`, {}); await mutate(); } catch {}
  }

  async function handleDelete(id: number) {
    try { await api.delete(`/connections/${id}`); await mutate(); } catch {}
  }

  async function handleResetSpend(id: number) {
    try { await api.post(`/connections/${id}/reset-spend`, {}); await mutate(); } catch {}
  }

  function handleOpenGuardrails(conn: ApiConnection) {
    setGuardrailsConn(conn);
    setEditing(null);
    setShowCreate(false);
  }

  const blockedBySpend = connections?.filter((c) => c.max_spend_reached).length ?? 0;

  return (
    <div className="max-w-3xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white">API Connections</h2>
          <p className="text-xs text-slate-500 mt-1">
            Scoped keys with violation-rate blocking and monthly spend limits.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {blockedBySpend > 0 && (
            <span
              className="text-xs font-mono px-2.5 py-1 rounded-full"
              style={{ background: "rgba(248,113,113,0.1)", color: "#f87171", border: "1px solid rgba(248,113,113,0.2)" }}
            >
              {blockedBySpend} spend-blocked
            </span>
          )}
          {!showCreate && !editing && (
            <button
              onClick={() => setShowCreate(true)}
              className="text-xs font-medium px-4 py-2 rounded"
              style={{ background: "#515594", color: "#0A0F1F" }}
            >
              + New connection
            </button>
          )}
        </div>
      </div>

      {/* How it works */}
      <div
        className="rounded border p-4 text-xs"
        style={{ background: "rgba(81,85,148,0.03)", borderColor: "rgba(81,85,148,0.12)" }}
      >
        <div className="flex items-start gap-3">
          <svg className="w-4 h-4 text-[#515594] shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          <div className="space-y-2 flex-1">
            <p className="text-sm font-semibold text-white">What are API connections?</p>
            <p className="text-slate-400 leading-relaxed">
              Each connection generates a scoped API key for one of your apps or environments. Use it as the Bearer token when
              calling <span className="font-mono text-slate-300">POST /api/scan/prompt</span> or{" "}
              <span className="font-mono text-slate-300">/api/scan/output</span> — SKF Guard will attribute every request to that
              connection, tracking its own violation rate, monthly token usage, and spend independently from all others.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
              <div className="rounded px-3 py-2 space-y-0.5" style={{ background: "rgba(255,255,255,0.03)" }}>
                <p className="text-slate-500 uppercase tracking-wider font-mono" style={{ fontSize: "10px" }}>Violation blocking</p>
                <p className="text-slate-300">Auto-block the key when its violation rate crosses a threshold — without affecting other connections.</p>
              </div>
              <div className="rounded px-3 py-2 space-y-0.5" style={{ background: "rgba(255,255,255,0.03)" }}>
                <p className="text-slate-500 uppercase tracking-wider font-mono" style={{ fontSize: "10px" }}>Spend alerts</p>
                <p className="text-slate-300">Set a monthly alert limit to get an amber warning as spend approaches your budget.</p>
              </div>
              <div className="rounded px-3 py-2 space-y-0.5" style={{ background: "rgba(255,255,255,0.03)" }}>
                <p className="text-slate-500 uppercase tracking-wider font-mono" style={{ fontSize: "10px" }}>Hard spend cap</p>
                <p className="text-slate-300">Set a max spend limit to return HTTP 402 and block scans the moment the budget is exhausted.</p>
              </div>
            </div>
            <p className="font-mono text-slate-600 pt-1">
              Authorization: Bearer ts_conn_&lt;your-key&gt;
            </p>
          </div>
        </div>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="rounded border border-white/5 p-6" style={{ background: "var(--card)" }}>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-mono mb-5">
            New connection
          </p>
          <ConnectionForm
            initial={BLANK_FORM}
            onSave={handleCreate}
            onCancel={() => { setShowCreate(false); setFormError(""); }}
            loading={formLoading}
            error={formError}
          />
        </div>
      )}

      {/* Edit form */}
      {editing && (
        <div className="rounded border border-[#515594]/20 p-6" style={{ background: "var(--card)" }}>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-mono mb-5">
            Edit — {editing.name}
          </p>
          <ConnectionForm
            initial={connToForm(editing)}
            onSave={handleEdit}
            onCancel={() => { setEditing(null); setFormError(""); }}
            loading={formLoading}
            error={formError}
          />
        </div>
      )}

      {/* Connection list */}
      {connections === undefined ? (
        <div className="space-y-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="rounded border border-white/5 p-5 h-48 animate-pulse" style={{ background: "var(--card)" }} />
          ))}
        </div>
      ) : connections.length > 0 ? (
        <div className="space-y-4">
          {connections.map((conn) => (
            <ConnectionCard
              key={conn.id}
              conn={conn}
              onToggle={handleToggle}
              onDelete={handleDelete}
              onEdit={(c) => { setEditing(c); setShowCreate(false); setFormError(""); }}
              onResetSpend={handleResetSpend}
              onGuardrails={handleOpenGuardrails}
            />
          ))}
        </div>
      ) : (
        !showCreate && (
          <div className="rounded border border-white/5 p-12 text-center" style={{ background: "var(--card)" }}>
            <p className="text-sm text-slate-500">No connections yet.</p>
            <p className="text-xs text-slate-600 mt-1">
              Create a connection to get a scoped API key for your app.
            </p>
            <button
              onClick={() => setShowCreate(true)}
              className="mt-4 text-xs font-medium px-4 py-2 rounded"
              style={{ background: "#515594", color: "#0A0F1F" }}
            >
              Create your first connection
            </button>
          </div>
        )
      )}

      {/* Guardrails panel overlay */}
      {guardrailsConn && (
        <GuardrailsPanel
          conn={guardrailsConn}
          onClose={() => setGuardrailsConn(null)}
          onSaved={() => { mutate(); setGuardrailsConn(null); }}
        />
      )}

    </div>
  );
}
