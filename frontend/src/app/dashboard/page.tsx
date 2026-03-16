"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { format } from "date-fns";

interface UserInfo { role: string; }
interface OrgOption { id: number; name: string; }

interface Summary {
  total_scans: number;
  scans_today: number;
  violations_today: number;
  total_violations: number;
  pass_rate_today: number;
  input_scans: number;
  output_scans: number;
  active_guardrails: number;
  avg_risk_score: number;
}
interface TrendPoint { date: string; total: number; violations: number; }
interface HourlyPoint { hour: string; total: number; violations: number; }
interface AuditItem {
  id: number;
  direction: string;
  is_valid: boolean;
  violation_scanners: string[];
  raw_text: string;
  connection_name: string | null;
  created_at: string;
}
interface AuditList { items: AuditItem[]; total: number; }

function Sk({ h = "h-24", w }: { h?: string; w?: string }) {
  return <div className={`${h} ${w ?? "w-full"} rounded animate-pulse`} style={{ background: "var(--card2)" }} />;
}

const ChartTip = ({ active, payload, label }: {
  active?: boolean;
  payload?: { value: number; name: string; color: string }[];
  label?: string;
}) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-white/10 px-3 py-2 text-xs" style={{ background: "var(--card)" }}>
      <p className="text-slate-500 mb-1 font-mono">{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }} className="font-mono">{p.name}: {p.value}</p>
      ))}
    </div>
  );
};

function passRateColor(r: number) {
  if (r >= 95) return "#5CF097";
  if (r >= 80) return "#fbbf24";
  return "#f87171";
}
function riskColor(r: number) {
  if (r < 0.3) return "#5CF097";
  if (r < 0.6) return "#fbbf24";
  return "#f87171";
}

/* ── Admin org filter banner ── */
function AdminBanner({
  filterOrgId, adminOrgs, setFilterOrgId,
}: Readonly<{
  filterOrgId: string;
  adminOrgs: OrgOption[] | undefined;
  setFilterOrgId: (v: string) => void;
}>) {
  return (
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
          Platform-wide view — showing data from{" "}
          <span className="font-semibold">
            {filterOrgId && adminOrgs
              ? (adminOrgs.find((o) => String(o.id) === filterOrgId)?.name ?? "selected org")
              : "all organizations"}
          </span>
        </p>
      </div>
      <select
        value={filterOrgId}
        onChange={(e) => setFilterOrgId(e.target.value)}
        className="text-sm rounded px-3 py-2 outline-none shrink-0"
        style={{ background: "var(--card)", border: "1px solid var(--border-input)", color: "var(--text-muted)" }}
      >
        <option value="">All organizations</option>
        {adminOrgs?.map((o) => (
          <option key={o.id} value={String(o.id)}>{o.name}</option>
        ))}
      </select>
    </div>
  );
}

/* ── Recent scans table ── */
function RecentScansTable({ auditData }: Readonly<{ auditData: AuditList | undefined }>) {
  return (
    <div className="rounded border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
      <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">Recent Scans</p>
        <a href="/dashboard/audit" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">
          View all →
        </a>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/5">
            {["Time", "Dir", "Status", "Connection", "Violations", "Preview"].map((h) => (
              <th key={h} className="px-5 py-3 text-left text-xs text-slate-700 font-mono uppercase tracking-wider">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {!auditData
            ? Array.from({ length: 5 }).map((_, i) => (
              <tr key={i} className="border-b border-white/5">
                <td colSpan={6} className="px-5 py-3">
                  <div className="h-3 rounded animate-pulse" style={{ background: "var(--card2)" }} />
                </td>
              </tr>
            ))
            : auditData.items.map((item) => (
              <tr key={item.id} className="border-b border-white/5 hover:bg-white/[0.015] transition-colors">
                <td className="px-5 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
                  {format(new Date(item.created_at), "HH:mm:ss")}
                </td>
                <td className="px-5 py-3">
                  <span className="text-xs font-mono text-slate-600">{item.direction}</span>
                </td>
                <td className="px-5 py-3">
                  <span
                    className="text-xs font-mono px-2 py-0.5 rounded"
                    style={item.is_valid
                      ? { background: "rgba(92,240,151,0.08)", color: "#5CF097" }
                      : { background: "rgba(248,113,113,0.08)", color: "#f87171" }
                    }
                  >
                    {item.is_valid ? "pass" : "block"}
                  </span>
                </td>
                <td className="px-5 py-3 text-xs text-slate-600 font-mono truncate max-w-[100px]">
                  {item.connection_name ?? "---"}
                </td>
                <td className="px-5 py-3 text-xs font-mono" style={{ color: item.violation_scanners.length > 0 ? "#f87171" : "#334155" }}>
                  {(() => {
                    const scanners = item.violation_scanners;
                    if (scanners.length === 0) return "---";
                    const preview = scanners.slice(0, 2).join(", ");
                    return scanners.length > 2 ? `${preview} ...` : preview;
                  })()}
                </td>
                <td className="px-5 py-3 text-xs text-slate-500 max-w-xs truncate">
                  {item.raw_text.slice(0, 55)}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DashboardOverview() {
  const [filterOrgId, setFilterOrgId] = useState("");

  const { data: me } = useSWR<UserInfo>(
    "/auth/me", () => api.get<UserInfo>("/auth/me"), { revalidateOnFocus: false },
  );
  const isAdmin = me?.role === "admin";

  const { data: adminOrgs } = useSWR<OrgOption[]>(
    isAdmin ? "/admin/orgs" : null,
    () => api.get<OrgOption[]>("/admin/orgs"),
  );

  const orgQs = filterOrgId ? `&filter_org_id=${filterOrgId}` : "";

  const { data: summary, error: summaryErr } = useSWR<Summary>(
    `/analytics/summary?${orgQs}`, () => api.get<Summary>(`/analytics/summary?${orgQs}`),
  );
  const { data: trends } = useSWR<TrendPoint[]>(
    `/analytics/trends?days=7${orgQs}`, () => api.get<TrendPoint[]>(`/analytics/trends?days=7${orgQs}`),
  );
  const { data: hourly } = useSWR<HourlyPoint[]>(
    `/analytics/hourly?${orgQs}`, () => api.get<HourlyPoint[]>(`/analytics/hourly?${orgQs}`),
  );
  const { data: auditData } = useSWR<AuditList>(
    `/audit?page=1&page_size=8${orgQs}`, () => api.get<AuditList>(`/audit?page=1&page_size=8${orgQs}`),
  );

  const directTotal = (summary?.input_scans ?? 0) + (summary?.output_scans ?? 0);
  const inputPct = directTotal > 0 ? ((summary?.input_scans ?? 0) / directTotal) * 100 : 50;
  const outputPct = 100 - inputPct;

  return (
    <div className="space-y-5 max-w-6xl">

      {/* ── Platform-wide banner + org filter (super admins only) ── */}
      {isAdmin && (
        <AdminBanner filterOrgId={filterOrgId} adminOrgs={adminOrgs} setFilterOrgId={setFilterOrgId} />
      )}

      {/* ── Stat cards ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        {!summary ? (
          Array.from({ length: 6 }).map((_, i) => <Sk key={i} h="h-20" />)
        ) : ([
          {
            label: "Total Scans", value: summary.total_scans.toLocaleString(),
            sub: "all time", color: "var(--text)",
          },
          {
            label: "Scans Today", value: summary.scans_today.toLocaleString(),
            sub: "since midnight UTC", color: "#5CF097",
          },
          {
            label: "Violations Today", value: summary.violations_today.toLocaleString(),
            sub: `${summary.total_violations.toLocaleString()} all time`,
            color: summary.violations_today > 0 ? "#f87171" : "#5CF097",
          },
          {
            label: "Pass Rate Today", value: `${summary.pass_rate_today.toFixed(1)}%`,
            sub: summary.scans_today > 0
              ? `${(summary.scans_today - summary.violations_today).toLocaleString()} clean`
              : "no scans yet",
            color: passRateColor(summary.pass_rate_today),
          },
          {
            label: "Active Guardrails", value: String(summary.active_guardrails),
            sub: "scanning now", color: "#a78bfa",
          },
          {
            label: "Avg Risk Score", value: summary.avg_risk_score.toFixed(3),
            sub: "across all scanners", color: riskColor(summary.avg_risk_score),
          },
        ].map(({ label, value, sub, color }) => (
          <div key={label} className="rounded border border-white/5 p-4" style={{ background: "var(--card)" }}>
            <p className="text-xs uppercase tracking-wider mb-1 truncate" style={{ color: "var(--text-dim)" }}>{label}</p>
            <p className="text-2xl font-bold tracking-tight" style={{ color }}>{value}</p>
            <p className="text-xs text-slate-600 mt-1">{sub}</p>
          </div>
        )))}
      </div>

      {/* ── Middle row: 7-day chart + traffic split ───────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* 7-day area chart */}
        <div className="lg:col-span-2 rounded border border-white/5 p-5" style={{ background: "var(--card)" }}>
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider mb-4">
            Violations — Last 7 Days
          </p>
          {!trends ? <Sk h="h-36" /> : (
            <ResponsiveContainer width="100%" height={140}>
              <AreaChart data={trends} margin={{ top: 0, right: 0, bottom: 0, left: -24 }}>
                <defs>
                  <linearGradient id="totalGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="rgba(255,255,255,0.06)" stopOpacity={1} />
                    <stop offset="95%" stopColor="rgba(255,255,255,0)" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="violGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#5CF097" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#5CF097" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="date" tick={{ fill: "#475569", fontSize: 10 }} axisLine={false} tickLine={false}
                  tickFormatter={(d: string) => d.slice(5)} />
                <YAxis tick={{ fill: "#475569", fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTip />} />
                <Area type="monotone" dataKey="total" stroke="rgba(255,255,255,0.12)"
                  fill="url(#totalGrad)" name="Total" strokeWidth={1} dot={false} />
                <Area type="monotone" dataKey="violations" stroke="#5CF097"
                  fill="url(#violGrad)" name="Violations" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Traffic split */}
        <div className="rounded border border-white/5 p-5" style={{ background: "var(--card)" }}>
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider mb-4">Traffic Split</p>
          {!summary ? <Sk h="h-36" /> : (
            <div className="space-y-4">
              {([
                { label: "Input", count: summary.input_scans, pct: inputPct, color: "#5CF097" },
                { label: "Output", count: summary.output_scans, pct: outputPct, color: "#a78bfa" },
              ] as const).map(({ label, count, pct, color }) => (
                <div key={label}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs text-slate-400">{label} scans</span>
                    <span className="text-xs font-mono text-white">{count.toLocaleString()}</span>
                  </div>
                  <div className="h-1.5 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
                    <div className="h-1.5 rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <p className="text-xs mt-1 font-mono" style={{ color }}>{pct.toFixed(1)}%</p>
                </div>
              ))}
              <div className="border-t border-white/5 pt-3 space-y-2">
                {[
                  { label: "Total today", value: summary.scans_today.toLocaleString(), color: "var(--text)" },
                  { label: "Clean today", value: (summary.scans_today - summary.violations_today).toLocaleString(), color: "#5CF097" },
                  { label: "Blocked today", value: summary.violations_today.toLocaleString(), color: summary.violations_today > 0 ? "#f87171" : "#64748b" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">{label}</span>
                    <span className="text-xs font-mono" style={{ color }}>{value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 24h hourly activity ───────────────────────────────────── */}
      <div className="rounded border border-white/5 p-5" style={{ background: "var(--card)" }}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">Last 24 Hours — Scan Activity</p>
          <div className="flex items-center gap-4 text-xs font-mono text-slate-600">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-2 rounded-sm" style={{ background: "rgba(255,255,255,0.1)" }} />
              Total
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-2 rounded-sm" style={{ background: "rgba(248,113,113,0.7)" }} />
              Violations
            </span>
          </div>
        </div>
        {!hourly ? <Sk h="h-24" /> : (
          <ResponsiveContainer width="100%" height={90}>
            <BarChart data={hourly} margin={{ top: 0, right: 0, bottom: 0, left: -28 }} barGap={1}>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fill: "#334155", fontSize: 9 }} axisLine={false} tickLine={false} interval={3} />
              <YAxis tick={{ fill: "#334155", fontSize: 9 }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTip />} />
              <Bar dataKey="total" fill="rgba(255,255,255,0.08)" name="Total" radius={[1, 1, 0, 0]} />
              <Bar dataKey="violations" fill="rgba(248,113,113,0.7)" name="Violations" radius={[1, 1, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Recent scans ──────────────────────────────────────────── */}
      <RecentScansTable auditData={auditData} />

      {summaryErr && (
        <p className="text-xs text-red-400 border border-red-400/20 rounded px-4 py-3" style={{ background: "rgba(248,113,113,0.05)" }}>
          Cannot reach backend API.
        </p>
      )}
    </div>
  );
}
