"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { format } from "date-fns";

interface UserInfo { role: string; }
interface OrgOption { id: number; name: string; }

interface AuditItem {
  id: number;
  direction: string;
  raw_text: string;
  sanitized_text: string | null;
  is_valid: boolean;
  scanner_results: Record<string, number>;
  violation_scanners: string[];
  ip_address: string | null;
  connection_id: number | null;
  connection_name: string | null;
  connection_environment: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  token_cost: number | null;
  org_id: number | null;
  user_id: number | null;
  max_risk_score: number;
  scanner_count: number;
  created_at: string;
}
interface AuditList { items: AuditItem[]; total: number; }

interface ConnectionOption { id: number; name: string; environment: string; }

const inputStyle = {
  background: "var(--card)",
  border: "1px solid var(--border-input)",
  color: "var(--text-muted)",
};

const ENV_COLORS: Record<string, { background: string; color: string }> = {
  production: { background: "rgba(81,85,148,0.1)", color: "#515594" },
  development: { background: "rgba(251,191,36,0.1)", color: "#fbbf24" },
  staging: { background: "rgba(148,163,184,0.1)", color: "var(--text-muted)" },
};

function riskLevel(score: number, violationCount: number) {
  if (score >= 0.9 || violationCount >= 3) return { label: "critical", color: "#f87171", bg: "rgba(248,113,113,0.08)" };
  if (score >= 0.7 || violationCount === 2) return { label: "high", color: "#fb923c", bg: "rgba(251,146,60,0.08)" };
  return { label: "medium", color: "#fbbf24", bg: "rgba(251,191,36,0.08)" };
}

function ScoreBar({ name, score }: { name: string; score: number }) {
  const pct = Math.round(score * 100);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-red-400">{name}</span>
        <span className="text-xs font-mono text-red-400/70">{score.toFixed(3)}</span>
      </div>
      <div className="h-1 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
        <div
          className="h-1 rounded-full"
          style={{ width: `${pct}%`, background: "#f87171" }}
        />
      </div>
    </div>
  );
}

function ExpandedRow({ item, orgName, isAdmin }: { item: AuditItem; orgName: string | null; isAdmin: boolean }) {
  const risk = riskLevel(item.max_risk_score, item.violation_scanners.length);
  const envStyle = item.connection_environment
    ? (ENV_COLORS[item.connection_environment] ?? ENV_COLORS.staging)
    : null;

  return (
    <div className="space-y-5 text-xs">
      {/* Meta row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          { label: "Request ID", value: `#${item.id}` },
          { label: "Direction", value: item.direction },
          { label: "Risk level", value: risk.label, color: risk.color },
          { label: "IP address", value: item.ip_address ?? "—" },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded px-3 py-2.5" style={{ background: "var(--card)" }}>
            <p className="text-xs text-slate-600 font-mono uppercase tracking-wider">{label}</p>
            <p className="text-xs font-semibold font-mono mt-0.5" style={{ color: color ?? "#e2e8f0" }}>
              {value}
            </p>
          </div>
        ))}
      </div>

      {/* Org attribution — super admins only */}
      {isAdmin && orgName && (
        <div
          className="flex items-center gap-2.5 px-3 py-2.5 rounded"
          style={{ background: "var(--card)" }}
        >
          <svg className="w-3.5 h-3.5 text-slate-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
          </svg>
          <span className="text-slate-500">Organization:</span>
          <span
            className="font-mono font-semibold px-1.5 py-0.5 rounded"
            style={{ background: "rgba(99,102,241,0.1)", color: "#818cf8" }}
          >
            {orgName}
          </span>
        </div>
      )}

      {/* Connection row */}
      <div
        className="flex items-center gap-3 px-3 py-2.5 rounded"
        style={{ background: "var(--card)" }}
      >
        <svg className="w-3.5 h-3.5 text-slate-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
        {item.connection_name ? (
          <>
            <span className="text-slate-500">Via API connection:</span>
            <span className="font-semibold text-white">{item.connection_name}</span>
            {envStyle && (
              <span className="text-xs px-1.5 py-0.5 rounded font-mono capitalize" style={envStyle}>
                {item.connection_environment}
              </span>
            )}
            <span className="text-slate-600 font-mono ml-auto">id:{item.connection_id}</span>
          </>
        ) : (
          <span className="text-slate-500">Via personal API token</span>
        )}
      </div>

      {/* Token cost (populated when connection has pricing configured) */}
      {item.token_cost !== null && (
        <div
          className="flex items-center gap-3 px-3 py-2.5 rounded"
          style={{ background: "var(--card)" }}
        >
          <svg className="w-3.5 h-3.5 text-slate-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-slate-500">Token cost:</span>
          <span className="font-mono" style={{ color: "#515594" }}>
            ${item.token_cost < 0.01 ? item.token_cost.toFixed(6) : item.token_cost.toFixed(4)}
          </span>
          {item.input_tokens !== null && (
            <span className="text-slate-600 font-mono ml-2">
              {item.input_tokens.toLocaleString()} in / {(item.output_tokens ?? 0).toLocaleString()} out tokens
            </span>
          )}
        </div>
      )}

      {/* Raw text */}
      <div>
        <p className="text-slate-600 font-mono uppercase tracking-wider mb-2">Raw text</p>
        <p
          className="text-slate-400 leading-relaxed border border-white/5 rounded px-4 py-3 font-mono whitespace-pre-wrap break-words"
          style={{ background: "var(--card)" }}
        >
          {item.raw_text}
        </p>
      </div>

      {/* Triggered scanners */}
      <div>
        <p className="text-slate-600 font-mono uppercase tracking-wider mb-2">Triggered scanners</p>
        <div className="flex flex-wrap gap-2 mb-4">
          {item.violation_scanners.map((s) => (
            <span
              key={s}
              className="px-2.5 py-1 rounded font-mono text-xs font-medium"
              style={{
                background: "rgba(248,113,113,0.1)",
                color: "#f87171",
                border: "1px solid rgba(248,113,113,0.2)",
              }}
            >
              ✗ {s}
            </span>
          ))}
        </div>

        {/* Score bars for violated scanners only */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
          {Object.entries(item.scanner_results)
            .filter(([name]) => item.violation_scanners.includes(name))
            .sort(([, a], [, b]) => b - a)
            .map(([name, score]) => (
              <ScoreBar key={name} name={name} score={typeof score === "number" ? score : 0} />
            ))}
        </div>
      </div>

      {/* All scanner scores (collapsible via title) */}
      {item.scanner_count > item.violation_scanners.length && (
        <div>
          <p className="text-slate-600 font-mono uppercase tracking-wider mb-3">
            All scanners ({item.scanner_count})
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
            {Object.entries(item.scanner_results)
              .filter(([name]) => !item.violation_scanners.includes(name))
              .sort(([, a], [, b]) => b - a)
              .map(([name, score]) => (
                <div key={name} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-slate-600">{name}</span>
                    <span className="text-xs font-mono text-slate-700">
                      {typeof score === "number" ? score.toFixed(3) : score}
                    </span>
                  </div>
                  <div className="h-1 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
                    <div
                      className="h-1 rounded-full"
                      style={{
                        width: `${Math.round((typeof score === "number" ? score : 0) * 100)}%`,
                        background: "#515594",
                      }}
                    />
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AbusePage() {
  const { data: me } = useSWR<UserInfo>(
    "/auth/me", () => api.get<UserInfo>("/auth/me"), { revalidateOnFocus: false },
  );
  const [page, setPage] = useState(1);
  const [connectionId, setConnectionId] = useState("");
  const [filterOrgId, setFilterOrgId] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const isAdmin = me?.role === "admin";

  const { data: connections } = useSWR<ConnectionOption[]>(
    "/connections",
    () => api.get<ConnectionOption[]>("/connections"),
  );
  const { data: adminOrgs } = useSWR<OrgOption[]>(
    isAdmin ? "/admin/orgs" : null,
    () => api.get<OrgOption[]>("/admin/orgs"),
  );
  const orgMap: Record<number, string> = {};
  adminOrgs?.forEach((o) => { orgMap[o.id] = o.name; });

  const queryStr = `/audit/abuse?page=${page}&page_size=20${connectionId ? `&connection_id=${connectionId}` : ""}${filterOrgId ? `&filter_org_id=${filterOrgId}` : ""}`;
  const { data, error } = useSWR<AuditList>(queryStr, () => api.get<AuditList>(queryStr));
  const totalPages = data ? Math.ceil(data.total / 20) : 1;

  return (
    <div className="space-y-4 max-w-6xl">

      {/* ── Platform-wide banner + org filter (super admins only) ── */}
      {isAdmin && (
        <div className="flex items-center gap-3">
          <div
            className="flex items-center gap-2.5 px-4 py-2.5 rounded flex-1"
            style={{ background: "rgba(248,113,113,0.06)", border: "1px solid rgba(248,113,113,0.15)" }}
          >
            <svg className="w-3.5 h-3.5 shrink-0" style={{ color: "#f87171" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <p className="text-xs font-mono" style={{ color: "#f87171" }}>
              Platform-wide view — showing blocked requests from{" "}
              <span className="font-semibold">
                {filterOrgId && adminOrgs
                  ? (adminOrgs.find((o) => String(o.id) === filterOrgId)?.name ?? "selected org")
                  : "all organizations"}
              </span>
            </p>
          </div>
          <select
            value={filterOrgId}
            onChange={(e) => { setFilterOrgId(e.target.value); setPage(1); }}
            className="text-sm rounded px-3 py-2 outline-none shrink-0"
            style={inputStyle}
          >
            <option value="">All organizations</option>
            {adminOrgs?.map((o) => (
              <option key={o.id} value={String(o.id)}>{o.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: "#f87171" }} />
          <p className="text-xs text-red-400 font-mono uppercase tracking-wider">
            {data?.total ?? "…"} blocked requests
          </p>
        </div>
        {/* Connection filter */}
        <select
          value={connectionId}
          onChange={(e) => { setConnectionId(e.target.value); setPage(1); }}
          className="text-sm rounded px-3 py-2 outline-none ml-auto"
          style={inputStyle}
        >
          <option value="">All connections</option>
          {connections?.map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.name} ({c.environment})
            </option>
          ))}
        </select>
      </div>

      {error && <p className="text-xs text-red-400">Failed to load.</p>}

      <div className="rounded border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/5">
              {["ID", "Time", "Risk", "Connection", ...(isAdmin ? ["Org"] : []), "Violated Scanners", "IP", "Preview"].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!data
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td colSpan={isAdmin ? 8 : 7} className="px-4 py-3">
                      <div className="h-3 rounded animate-pulse" style={{ background: "var(--card2)" }} />
                    </td>
                  </tr>
                ))
              : data.items.map((item) => {
                  const risk = riskLevel(item.max_risk_score, item.violation_scanners.length);
                  const envStyle = item.connection_environment
                    ? (ENV_COLORS[item.connection_environment] ?? ENV_COLORS.staging)
                    : null;

                  return (
                    <>
                      <tr
                        key={item.id}
                        className="border-b border-white/5 cursor-pointer hover:bg-white/[0.01] transition-colors"
                        style={{ background: expanded === item.id ? "rgba(248,113,113,0.02)" : undefined }}
                        onClick={() => setExpanded(expanded === item.id ? null : item.id)}
                      >
                        <td className="px-4 py-3 text-xs text-slate-600 font-mono">{item.id}</td>
                        <td className="px-4 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
                          {format(new Date(item.created_at), "MM/dd HH:mm:ss")}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className="text-xs font-mono px-2 py-0.5 rounded"
                            style={{ color: risk.color, background: risk.bg }}
                          >
                            {risk.label}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {item.connection_name ? (
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs text-slate-400 truncate max-w-[90px]">
                                {item.connection_name}
                              </span>
                              {envStyle && (
                                <span
                                  className="text-xs px-1 py-0.5 rounded font-mono capitalize shrink-0"
                                  style={envStyle}
                                >
                                  {item.connection_environment}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-slate-700 font-mono">personal</span>
                          )}
                        </td>
                        {/* Org column — super admins only */}
                        {isAdmin && (
                          <td className="px-4 py-3">
                            {item.org_id ? (
                              <span
                                className="text-xs font-mono px-1.5 py-0.5 rounded truncate max-w-[100px] inline-block"
                                style={{ background: "rgba(99,102,241,0.1)", color: "#818cf8" }}
                              >
                                {orgMap[item.org_id] ?? `org #${item.org_id}`}
                              </span>
                            ) : (
                              <span className="text-xs text-slate-700 font-mono">—</span>
                            )}
                          </td>
                        )}
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            {item.violation_scanners.map((s) => (
                              <span
                                key={s}
                                className="text-xs font-mono px-1.5 py-0.5 rounded"
                                style={{ color: "#f87171", background: "rgba(248,113,113,0.08)" }}
                              >
                                {s}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600 font-mono">
                          {item.ip_address ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500 max-w-[160px] truncate">
                          {item.raw_text.slice(0, 55)}
                        </td>
                      </tr>
                      {expanded === item.id && (
                        <tr key={`${item.id}-exp`}>
                          <td
                            colSpan={isAdmin ? 8 : 7}
                            className="px-6 py-5 border-b border-white/5"
                            style={{ background: "var(--bg)" }}
                          >
                            <ExpandedRow item={item} orgName={item.org_id ? (orgMap[item.org_id] ?? `org #${item.org_id}`) : null} isAdmin={isAdmin} />
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-600 font-mono">page {page} / {totalPages}</p>
        <div className="flex gap-2">
          {([
            ["← prev", () => setPage((p) => Math.max(1, p - 1)), page === 1],
            ["next →", () => setPage((p) => Math.min(totalPages, p + 1)), page >= totalPages],
          ] as const).map(([label, fn, disabled]) => (
            <button
              key={label}
              onClick={fn}
              disabled={disabled}
              className="text-xs px-3 py-1.5 rounded border border-white/10 text-slate-500 hover:text-white hover:border-white/20 transition-colors disabled:opacity-30"
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
