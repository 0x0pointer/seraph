"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import {
  ComposedChart, AreaChart, Area, Bar,
  Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

interface UserInfo { role: string; }
interface OrgOption { id: number; name: string; }

interface TrendPoint { date: string; total: number; violations: number; }
interface HourlyPoint { hour: string; total: number; violations: number; }
interface TopViolation { scanner: string; count: number; }
interface Summary {
  total_scans: number;
  total_violations: number;
  input_scans: number;
  output_scans: number;
  avg_risk_score: number;
}

function Sk({ h = "h-52" }: { h?: string }) {
  return <div className={`${h} rounded animate-pulse`} style={{ background: "var(--card2)" }} />;
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
        <p key={p.name} style={{ color: p.color }} className="font-mono">
          {p.name}: {p.name.includes("%") ? `${p.value.toFixed(1)}%` : p.value}
        </p>
      ))}
    </div>
  );
};

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded border border-white/5 p-4" style={{ background: "var(--card)" }}>
      <p className="text-xs uppercase tracking-wider mb-1 truncate" style={{ color: "var(--text-dim)" }}>{label}</p>
      <p className="text-2xl font-bold tracking-tight" style={{ color: color ?? "#e2e8f0" }}>{value}</p>
      {sub && <p className="text-xs mt-1" style={{ color: "var(--text-dim)" }}>{sub}</p>}
    </div>
  );
}

function rateColor(rate: number, thresholdHigh: number, thresholdLow: number, invert = false): string {
  if (invert) {
    if (rate < thresholdLow) return "#5CF097";
    if (rate < thresholdHigh) return "#fbbf24";
    return "#f87171";
  }
  if (rate >= thresholdHigh) return "#5CF097";
  if (rate >= thresholdLow) return "#fbbf24";
  return "#f87171";
}

/* ── Admin org filter banner ── */
function AdminBanner({
  filterOrgId, adminOrgs, setFilterOrgId,
}: {
  filterOrgId: string;
  adminOrgs: OrgOption[] | undefined;
  setFilterOrgId: (v: string) => void;
}) {
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
          Platform-wide view — showing analytics from{" "}
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

/* ── Top violated scanners panel ── */
function TopScannersPanel({
  topViolations, maxViolCount, totalViolations,
}: {
  topViolations: TopViolation[] | undefined;
  maxViolCount: number;
  totalViolations: number;
}) {
  if (!topViolations) return <Sk />;
  if (topViolations.length === 0) {
    return <p className="text-xs text-slate-600 py-14 text-center font-mono">No violations recorded yet.</p>;
  }
  return (
    <div className="space-y-3">
      {topViolations.slice(0, 8).map((v) => {
        const barPct = Math.round((v.count / maxViolCount) * 100);
        const sharePct = totalViolations > 0
          ? ((v.count / totalViolations) * 100).toFixed(0)
          : "0";
        return (
          <div key={v.scanner} className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-slate-400 truncate max-w-[200px]">
                {v.scanner}
              </span>
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-xs text-slate-600 font-mono">{sharePct}% of violations</span>
                <span className="text-xs font-semibold font-mono text-white w-8 text-right">{v.count}</span>
              </div>
            </div>
            <div className="h-1 rounded-full" style={{ background: "rgba(255,255,255,0.04)" }}>
              <div
                className="h-1 rounded-full transition-all"
                style={{
                  width: `${barPct}%`,
                  background: `rgba(248,113,113,${0.35 + barPct / 180})`,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function AnalyticsPage() {
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

  const { data: trends } = useSWR<TrendPoint[]>(
    `/analytics/trends?days=30${orgQs}`,
    () => api.get<TrendPoint[]>(`/analytics/trends?days=30${orgQs}`),
  );
  const { data: hourly } = useSWR<HourlyPoint[]>(
    `/analytics/hourly?${orgQs}`,
    () => api.get<HourlyPoint[]>(`/analytics/hourly?${orgQs}`),
  );
  const { data: topViolations } = useSWR<TopViolation[]>(
    `/analytics/top-violations?limit=10${orgQs}`,
    () => api.get<TopViolation[]>(`/analytics/top-violations?limit=10${orgQs}`),
  );
  const { data: summary } = useSWR<Summary>(
    `/analytics/summary?${orgQs}`,
    () => api.get<Summary>(`/analytics/summary?${orgQs}`),
  );

  // ── Derived stats ────────────────────────────────────────────────────────────
  const total30d = trends?.reduce((s, d) => s + d.total, 0) ?? 0;
  const violations30d = trends?.reduce((s, d) => s + d.violations, 0) ?? 0;
  const passRate30d = total30d > 0 ? ((total30d - violations30d) / total30d * 100) : 100;
  const violRate30d = total30d > 0 ? (violations30d / total30d * 100) : 0;
  const busiestDay = trends?.reduce<TrendPoint | null>(
    (best, d) => (best === null || d.total > best.total ? d : best), null,
  );
  const topScanner = topViolations?.[0];
  const maxViolCount = topScanner?.count ?? 1;

  const directTotal = (summary?.input_scans ?? 0) + (summary?.output_scans ?? 0);
  const inputPct = directTotal > 0 ? ((summary?.input_scans ?? 0) / directTotal * 100) : 50;
  const outputPct = 100 - inputPct;

  // Enrich trends with per-day violation rate %
  const trendsWithRate = trends?.map((d) => ({
    ...d,
    "Viol. rate %": d.total > 0 ? parseFloat((d.violations / d.total * 100).toFixed(1)) : 0,
  }));

  return (
    <div className="space-y-5 max-w-6xl">

      {/* ── Platform-wide banner + org filter (super admins only) ── */}
      {isAdmin && (
        <AdminBanner filterOrgId={filterOrgId} adminOrgs={adminOrgs} setFilterOrgId={setFilterOrgId} />
      )}

      {/* ── Stat cards ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard
          label="Scans (30d)"
          value={total30d.toLocaleString()}
          color="#e2e8f0"
          sub={`${(summary?.total_scans ?? 0).toLocaleString()} all time`}
        />
        <StatCard
          label="Violations (30d)"
          value={violations30d.toLocaleString()}
          color="#f87171"
          sub={`${(summary?.total_violations ?? 0).toLocaleString()} all time`}
        />
        <StatCard
          label="Pass Rate (30d)"
          value={`${passRate30d.toFixed(1)}%`}
          color={rateColor(passRate30d, 95, 80)}
          sub="clean scans"
        />
        <StatCard
          label="Violation Rate (30d)"
          value={`${violRate30d.toFixed(1)}%`}
          color={rateColor(violRate30d, 20, 5, true)}
          sub="of all scans"
        />
        <StatCard
          label="Busiest Day"
          value={busiestDay ? busiestDay.date.slice(5) : "—"}
          color="#a78bfa"
          sub={busiestDay ? `${busiestDay.total.toLocaleString()} scans` : "no data"}
        />
        <StatCard
          label="Top Scanner"
          value={topScanner ? topScanner.scanner.replace(/([A-Z])/g, " $1").trim() : "—"}
          color="#fbbf24"
          sub={topScanner ? `${topScanner.count} hits` : "no violations"}
        />
      </div>

      {/* ── 30-day volume + violation rate % ─────────────────────── */}
      <div className="rounded border border-white/5 p-5" style={{ background: "var(--card)" }}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">
            30-Day Volume &amp; Violation Rate
          </p>
          <div className="flex items-center gap-5 text-xs font-mono text-slate-600">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-2.5 rounded-sm" style={{ background: "rgba(255,255,255,0.1)" }} />
              Total scans
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 rounded" style={{ background: "#f87171" }} />
              Viol. rate %
            </span>
          </div>
        </div>
        {!trendsWithRate ? <Sk /> : (
          <ResponsiveContainer width="100%" height={210}>
            <ComposedChart data={trendsWithRate} margin={{ top: 0, right: 24, bottom: 0, left: -24 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="date" tick={{ fill: "#475569", fontSize: 10 }} axisLine={false} tickLine={false}
                tickFormatter={(d: string) => d.slice(5)} interval={4} />
              <YAxis yAxisId="left" tick={{ fill: "#475569", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis yAxisId="right" orientation="right" tick={{ fill: "#475569", fontSize: 10 }}
                axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
              <Tooltip content={<ChartTip />} />
              <Bar yAxisId="left" dataKey="total" fill="rgba(255,255,255,0.08)"
                name="Total scans" radius={[2, 2, 0, 0]} />
              <Line yAxisId="right" type="monotone" dataKey="Viol. rate %"
                stroke="#f87171" dot={false} strokeWidth={2} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── 24h hourly activity ───────────────────────────────────── */}
      <div className="rounded border border-white/5 p-5" style={{ background: "var(--card)" }}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">Last 24 Hours — Hourly Activity</p>
          <div className="flex items-center gap-5 text-xs font-mono text-slate-600">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 rounded" style={{ background: "rgba(255,255,255,0.15)" }} />
              Total
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 rounded" style={{ background: "#f87171" }} />
              Violations
            </span>
          </div>
        </div>
        {!hourly ? <Sk h="h-32" /> : (
          <ResponsiveContainer width="100%" height={120}>
            <AreaChart data={hourly} margin={{ top: 0, right: 0, bottom: 0, left: -28 }}>
              <defs>
                <linearGradient id="totalGradH" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="rgba(255,255,255,0.07)" stopOpacity={1} />
                  <stop offset="95%" stopColor="rgba(255,255,255,0)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="violGradH" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f87171" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fill: "#334155", fontSize: 9 }} axisLine={false} tickLine={false} interval={3} />
              <YAxis tick={{ fill: "#334155", fontSize: 9 }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTip />} />
              <Area type="monotone" dataKey="total" stroke="rgba(255,255,255,0.15)"
                fill="url(#totalGradH)" name="Total" strokeWidth={1.5} dot={false} />
              <Area type="monotone" dataKey="violations" stroke="#f87171"
                fill="url(#violGradH)" name="Violations" strokeWidth={2} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Bottom row: top scanners + input/output ───────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Top violated scanners — custom bars */}
        <div className="lg:col-span-2 rounded border border-white/5 p-5" style={{ background: "var(--card)" }}>
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider mb-4">Top Violated Scanners</p>
          <TopScannersPanel
            topViolations={topViolations}
            maxViolCount={maxViolCount}
            totalViolations={summary?.total_violations ?? 0}
          />
        </div>

        {/* Input vs Output */}
        <div className="rounded border border-white/5 p-5" style={{ background: "var(--card)" }}>
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider mb-4">Input vs Output</p>
          {!summary ? <Sk /> : (
            <div className="space-y-5">
              {([
                { label: "Input", count: summary.input_scans, pct: inputPct, color: "#5CF097" },
                { label: "Output", count: summary.output_scans, pct: outputPct, color: "#a78bfa" },
              ] as const).map(({ label, count, pct, color }) => (
                <div key={label}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
                      <span className="text-xs text-slate-400">{label}</span>
                    </div>
                    <span className="text-xs font-mono text-white">{count.toLocaleString()}</span>
                  </div>
                  <div className="h-2 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
                    <div className="h-2 rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <p className="text-xs mt-1 font-mono" style={{ color }}>{pct.toFixed(1)}%</p>
                </div>
              ))}
              <div className="border-t border-white/5 pt-3 space-y-2.5">
                {[
                  { label: "All-time scans", value: summary.total_scans.toLocaleString(), color: "var(--text)" },
                  { label: "All-time violations", value: summary.total_violations.toLocaleString(), color: "#f87171" },
                  { label: "Avg risk score", value: summary.avg_risk_score.toFixed(3), color: "#a78bfa" },
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
    </div>
  );
}
