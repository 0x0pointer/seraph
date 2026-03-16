"use client";

/* ── Shared dashboard components ──
   Extracted to avoid duplication across dashboard pages.
*/

/* ── Skeleton placeholder ── */
export function Sk({ h = "h-24", w }: { h?: string; w?: string }) {
  return <div className={`${h} ${w ?? "w-full"} rounded animate-pulse`} style={{ background: "var(--card2)" }} />;
}

/* ── Recharts tooltip ── */
export const ChartTip = ({ active, payload, label }: {
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

/* ── Admin org filter banner ── */
export interface OrgOption { id: number; name: string; }

export function AdminBanner({
  filterOrgId, adminOrgs, setFilterOrgId, label = "data",
}: Readonly<{
  filterOrgId: string;
  adminOrgs: OrgOption[] | undefined;
  setFilterOrgId: (v: string) => void;
  label?: string;
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
          Platform-wide view — showing {label} from{" "}
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
