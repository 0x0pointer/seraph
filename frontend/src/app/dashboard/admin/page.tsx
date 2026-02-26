"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Cookies from "js-cookie";
import useSWR from "swr";
import { api } from "@/lib/api";
import { format, formatDistanceToNow } from "date-fns";

// ── Interfaces ────────────────────────────────────────────────────────────────

interface Me { role: string; }

interface AdminStats {
  total_users: number; admin_users: number; viewer_users: number; new_users_week: number;
  total_scans: number; scans_today: number;
  total_violations: number; violations_today: number;
  pass_rate: number; pass_rate_today: number;
  total_guardrails: number; active_guardrails: number;
  total_connections: number; blocked_connections: number;
  total_month_spend: number;
}

interface AdminUser {
  id: number; username: string; full_name: string | null; email: string | null;
  role: string; plan?: string; org_id: number | null; org_name: string | null;
  created_at: string | null;
  connection_count: number; total_requests: number; last_active_at: string | null;
}

interface AdminConnection {
  id: number; name: string; environment: string; status: string;
  user_id: number; username: string; full_name: string | null;
  total_requests: number; total_violations: number; month_spend: number;
  monthly_alert_spend: number | null; max_monthly_spend: number | null;
  alert_enabled: boolean; alert_threshold: number | null;
  created_at: string | null; last_active_at: string | null;
}

interface ActivityEntry {
  id: number; direction: string; is_valid: boolean;
  violation_scanners: string[]; scanner_results: Record<string, number>;
  connection_name: string | null; connection_environment: string | null;
  ip_address: string | null; max_risk_score: number;
  token_cost: number | null; preview: string; created_at: string | null;
}

interface GuardrailEntry {
  id: number; name: string; scanner_type: string;
  direction: string; is_active: boolean; order: number;
}

interface TopViolation { scanner: string; count: number; }

interface BillingStats {
  plan_counts: Record<string, number>;
  mrr: number;
  total_invoiced: number;
  total_paid: number;
  total_open: number;
  invoice_stats: Record<string, { count: number; total: number }>;
}

interface AdminInvoice {
  id: number; invoice_number: string; amount: number; currency: string;
  status: string; description: string | null;
  period_start: string | null; period_end: string | null;
  paid_at: string | null; created_at: string | null;
  user_id: number; username: string; user_plan: string;
}

interface AdminInvoicePage {
  total: number; page: number; limit: number; items: AdminInvoice[];
}

interface AuditEntry {
  id: number; direction: string; is_valid: boolean;
  raw_text: string; scanner_results: Record<string, number>;
  violation_scanners: string[]; connection_name: string | null;
  connection_environment: string | null; ip_address: string | null;
  input_tokens: number | null; output_tokens: number | null;
  token_cost: number | null; max_risk_score: number;
  created_at: string | null;
}

interface AdminAuditPage {
  total: number; page: number; limit: number; items: AuditEntry[];
}

interface SystemEventEntry {
  id: number; event_type: string;
  actor_id: number | null; actor_username: string | null;
  target_type: string | null; target_id: number | null; target_name: string | null;
  details: Record<string, unknown>; ip_address: string | null;
  created_at: string | null;
}

interface SystemEventsPage {
  total: number; page: number; limit: number; items: SystemEventEntry[];
}

type AdminTab = "overview" | "users" | "connections" | "guardrails" | "audits" | "orgs" | "billing" | "settings" | "activity";

// ── Helpers ───────────────────────────────────────────────────────────────────

const inputStyle = { background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#e2e8f0" };

function Sk({ h = "h-16", cols = 1 }: { h?: string; cols?: number }) {
  return (
    <>
      {Array.from({ length: cols }).map((_, i) => (
        <div key={i} className={`${h} rounded animate-pulse`} style={{ background: "#111827" }} />
      ))}
    </>
  );
}

function StatCard({ label, value, sub, color, warn }: {
  label: string; value: string; sub?: string; color?: string; warn?: boolean;
}) {
  return (
    <div className="rounded border p-4" style={{
      background: "#0d1426",
      borderColor: warn ? "rgba(248,113,113,0.3)" : "rgba(255,255,255,0.05)",
    }}>
      <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-bold tracking-tight" style={{ color: color ?? "#e2e8f0" }}>{value}</p>
      {sub && <p className="text-xs text-slate-600 mt-1">{sub}</p>}
    </div>
  );
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }); }
  catch { return "—"; }
}

const ENV_COLOR: Record<string, { background: string; color: string }> = {
  production: { background: "rgba(20,184,166,0.1)", color: "#14B8A6" },
  development: { background: "rgba(251,191,36,0.1)", color: "#fbbf24" },
  staging: { background: "rgba(148,163,184,0.1)", color: "#94a3b8" },
};

function Section({ title, action, children }: {
  title: string; action?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">{title}</p>
        {action}
      </div>
      {children}
    </div>
  );
}

// ── Modals ────────────────────────────────────────────────────────────────────

interface OrgOption { id: number; name: string; }

function AssignOrgModal({ user, orgs, onClose, onSaved }: {
  user: AdminUser;
  orgs: OrgOption[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [orgId, setOrgId] = useState<string>(user.org_id ? String(user.org_id) : "");
  const [role, setRole] = useState(user.role === "admin" ? user.role : (user.org_id ? user.role : "viewer"));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave(e: React.FormEvent) {
    e.preventDefault(); setError(""); setSaving(true);
    try {
      await api.patch(`/admin/users/${user.id}/org`, {
        org_id: orgId ? Number(orgId) : null,
        role: orgId ? role : null,
      });
      onSaved();
    } catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
    finally { setSaving(false); }
  }

  async function handleRemove() {
    setSaving(true);
    try { await api.patch(`/admin/users/${user.id}/org`, { org_id: null }); onSaved(); }
    catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
    finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.8)" }} onClick={onClose}>
      <div className="w-full max-w-sm mx-4 rounded-lg border p-6 space-y-4"
        style={{ background: "#0d1426", borderColor: "rgba(255,255,255,0.08)" }}
        onClick={(e) => e.stopPropagation()}>
        <div>
          <p className="text-sm font-semibold text-white">Assign to organization</p>
          <p className="text-xs text-slate-500 mt-0.5 font-mono">@{user.username}</p>
        </div>

        {user.org_name && (
          <div className="rounded px-3 py-2 flex items-center justify-between"
            style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.06)" }}>
            <div>
              <p className="text-xs text-slate-500">Current org</p>
              <p className="text-xs text-white font-medium">{user.org_name}</p>
            </div>
            <button onClick={handleRemove} disabled={saving}
              className="text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40"
              style={{ borderColor: "rgba(248,113,113,0.25)", color: "#f87171" }}>
              Remove
            </button>
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-3">
          <div>
            <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Organization</label>
            <div className="relative">
              <select value={orgId} onChange={(e) => setOrgId(e.target.value)}
                className="w-full rounded px-3 py-2 text-sm outline-none appearance-none pr-8"
                style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#e2e8f0" }}>
                <option value="">— No organization —</option>
                {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none text-xs">▾</span>
            </div>
          </div>

          {orgId && user.role !== "admin" && (
            <div>
              <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Role in org</label>
              <div className="flex gap-2">
                {[{ v: "viewer", label: "Member" }, { v: "org_admin", label: "Org Admin" }].map(({ v, label }) => (
                  <button key={v} type="button" onClick={() => setRole(v)}
                    className="flex-1 py-1.5 rounded text-xs font-medium border transition-colors"
                    style={role === v
                      ? { background: "#14B8A6", color: "#0A0F1F", borderColor: "#14B8A6" }
                      : { background: "transparent", color: "#64748b", borderColor: "rgba(255,255,255,0.08)" }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-3 pt-1">
            <button type="submit" disabled={saving}
              className="flex-1 py-2 rounded text-sm font-medium disabled:opacity-50"
              style={{ background: "#14B8A6", color: "#0A0F1F" }}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button type="button" onClick={onClose}
              className="flex-1 py-2 rounded text-sm border border-white/10 text-slate-400 hover:text-white transition-colors">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DeleteModal({ user, onConfirm, onCancel }: {
  user: AdminUser; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.8)" }} onClick={onCancel}>
      <div className="w-full max-w-md mx-4 rounded-lg border p-6 space-y-4"
        style={{ background: "#0d1426", borderColor: "rgba(248,113,113,0.3)" }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full flex items-center justify-center"
            style={{ background: "rgba(248,113,113,0.1)" }}>
            <svg className="w-5 h-5" style={{ color: "#f87171" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Delete user account</p>
            <p className="text-xs text-slate-500">This cannot be undone</p>
          </div>
        </div>
        <p className="text-xs text-slate-400 leading-relaxed">
          Permanently delete <span className="font-mono text-white font-semibold">{user.username}</span>
          {user.full_name ? ` (${user.full_name})` : ""}. Audit logs and connections remain.
        </p>
        <div className="flex gap-3">
          <button onClick={onConfirm} className="flex-1 py-2 rounded text-sm font-medium"
            style={{ background: "rgba(248,113,113,0.15)", color: "#f87171", border: "1px solid rgba(248,113,113,0.3)" }}>
            Yes, delete permanently
          </button>
          <button onClick={onCancel}
            className="flex-1 py-2 rounded text-sm border border-white/10 text-slate-400 hover:text-white transition-colors">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function ResetPasswordModal({ user, onClose }: { user: AdminUser; onClose: () => void; }) {
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setError(""); setSaving(true);
    try { await api.patch(`/admin/users/${user.id}/password`, { password }); setDone(true); }
    catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
    finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.8)" }} onClick={onClose}>
      <div className="w-full max-w-sm mx-4 rounded-lg border p-6 space-y-4"
        style={{ background: "#0d1426", borderColor: "rgba(255,255,255,0.08)" }}
        onClick={(e) => e.stopPropagation()}>
        <div>
          <p className="text-sm font-semibold text-white">Reset password</p>
          <p className="text-xs text-slate-500 mt-0.5">For <span className="font-mono text-slate-300">{user.username}</span></p>
        </div>
        {done ? (
          <div className="space-y-3">
            <p className="text-xs font-mono" style={{ color: "#14B8A6" }}>✓ Password updated.</p>
            <button onClick={onClose} className="w-full py-2 rounded text-sm border border-white/10 text-slate-400 hover:text-white transition-colors">Close</button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">New password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                required minLength={6} placeholder="Min. 6 characters"
                className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
            </div>
            {error && <p className="text-xs text-red-400">{error}</p>}
            <div className="flex gap-3">
              <button type="submit" disabled={saving}
                className="flex-1 py-2 rounded text-sm font-medium disabled:opacity-50"
                style={{ background: "#14B8A6", color: "#0A0F1F" }}>
                {saving ? "Saving…" : "Set password"}
              </button>
              <button type="button" onClick={onClose}
                className="flex-1 py-2 rounded text-sm border border-white/10 text-slate-400 hover:text-white transition-colors">
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// ── Create user panel ─────────────────────────────────────────────────────────

function CreateUserPanel({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void; }) {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setError(""); setSaving(true);
    try {
      await api.post("/admin/users", { username, full_name: fullName || null, email: email || null, password, role });
      onCreated();
    } catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
    finally { setSaving(false); }
  }

  return (
    <div className="rounded border p-5 space-y-4" style={{ background: "#0d1426", borderColor: "rgba(20,184,166,0.2)" }}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-mono text-slate-400 uppercase tracking-wider">New User Account</p>
        <button onClick={onCancel} className="text-xs text-slate-600 hover:text-slate-400">✕ Cancel</button>
      </div>
      <form onSubmit={handleSubmit} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Username *</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} required placeholder="e.g. jane.doe"
            className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Password * (min 6)</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6}
            className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Full Name</label>
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jane Doe"
            className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="jane@company.com"
            className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Role</label>
          <div className="relative">
            <select value={role} onChange={(e) => setRole(e.target.value)}
              className="w-full rounded px-3 py-2 text-sm outline-none appearance-none pr-8" style={inputStyle}>
              <option value="viewer">Viewer — standard access</option>
              <option value="support">Support — ticket management + impersonation</option>
              <option value="admin">Admin — full platform access</option>
            </select>
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none text-xs">▾</span>
          </div>
        </div>
        <div className="sm:col-span-2 flex items-center gap-4">
          <button type="submit" disabled={saving} className="text-sm font-medium px-5 py-2 rounded disabled:opacity-50"
            style={{ background: "#14B8A6", color: "#0A0F1F" }}>
            {saving ? "Creating…" : "Create user"}
          </button>
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
      </form>
    </div>
  );
}

// ── User actions dropdown ─────────────────────────────────────────────────────

const ALL_ROLES: { value: string; label: string }[] = [
  { value: "viewer",   label: "Viewer" },
  { value: "support",  label: "Support" },
  { value: "org_admin", label: "Org Admin" },
  { value: "admin",    label: "Admin" },
];

const ALL_PLANS = [
  { value: "free",       label: "Free",       color: "#94a3b8" },
  { value: "pro",        label: "Pro",        color: "#14B8A6" },
  { value: "enterprise", label: "Enterprise", color: "#a78bfa" },
];

function UserActions({ user, onRoleChange, onPlanChange, onResetPw, onDelete, onImpersonate, onAssignOrg, roleLoading }: {
  user: AdminUser; onRoleChange: (role: string) => void; onPlanChange: (plan: string) => void;
  onResetPw: () => void; onDelete: () => void; onImpersonate: () => void; onAssignOrg: () => void; roleLoading: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [showRoles, setShowRoles] = useState(false);
  const [showPlans, setShowPlans] = useState(false);
  const currentPlan = user.plan ?? "free";
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)}
        className="text-xs px-2.5 py-1 rounded border transition-colors"
        style={{ borderColor: "rgba(255,255,255,0.08)", color: "#64748b" }}>
        Actions ▾
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => { setOpen(false); setShowRoles(false); setShowPlans(false); }} />
          <div className="absolute right-0 mt-1 w-52 rounded border z-20 overflow-hidden py-1"
            style={{ background: "#0A0F1F", borderColor: "rgba(255,255,255,0.08)" }}>
            <button onClick={() => { setShowRoles(!showRoles); setShowPlans(false); }} disabled={roleLoading}
              className="w-full text-left px-3 py-2 text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-40">
              {roleLoading ? "Updating…" : `Change role (${user.role}) ▾`}
            </button>
            {showRoles && ALL_ROLES.filter((r) => r.value !== user.role).map((r) => (
              <button key={r.value} onClick={() => { onRoleChange(r.value); setOpen(false); setShowRoles(false); }}
                className="w-full text-left px-6 py-1.5 text-xs text-slate-500 hover:text-white hover:bg-white/5 transition-colors">
                → Set as {r.label}
              </button>
            ))}
            <button onClick={() => { setShowPlans(!showPlans); setShowRoles(false); }} disabled={roleLoading}
              className="w-full text-left px-3 py-2 text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-40">
              {roleLoading ? "Updating…" : `Change plan (${currentPlan}) ▾`}
            </button>
            {showPlans && ALL_PLANS.filter((p) => p.value !== currentPlan).map((p) => (
              <button key={p.value} onClick={() => { onPlanChange(p.value); setOpen(false); setShowPlans(false); }}
                className="w-full text-left px-6 py-1.5 text-xs hover:bg-white/5 transition-colors"
                style={{ color: p.color }}>
                → Set as {p.label}
              </button>
            ))}
            <button onClick={() => { onResetPw(); setOpen(false); }}
              className="w-full text-left px-3 py-2 text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors">
              Reset password
            </button>
            <button onClick={() => { onAssignOrg(); setOpen(false); }}
              className="w-full text-left px-3 py-2 text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors">
              Assign to org
            </button>
            <button onClick={() => { onImpersonate(); setOpen(false); }}
              className="w-full text-left px-3 py-2 text-xs hover:bg-white/5 transition-colors" style={{ color: "#fbbf24" }}>
              Impersonate user
            </button>
            <div className="border-t border-white/5 my-1" />
            <button onClick={() => { onDelete(); setOpen(false); }}
              className="w-full text-left px-3 py-2 text-xs hover:bg-white/5 transition-colors" style={{ color: "#f87171" }}>
              Delete account
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── Audit log expandable row ──────────────────────────────────────────────────

function AuditRow({ entry }: { entry: AuditEntry }) {
  const [expanded, setExpanded] = useState(false);
  const riskColor = entry.max_risk_score >= 0.8 ? "#f87171" : entry.max_risk_score >= 0.5 ? "#fbbf24" : "#94a3b8";
  const envStyle = entry.connection_environment
    ? (ENV_COLOR[entry.connection_environment] ?? ENV_COLOR.staging) : null;

  return (
    <>
      <tr
        onClick={() => setExpanded((v) => !v)}
        className="border-b border-white/5 last:border-0 cursor-pointer transition-colors"
        style={{ background: expanded ? "rgba(20,184,166,0.02)" : undefined }}
        onMouseEnter={(e) => { if (!expanded) e.currentTarget.style.background = "rgba(255,255,255,0.01)"; }}
        onMouseLeave={(e) => { if (!expanded) e.currentTarget.style.background = ""; }}
      >
        <td className="px-4 py-3 text-xs font-mono text-slate-600">#{entry.id}</td>
        <td className="px-4 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
          {entry.created_at ? format(new Date(entry.created_at), "MM/dd HH:mm:ss") : "—"}
        </td>
        <td className="px-4 py-3 text-xs text-slate-600 font-mono">{entry.direction}</td>
        <td className="px-4 py-3">
          <span className="text-xs font-mono px-2 py-0.5 rounded"
            style={entry.is_valid
              ? { background: "rgba(20,184,166,0.08)", color: "#14B8A6" }
              : { background: "rgba(248,113,113,0.08)", color: "#f87171" }}>
            {entry.is_valid ? "pass" : "block"}
          </span>
        </td>
        <td className="px-4 py-3 text-xs font-mono" style={{ color: riskColor }}>
          {entry.max_risk_score.toFixed(2)}
        </td>
        <td className="px-4 py-3">
          {entry.connection_name ? (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-400 truncate max-w-[90px]">{entry.connection_name}</span>
              {envStyle && (
                <span className="text-xs px-1 py-0.5 rounded font-mono capitalize shrink-0" style={envStyle}>
                  {entry.connection_environment}
                </span>
              )}
            </div>
          ) : (
            <span className="text-xs text-slate-700 font-mono">direct</span>
          )}
        </td>
        <td className="px-4 py-3 text-xs font-mono"
          style={{ color: entry.violation_scanners.length > 0 ? "#f87171" : "#334155" }}>
          {entry.violation_scanners.length > 0
            ? entry.violation_scanners.slice(0, 2).join(", ") + (entry.violation_scanners.length > 2 ? " …" : "")
            : "—"}
        </td>
        <td className="px-4 py-3 text-xs text-slate-500 max-w-[200px] truncate">
          {entry.raw_text.slice(0, 80)}
        </td>
        <td className="px-4 py-3 text-xs font-mono" style={{ color: "#a78bfa" }}>
          {entry.token_cost != null ? `$${entry.token_cost.toFixed(4)}` : "—"}
        </td>
        <td className="px-4 py-3 text-xs text-slate-700 font-mono">{expanded ? "▲" : "▼"}</td>
      </tr>

      {expanded && (
        <tr className="border-b border-white/5">
          <td colSpan={10} className="px-4 pb-4 pt-1">
            <div className="rounded border border-white/5 p-4 space-y-4" style={{ background: "#0A0F1F" }}>
              {/* Full prompt text */}
              <div>
                <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-2">Full text</p>
                <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap break-words font-mono"
                  style={{ maxHeight: 160, overflowY: "auto" }}>
                  {entry.raw_text}
                </p>
              </div>

              {/* Scanner results */}
              {Object.keys(entry.scanner_results ?? {}).length > 0 && (
                <div>
                  <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-2">Scanner scores</p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {Object.entries(entry.scanner_results)
                      .sort(([, a], [, b]) => b - a)
                      .map(([name, score]) => {
                        const pct = Math.round(score * 100);
                        const isViol = entry.violation_scanners.includes(name);
                        const barColor = isViol ? "#f87171" : score > 0.4 ? "#fbbf24" : "#14B8A6";
                        return (
                          <div key={name} className="rounded px-3 py-2 border border-white/5"
                            style={{ background: isViol ? "rgba(248,113,113,0.04)" : "#0d1426" }}>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-xs font-mono text-slate-400 truncate mr-2">{name}</span>
                              <span className="text-xs font-mono shrink-0"
                                style={{ color: isViol ? "#f87171" : "#475569" }}>
                                {isViol ? "✗" : "✓"} {pct}%
                              </span>
                            </div>
                            <div className="h-1 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
                              <div className="h-1 rounded-full transition-all"
                                style={{ width: `${pct}%`, background: barColor }} />
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}

              {/* Token info */}
              {(entry.input_tokens != null || entry.token_cost != null) && (
                <div className="flex gap-6 text-xs font-mono">
                  {entry.input_tokens != null && (
                    <span className="text-slate-500">in: <span className="text-slate-300">{entry.input_tokens}</span> tokens</span>
                  )}
                  {entry.output_tokens != null && (
                    <span className="text-slate-500">out: <span className="text-slate-300">{entry.output_tokens}</span> tokens</span>
                  )}
                  {entry.token_cost != null && (
                    <span className="text-slate-500">cost: <span style={{ color: "#a78bfa" }}>${entry.token_cost.toFixed(6)}</span></span>
                  )}
                  {entry.ip_address && (
                    <span className="text-slate-500">ip: <span className="text-slate-400">{entry.ip_address}</span></span>
                  )}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Pagination helper ─────────────────────────────────────────────────────────

function Pagination({ page, total, limit, onPage }: { page: number; total: number; limit: number; onPage: (p: number) => void }) {
  const totalPages = Math.ceil(total / limit);
  if (totalPages <= 1) return null;
  return (
    <div className="px-4 py-3 border-t border-white/5 flex items-center justify-between">
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}
        className="text-xs font-mono px-3 py-1 rounded border border-white/10 text-slate-400 hover:text-white disabled:opacity-30 transition-colors">
        ← Prev
      </button>
      <div className="flex items-center gap-1">
        {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
          const p = totalPages <= 7 ? i + 1 : page <= 4 ? i + 1 : page >= totalPages - 3 ? totalPages - 6 + i : page - 3 + i;
          return (
            <button key={p} onClick={() => onPage(p)}
              className="w-7 h-7 rounded text-xs font-mono transition-colors"
              style={p === page ? { background: "#14B8A6", color: "#0A0F1F" } : { color: "#64748b" }}>
              {p}
            </button>
          );
        })}
      </div>
      <button disabled={page >= totalPages} onClick={() => onPage(page + 1)}
        className="text-xs font-mono px-3 py-1 rounded border border-white/10 text-slate-400 hover:text-white disabled:opacity-30 transition-colors">
        Next →
      </button>
    </div>
  );
}

// ── System Events sub-tab ─────────────────────────────────────────────────────

const EVENT_STYLES: Record<string, { background: string; color: string }> = {
  "user.created":        { background: "rgba(20,184,166,0.1)",  color: "#14B8A6" },
  "user.registered":     { background: "rgba(20,184,166,0.08)", color: "#5eead4" },
  "user.deleted":        { background: "rgba(248,113,113,0.1)", color: "#f87171" },
  "user.role_changed":   { background: "rgba(251,191,36,0.1)",  color: "#fbbf24" },
  "user.password_reset": { background: "rgba(251,191,36,0.08)", color: "#fbbf24" },
  "user.impersonated":   { background: "rgba(251,191,36,0.12)", color: "#fbbf24" },
  "guardrail.created":   { background: "rgba(20,184,166,0.1)",  color: "#14B8A6" },
  "guardrail.updated":   { background: "rgba(148,163,184,0.1)", color: "#94a3b8" },
  "guardrail.deleted":   { background: "rgba(248,113,113,0.1)", color: "#f87171" },
  "guardrail.toggled":   { background: "rgba(167,139,250,0.1)", color: "#a78bfa" },
  "connection.created":  { background: "rgba(20,184,166,0.1)",  color: "#14B8A6" },
  "connection.updated":  { background: "rgba(148,163,184,0.1)", color: "#94a3b8" },
  "connection.deleted":  { background: "rgba(248,113,113,0.1)", color: "#f87171" },
  "connection.toggled":  { background: "rgba(251,191,36,0.1)",  color: "#fbbf24" },
  "connection.spend_reset": { background: "rgba(167,139,250,0.1)", color: "#a78bfa" },
  "org.created":            { background: "rgba(20,184,166,0.1)",  color: "#14B8A6" },
  "org.deleted":            { background: "rgba(248,113,113,0.1)", color: "#f87171" },
  "org.member_removed":     { background: "rgba(251,191,36,0.1)",  color: "#fbbf24" },
  "org.invite_created":     { background: "rgba(20,184,166,0.08)", color: "#5eead4" },
  "user.org_assigned":      { background: "rgba(167,139,250,0.1)", color: "#a78bfa" },
};

function eventSummary(e: SystemEventEntry): string {
  const actor = e.actor_username ?? "system";
  const target = e.target_name ? `"${e.target_name}"` : "";
  const d = e.details;
  switch (e.event_type) {
    case "user.created":        return `${actor} created user ${target} with role ${d.role}`;
    case "user.registered":     return `${target} registered as a new viewer account`;
    case "user.deleted":        return `${actor} deleted user ${target}`;
    case "user.role_changed":   return `${actor} changed ${target}'s role from ${d.old_role} → ${d.new_role}`;
    case "user.password_reset": return `${actor} reset password for ${target}`;
    case "user.impersonated":   return `${actor} started an impersonation session as ${target}`;
    case "guardrail.created":   return `${actor} created guardrail ${target} (${d.scanner_type}, ${d.direction})`;
    case "guardrail.updated":   return `${actor} updated guardrail ${target}`;
    case "guardrail.deleted":   return `${actor} deleted guardrail ${target}`;
    case "guardrail.toggled":   return `${actor} ${d.is_active ? "enabled" : "disabled"} guardrail ${target}`;
    case "connection.created":  return `${actor} created API connection ${target} (${d.environment})`;
    case "connection.updated":  return `${actor} updated API connection ${target}`;
    case "connection.deleted":  return `${actor} deleted API connection ${target}`;
    case "connection.toggled":  return `${actor} set API connection ${target} to ${d.status}`;
    case "connection.spend_reset": return `${actor} reset monthly spend for ${target} (was $${d.previous_spend})`;
    case "org.created":         return `${actor} created organization ${target}`;
    case "org.deleted":         return `${actor} deleted organization ${target}`;
    case "org.member_removed":  return `${actor} removed ${target} from the organization`;
    case "org.invite_created":  return `${actor} invited ${target} to the organization`;
    case "user.org_assigned":   return `${actor} assigned ${target} to org #${d.org_id} as ${d.role}`;
    default: return e.event_type;
  }
}

function SystemEventsTab({ isAdmin }: { isAdmin: boolean }) {
  const [page, setPage] = useState(1);
  const [eventFilter, setEventFilter] = useState("all");
  const [actorSearch, setActorSearch] = useState("");
  const [debouncedActor, setDebouncedActor] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const buildKey = useCallback(() => {
    const params = new URLSearchParams({ page: page.toString(), limit: "50", event_type: eventFilter });
    if (debouncedActor.trim()) params.set("actor", debouncedActor.trim());
    return `/admin/events?${params}`;
  }, [page, eventFilter, debouncedActor]);

  const { data, isLoading } = useSWR<SystemEventsPage>(
    isAdmin ? buildKey() : null,
    (url: string) => api.get<SystemEventsPage>(url),
    { keepPreviousData: true },
  );

  function handleActorSearch(val: string) {
    setActorSearch(val);
    setPage(1);
    clearTimeout((handleActorSearch as unknown as { _t?: ReturnType<typeof setTimeout> })._t);
    (handleActorSearch as unknown as { _t?: ReturnType<typeof setTimeout> })._t = setTimeout(() => setDebouncedActor(val), 400);
  }

  const EVENT_TYPE_OPTIONS = [
    "all", "user.created", "user.registered", "user.deleted", "user.role_changed", "user.password_reset",
    "user.impersonated", "user.org_assigned",
    "guardrail.created", "guardrail.updated", "guardrail.deleted", "guardrail.toggled",
    "connection.created", "connection.updated", "connection.deleted", "connection.toggled", "connection.spend_reset",
    "org.created", "org.deleted", "org.member_removed", "org.invite_created",
  ];

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={actorSearch}
          onChange={(e) => handleActorSearch(e.target.value)}
          placeholder="Filter by actor…"
          className="rounded px-3 py-2 text-sm outline-none w-48"
          style={inputStyle}
        />
        <div className="relative">
          <select
            value={eventFilter}
            onChange={(e) => { setEventFilter(e.target.value); setPage(1); }}
            className="rounded px-3 py-2 text-sm outline-none appearance-none pr-7"
            style={inputStyle}
          >
            {EVENT_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>{t === "all" ? "All event types" : t}</option>
            ))}
          </select>
          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none text-xs">▾</span>
        </div>
        {data && (
          <p className="text-xs text-slate-600 font-mono ml-auto">
            {data.total.toLocaleString()} {data.total === 1 ? "event" : "events"}
          </p>
        )}
      </div>

      {/* Table */}
      <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5">
                {["Time", "Event", "Actor", "Target", "Summary", ""].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td colSpan={6} className="px-4 py-3">
                      <div className="h-3 rounded animate-pulse" style={{ background: "#111827" }} />
                    </td>
                  </tr>
                ))
              ) : !data || data.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-16 text-center text-xs text-slate-600 font-mono">
                    No system events recorded yet. Events will appear here as users make changes.
                  </td>
                </tr>
              ) : data.items.map((e) => {
                const style = EVENT_STYLES[e.event_type] ?? { background: "rgba(148,163,184,0.08)", color: "#94a3b8" };
                const isExpanded = expanded === e.id;
                return (
                  <>
                    <tr key={e.id}
                      onClick={() => setExpanded(isExpanded ? null : e.id)}
                      className="border-b border-white/5 cursor-pointer transition-colors"
                      style={{ background: isExpanded ? "rgba(20,184,166,0.02)" : undefined }}
                      onMouseEnter={(ev) => { if (!isExpanded) ev.currentTarget.style.background = "rgba(255,255,255,0.01)"; }}
                      onMouseLeave={(ev) => { if (!isExpanded) ev.currentTarget.style.background = ""; }}
                    >
                      <td className="px-4 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
                        {e.created_at ? format(new Date(e.created_at), "MM/dd HH:mm:ss") : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-mono px-2 py-0.5 rounded whitespace-nowrap" style={style}>
                          {e.event_type}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {e.actor_username ? (
                          <span className="text-xs font-mono text-white">{e.actor_username}</span>
                        ) : (
                          <span className="text-xs text-slate-700 font-mono">system</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {e.target_name ? (
                          <div>
                            <span className="text-xs text-slate-300">{e.target_name}</span>
                            {e.target_type && (
                              <span className="text-xs text-slate-700 font-mono ml-1.5">({e.target_type})</span>
                            )}
                          </div>
                        ) : <span className="text-slate-700 text-xs">—</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-400 max-w-xs truncate">
                        {eventSummary(e)}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-700 font-mono">{isExpanded ? "▲" : "▼"}</td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${e.id}-exp`} className="border-b border-white/5">
                        <td colSpan={6} className="px-4 pb-4 pt-1">
                          <div className="rounded border border-white/5 p-4 space-y-3" style={{ background: "#0A0F1F" }}>
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs font-mono">
                              <div>
                                <p className="text-slate-600 uppercase tracking-wider mb-1">Event ID</p>
                                <p className="text-slate-300">#{e.id}</p>
                              </div>
                              <div>
                                <p className="text-slate-600 uppercase tracking-wider mb-1">Actor</p>
                                <p className="text-slate-300">{e.actor_username ?? "—"}{e.actor_id ? ` (id:${e.actor_id})` : ""}</p>
                              </div>
                              <div>
                                <p className="text-slate-600 uppercase tracking-wider mb-1">Target</p>
                                <p className="text-slate-300">{e.target_name ?? "—"}{e.target_id ? ` (id:${e.target_id})` : ""}</p>
                              </div>
                              {e.ip_address && (
                                <div>
                                  <p className="text-slate-600 uppercase tracking-wider mb-1">IP Address</p>
                                  <p className="text-slate-300">{e.ip_address}</p>
                                </div>
                              )}
                              <div>
                                <p className="text-slate-600 uppercase tracking-wider mb-1">Timestamp</p>
                                <p className="text-slate-300">{e.created_at ? format(new Date(e.created_at), "yyyy-MM-dd HH:mm:ss 'UTC'") : "—"}</p>
                              </div>
                            </div>
                            {Object.keys(e.details).length > 0 && (
                              <div>
                                <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-2">Details</p>
                                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                  {Object.entries(e.details).map(([k, v]) => (
                                    <div key={k} className="rounded px-3 py-2 border border-white/5" style={{ background: "#0d1426" }}>
                                      <p className="text-xs text-slate-600 font-mono mb-0.5">{k}</p>
                                      <p className="text-xs text-slate-300 font-mono">{String(v)}</p>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
        {data && <Pagination page={page} total={data.total} limit={50} onPage={setPage} />}
      </div>
    </div>
  );
}

// ── Audits tab (scan logs sub-tab) ────────────────────────────────────────────

function AuditsTab({ isAdmin }: { isAdmin: boolean }) {
  const [subTab, setSubTab] = useState<"scan-logs" | "system-events">("scan-logs");
  const [page, setPage] = useState(1);
  const [dir, setDir] = useState("all");
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  const buildKey = useCallback(() => {
    const params = new URLSearchParams({ page: page.toString(), limit: "50", direction: dir, status });
    if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
    return `/admin/audit-logs?${params}`;
  }, [page, dir, status, debouncedSearch]);

  const { data, isLoading } = useSWR<AdminAuditPage>(
    isAdmin ? buildKey() : null,
    (url: string) => api.get<AdminAuditPage>(url),
    { keepPreviousData: true },
  );

  function handleSearch(val: string) {
    setSearch(val);
    setPage(1);
    // Simple debounce via timeout replacement
    const t = setTimeout(() => setDebouncedSearch(val), 400);
    return () => clearTimeout(t);
  }

  function applyFilter(key: "dir" | "status", val: string) {
    if (key === "dir") setDir(val);
    else setStatus(val);
    setPage(1);
  }

  const totalPages = data ? Math.ceil(data.total / 50) : 1;

  return (
    <div className="space-y-4">
      {/* Sub-tab bar */}
      <div className="flex gap-1 p-1 rounded w-fit" style={{ background: "#0A0F1F" }}>
        {(["scan-logs", "system-events"] as const).map((k) => (
          <button key={k} onClick={() => setSubTab(k)}
            className="px-4 py-1.5 rounded text-xs font-medium transition-colors"
            style={subTab === k ? { background: "#14B8A6", color: "#0A0F1F" } : { color: "#64748b" }}>
            {k === "scan-logs" ? "Scan Logs" : "System Events"}
          </button>
        ))}
      </div>

      {subTab === "scan-logs" && (
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <input
              value={search}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder="Search prompt text…"
              className="rounded px-3 py-2 text-sm outline-none w-64"
              style={inputStyle}
            />
            <div className="flex gap-1 p-1 rounded" style={{ background: "#0d1426" }}>
              {(["all", "input", "output"] as const).map((d) => (
                <button key={d} onClick={() => applyFilter("dir", d)}
                  className="px-3 py-1 rounded text-xs font-medium transition-colors capitalize"
                  style={dir === d ? { background: "#14B8A6", color: "#0A0F1F" } : { color: "#64748b" }}>
                  {d}
                </button>
              ))}
            </div>
            <div className="flex gap-1 p-1 rounded" style={{ background: "#0d1426" }}>
              {[{ v: "all", label: "All" }, { v: "pass", label: "Pass" }, { v: "block", label: "Block" }].map(({ v, label }) => (
                <button key={v} onClick={() => applyFilter("status", v)}
                  className="px-3 py-1 rounded text-xs font-medium transition-colors"
                  style={status === v ? { background: "#14B8A6", color: "#0A0F1F" } : { color: "#64748b" }}>
                  {label}
                </button>
              ))}
            </div>
            <button onClick={() => downloadCSV("/admin/export/audit-logs?limit=1000", "talix-audit-logs.csv")}
              className="text-xs px-3 py-1.5 rounded font-mono border border-white/10 text-slate-400 hover:text-white transition-colors">
              ↓ Export CSV
            </button>
            {data && (
              <p className="text-xs text-slate-600 font-mono ml-auto">
                {data.total.toLocaleString()} {data.total === 1 ? "entry" : "entries"}
                {data.total > 50 ? ` · page ${page} of ${totalPages}` : ""}
              </p>
            )}
          </div>

          {/* Table */}
          <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5">
                    {["#", "Time", "Dir", "Status", "Risk", "Via", "Violations", "Preview", "Cost", ""].map((h) => (
                      <th key={h} className="px-4 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {isLoading ? (
                    Array.from({ length: 8 }).map((_, i) => (
                      <tr key={i} className="border-b border-white/5">
                        <td colSpan={10} className="px-4 py-3">
                          <div className="h-3 rounded animate-pulse" style={{ background: "#111827" }} />
                        </td>
                      </tr>
                    ))
                  ) : !data || data.items.length === 0 ? (
                    <tr>
                      <td colSpan={10} className="px-4 py-16 text-center text-xs text-slate-600 font-mono">
                        No audit logs match the current filters.
                      </td>
                    </tr>
                  ) : (
                    data.items.map((entry) => <AuditRow key={entry.id} entry={entry} />)
                  )}
                </tbody>
              </table>
            </div>
            {data && <Pagination page={page} total={data.total} limit={50} onPage={setPage} />}
          </div>
        </div>
      )}

      {subTab === "system-events" && <SystemEventsTab isAdmin={isAdmin} />}
    </div>
  );
}

// ── Orgs tab (super admin) ────────────────────────────────────────────────────

interface OrgEntry {
  id: number; name: string; plan: string; created_at: string | null;
  owner_id: number | null; owner_username: string | null;
  member_count: number; team_count: number;
}

interface OrgTeam {
  id: number; name: string; created_by_username: string | null;
  created_at: string | null; member_count: number;
}

function OrgsTab() {
  const { data: orgs, isLoading, mutate } = useSWR<OrgEntry[]>(
    "/admin/orgs",
    (url: string) => api.get<OrgEntry[]>(url),
    { revalidateOnFocus: false },
  );

  const [showCreate, setShowCreate] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [expandedOrg, setExpandedOrg] = useState<number | null>(null);
  const [expandPanel, setExpandPanel] = useState<Record<number, "members" | "teams">>({});
  const [orgMembers, setOrgMembers] = useState<Record<number, { id: number; username: string; role: string; email: string | null }[]>>({});
  const [orgTeams, setOrgTeams] = useState<Record<number, OrgTeam[]>>({});
  const [planChangingId, setPlanChangingId] = useState<number | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(""); setCreating(true);
    try {
      await api.post("/admin/orgs", { name: newOrgName });
      setNewOrgName(""); setShowCreate(false);
      await mutate();
    } catch (err) { setCreateError(err instanceof Error ? err.message : "Failed"); }
    finally { setCreating(false); }
  }

  async function handleDelete(org: OrgEntry) {
    if (!confirm(`Delete organization "${org.name}" and remove all ${org.member_count} member assignments?`)) return;
    setDeletingId(org.id);
    try { await api.delete(`/admin/orgs/${org.id}`); await mutate(); }
    finally { setDeletingId(null); }
  }

  async function handleOrgPlanChange(org: OrgEntry, newPlan: string) {
    setPlanChangingId(org.id);
    try { await api.patch(`/admin/orgs/${org.id}/plan`, { plan: newPlan }); await mutate(); }
    finally { setPlanChangingId(null); }
  }

  async function toggleExpand(orgId: number, panel: "members" | "teams") {
    const isOpen = expandedOrg === orgId && expandPanel[orgId] === panel;
    if (isOpen) { setExpandedOrg(null); return; }
    setExpandedOrg(orgId);
    setExpandPanel((p) => ({ ...p, [orgId]: panel }));

    if (panel === "members" && !orgMembers[orgId]) {
      const members = await api.get<{ id: number; username: string; role: string; email: string | null }[]>(`/admin/orgs/${orgId}/members`);
      setOrgMembers((prev) => ({ ...prev, [orgId]: members }));
    }
    if (panel === "teams" && !orgTeams[orgId]) {
      const teams = await api.get<OrgTeam[]>(`/admin/orgs/${orgId}/teams`);
      setOrgTeams((prev) => ({ ...prev, [orgId]: teams }));
    }
  }

  const isOpen = (orgId: number, panel: "members" | "teams") =>
    expandedOrg === orgId && expandPanel[orgId] === panel;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">All Organizations</p>
        <button onClick={() => setShowCreate(!showCreate)}
          className="text-xs font-medium px-3 py-1.5 rounded transition-colors"
          style={showCreate ? { background: "rgba(255,255,255,0.05)", color: "#94a3b8" } : { background: "#14B8A6", color: "#0A0F1F" }}>
          {showCreate ? "✕ Cancel" : "+ New org"}
        </button>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate}
          className="rounded border p-4 flex items-end gap-3"
          style={{ background: "#0d1426", borderColor: "rgba(20,184,166,0.2)" }}>
          <div className="flex-1">
            <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Organization Name</label>
            <input value={newOrgName} onChange={(e) => setNewOrgName(e.target.value)}
              required placeholder="e.g. Acme Corp"
              className="w-full rounded px-3 py-2 text-sm outline-none"
              style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#e2e8f0" }} />
          </div>
          <button type="submit" disabled={creating}
            className="px-5 py-2 rounded text-sm font-medium disabled:opacity-50"
            style={{ background: "#14B8A6", color: "#0A0F1F" }}>
            {creating ? "Creating…" : "Create"}
          </button>
          {createError && <p className="text-xs text-red-400">{createError}</p>}
        </form>
      )}

      <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
        {isLoading ? (
          <div className="p-6 space-y-3">{Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-10 rounded animate-pulse" style={{ background: "#111827" }} />
          ))}</div>
        ) : !orgs || orgs.length === 0 ? (
          <div className="px-4 py-16 text-center text-xs text-slate-600 font-mono">
            No organizations yet. Create one to get started.
          </div>
        ) : orgs.map((org) => (
          <div key={org.id}>
            {/* Org row */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/5 hover:bg-white/[0.01] transition-colors">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                  style={{ background: "rgba(20,184,166,0.1)", color: "#14B8A6" }}>
                  {org.name[0]?.toUpperCase()}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-white truncate">{org.name}</p>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-slate-600 font-mono">
                      {org.member_count} member{org.member_count !== 1 ? "s" : ""}
                    </span>
                    <span className="text-xs font-mono px-1.5 py-0.5 rounded"
                      style={{ background: "rgba(99,102,241,0.1)", color: "#a5b4fc" }}>
                      {org.team_count} team{org.team_count !== 1 ? "s" : ""}
                    </span>
                    {org.owner_username && (
                      <span className="text-xs text-slate-600 font-mono">owner: {org.owner_username}</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-4">
                {/* Plan selector */}
                <div className="relative">
                  <select
                    value={org.plan ?? "free"}
                    onChange={(e) => handleOrgPlanChange(org, e.target.value)}
                    disabled={planChangingId === org.id}
                    className="text-xs rounded px-2 py-1 outline-none appearance-none pr-5 disabled:opacity-40"
                    style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#64748b", fontSize: "11px" }}
                  >
                    <option value="free">free</option>
                    <option value="pro">pro</option>
                    <option value="enterprise">enterprise</option>
                  </select>
                  <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none" style={{ fontSize: 9 }}>▾</span>
                </div>
                <button onClick={() => toggleExpand(org.id, "members")}
                  className="text-xs px-2.5 py-1 rounded border transition-colors"
                  style={isOpen(org.id, "members")
                    ? { borderColor: "rgba(20,184,166,0.4)", color: "#14B8A6" }
                    : { borderColor: "rgba(255,255,255,0.08)", color: "#64748b" }}>
                  Members {isOpen(org.id, "members") ? "▲" : "▼"}
                </button>
                <button onClick={() => toggleExpand(org.id, "teams")}
                  className="text-xs px-2.5 py-1 rounded border transition-colors"
                  style={isOpen(org.id, "teams")
                    ? { borderColor: "rgba(99,102,241,0.4)", color: "#a5b4fc" }
                    : { borderColor: "rgba(255,255,255,0.08)", color: "#64748b" }}>
                  Teams {isOpen(org.id, "teams") ? "▲" : "▼"}
                </button>
                <button onClick={() => handleDelete(org)} disabled={deletingId === org.id}
                  className="text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40"
                  style={{ borderColor: "rgba(248,113,113,0.2)", color: "#f87171" }}>
                  {deletingId === org.id ? "…" : "Delete"}
                </button>
              </div>
            </div>

            {/* Members panel */}
            {isOpen(org.id, "members") && (
              <div className="px-5 py-3 border-b border-white/5" style={{ background: "rgba(20,184,166,0.02)" }}>
                <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-2">Members</p>
                {!orgMembers[org.id] ? (
                  <p className="text-xs text-slate-600 font-mono">Loading…</p>
                ) : orgMembers[org.id].length === 0 ? (
                  <p className="text-xs text-slate-600 font-mono">No members yet.</p>
                ) : (
                  <div className="space-y-1.5">
                    {orgMembers[org.id].map((m) => (
                      <div key={m.id} className="flex items-center gap-3 text-xs">
                        <span className="font-mono text-white">{m.username}</span>
                        <span className="font-mono px-1.5 py-0.5 rounded"
                          style={m.role === "org_admin"
                            ? { background: "rgba(251,191,36,0.1)", color: "#fbbf24" }
                            : { background: "rgba(20,184,166,0.08)", color: "#14B8A6" }}>
                          {m.role === "org_admin" ? "Org Admin" : "Member"}
                        </span>
                        {m.email && <span className="text-slate-600">{m.email}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Teams panel */}
            {isOpen(org.id, "teams") && (
              <div className="px-5 py-3 border-b border-white/5" style={{ background: "rgba(99,102,241,0.02)" }}>
                <p className="text-xs font-mono uppercase tracking-wider mb-2" style={{ color: "#a5b4fc" }}>Teams</p>
                {!orgTeams[org.id] ? (
                  <p className="text-xs text-slate-600 font-mono">Loading…</p>
                ) : orgTeams[org.id].length === 0 ? (
                  <p className="text-xs text-slate-600 font-mono">No teams in this org yet.</p>
                ) : (
                  <div className="space-y-2">
                    {orgTeams[org.id].map((t) => (
                      <div key={t.id} className="flex items-center justify-between py-1.5 px-3 rounded"
                        style={{ background: "rgba(99,102,241,0.06)", border: "1px solid rgba(99,102,241,0.12)" }}>
                        <div className="flex items-center gap-2.5">
                          <div className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold shrink-0"
                            style={{ background: "rgba(99,102,241,0.2)", color: "#a5b4fc" }}>
                            {t.name[0]?.toUpperCase()}
                          </div>
                          <div>
                            <p className="text-xs font-medium text-white">{t.name}</p>
                            {t.created_by_username && (
                              <p className="text-xs text-slate-600 font-mono">created by @{t.created_by_username}</p>
                            )}
                          </div>
                        </div>
                        <span className="text-xs font-mono px-2 py-0.5 rounded"
                          style={{ background: "rgba(99,102,241,0.1)", color: "#a5b4fc" }}>
                          {t.member_count} member{t.member_count !== 1 ? "s" : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {orgs && orgs.length > 0 && (
          <div className="px-5 py-3 border-t border-white/5 flex items-center gap-4">
            <p className="text-xs text-slate-700 font-mono">
              {orgs.length} org{orgs.length !== 1 ? "s" : ""} · {orgs.reduce((s, o) => s + o.member_count, 0)} members · {orgs.reduce((s, o) => s + o.team_count, 0)} teams
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Access denied screen ──────────────────────────────────────────────────────

// ── CSV download helper ───────────────────────────────────────────────────────

async function downloadCSV(path: string, filename: string) {
  const Cookies = (await import("js-cookie")).default;
  const token = Cookies.get("token");
  const res = await fetch(`/api${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// ── Billing admin tab ─────────────────────────────────────────────────────────

function BillingAdminTab() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [markingPaid, setMarkingPaid] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newInv, setNewInv] = useState({ user_id: "", amount: "", currency: "USD", description: "", status: "open" });
  const [creating, setCreating] = useState(false);

  const { data: billing } = useSWR<BillingStats>(
    "/admin/billing/stats",
    () => api.get<BillingStats>("/admin/billing/stats"),
  );
  const { data: invoicePage, mutate: mutateInvoices } = useSWR<AdminInvoicePage>(
    `/admin/billing/invoices?status_filter=${statusFilter}&limit=50`,
    () => api.get<AdminInvoicePage>(`/admin/billing/invoices?status_filter=${statusFilter}&limit=50`),
  );

  const PLAN_COLOR: Record<string, string> = { free: "#64748b", pro: "#14B8A6", enterprise: "#a78bfa" };
  const STATUS_COLOR: Record<string, string> = { paid: "#14B8A6", open: "#fbbf24", failed: "#f87171", void: "#475569" };

  async function markPaid(inv: AdminInvoice) {
    setMarkingPaid(inv.id);
    try {
      await api.patch(`/billing/admin/invoices/${inv.id}`, { status: "paid" });
      await mutateInvoices();
    } finally { setMarkingPaid(null); }
  }

  async function handleCreate() {
    if (!newInv.user_id || !newInv.amount) return;
    setCreating(true);
    try {
      await api.post("/billing/admin/invoices", {
        user_id: parseInt(newInv.user_id),
        amount: parseFloat(newInv.amount),
        currency: newInv.currency,
        description: newInv.description || null,
        status: newInv.status,
      });
      await mutateInvoices();
      setShowCreate(false);
      setNewInv({ user_id: "", amount: "", currency: "USD", description: "", status: "open" });
    } finally { setCreating(false); }
  }

  return (
    <div className="space-y-6">
      {/* Revenue stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {!billing ? <Sk h="h-20" cols={4} /> : (
          <>
            <StatCard label="Est. MRR" value={`$${billing.mrr.toLocaleString()}`} color="#14B8A6" sub="based on Pro seats" />
            <StatCard label="Total Invoiced" value={`$${billing.total_invoiced.toFixed(2)}`} color="#e2e8f0" sub="all time" />
            <StatCard label="Total Paid" value={`$${billing.total_paid.toFixed(2)}`} color="#14B8A6" sub="collected" />
            <StatCard label="Open / Unpaid" value={`$${billing.total_open.toFixed(2)}`} color={billing.total_open > 0 ? "#fbbf24" : "#64748b"} sub="outstanding" />
          </>
        )}
      </div>

      {/* Plan distribution */}
      {billing && (
        <Section title="Plan Distribution">
          <div className="flex flex-wrap gap-4 px-1">
            {Object.entries(billing.plan_counts).map(([plan, count]) => (
              <div key={plan} className="rounded border border-white/5 px-5 py-4 flex items-center gap-4" style={{ background: "#0d1426" }}>
                <span className="text-xs font-mono px-2 py-0.5 rounded capitalize"
                  style={{ background: `${PLAN_COLOR[plan] || "#64748b"}18`, color: PLAN_COLOR[plan] || "#64748b" }}>
                  {plan}
                </span>
                <span className="text-2xl font-bold text-white">{count}</span>
                <span className="text-xs text-slate-600">users</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Invoice management */}
      <Section
        title="All Invoices"
        action={
          <div className="flex gap-2">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
              className="text-xs rounded px-2 py-1 outline-none" style={inputStyle}>
              {["all", "open", "paid", "failed", "void"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button onClick={() => setShowCreate(true)}
              className="text-xs px-3 py-1 rounded font-medium" style={{ background: "#14B8A6", color: "#0A0F1F" }}>
              + Create invoice
            </button>
          </div>
        }
      >
        {showCreate && (
          <div className="mx-5 mb-4 rounded border border-white/10 p-4 space-y-3" style={{ background: "#0A0F1F" }}>
            <p className="text-xs font-mono text-slate-400 uppercase tracking-wider">New invoice</p>
            <div className="grid grid-cols-2 gap-3">
              <input placeholder="User ID" value={newInv.user_id} onChange={(e) => setNewInv({ ...newInv, user_id: e.target.value })}
                className="rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
              <input placeholder="Amount (e.g. 129.00)" value={newInv.amount} onChange={(e) => setNewInv({ ...newInv, amount: e.target.value })}
                className="rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
              <input placeholder="Description" value={newInv.description} onChange={(e) => setNewInv({ ...newInv, description: e.target.value })}
                className="rounded px-3 py-2 text-sm outline-none col-span-2" style={inputStyle} />
              <select value={newInv.status} onChange={(e) => setNewInv({ ...newInv, status: e.target.value })}
                className="rounded px-3 py-2 text-sm outline-none" style={inputStyle}>
                {["open", "paid", "failed", "void"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={newInv.currency} onChange={(e) => setNewInv({ ...newInv, currency: e.target.value })}
                className="rounded px-3 py-2 text-sm outline-none" style={inputStyle}>
                {["USD", "EUR", "GBP"].map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="flex gap-2">
              <button onClick={handleCreate} disabled={creating}
                className="text-sm px-4 py-2 rounded font-medium disabled:opacity-50" style={{ background: "#14B8A6", color: "#0A0F1F" }}>
                {creating ? "Creating…" : "Create"}
              </button>
              <button onClick={() => setShowCreate(false)} className="text-sm px-4 py-2 rounded text-slate-500 hover:text-white transition-colors">
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5">
                {["Invoice #", "User", "Plan", "Amount", "Status", "Created", ""].map((h) => (
                  <th key={h} className="text-left px-5 py-2.5 text-xs text-slate-600 font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!invoicePage ? (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-slate-600 text-xs">Loading…</td></tr>
              ) : invoicePage.items.length === 0 ? (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-slate-600 text-xs">No invoices found.</td></tr>
              ) : invoicePage.items.map((inv) => (
                <tr key={inv.id} className="border-b border-white/5 hover:bg-white/2 transition-colors">
                  <td className="px-5 py-3 font-mono text-xs text-slate-400">{inv.invoice_number}</td>
                  <td className="px-5 py-3 text-slate-300 text-xs">{inv.username}</td>
                  <td className="px-5 py-3">
                    <span className="text-xs font-mono px-1.5 py-0.5 rounded capitalize"
                      style={{ background: `${PLAN_COLOR[inv.user_plan]}18`, color: PLAN_COLOR[inv.user_plan] || "#64748b" }}>
                      {inv.user_plan}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-white font-medium text-xs">${inv.amount.toFixed(2)} {inv.currency}</td>
                  <td className="px-5 py-3">
                    <span className="text-xs font-mono px-1.5 py-0.5 rounded capitalize"
                      style={{ background: `${STATUS_COLOR[inv.status] || "#64748b"}18`, color: STATUS_COLOR[inv.status] || "#64748b" }}>
                      {inv.status}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-600 text-xs font-mono">
                    {inv.created_at ? format(new Date(inv.created_at), "MMM d, yyyy") : "—"}
                  </td>
                  <td className="px-5 py-3">
                    {inv.status === "open" && (
                      <button onClick={() => markPaid(inv)} disabled={markingPaid === inv.id}
                        className="text-xs px-2.5 py-1 rounded font-mono disabled:opacity-50"
                        style={{ background: "rgba(20,184,166,0.1)", color: "#14B8A6" }}>
                        {markingPaid === inv.id ? "…" : "Mark paid"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {invoicePage && (
          <p className="px-5 py-3 text-xs text-slate-700 font-mono border-t border-white/5">
            {invoicePage.total} invoice{invoicePage.total !== 1 ? "s" : ""} total
          </p>
        )}
      </Section>
    </div>
  );
}

// ── Settings tab ──────────────────────────────────────────────────────────────

function SettingsTab({ platformSettings, mutatePlatform }: {
  platformSettings: Record<string, string> | undefined;
  mutatePlatform: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState<Record<string, string>>({
    company_name: "", maintenance_mode: "false", maintenance_message: "",
    signup_enabled: "true", chatbot_enabled: "true",
    smtp_host: "", smtp_port: "587",
    smtp_user: "", smtp_password: "", smtp_from: "", smtp_tls: "true",
  });

  useEffect(() => {
    if (platformSettings) setSettings((prev) => ({ ...prev, ...platformSettings }));
  }, [platformSettings]);

  function set(key: string, value: string) {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await api.put("/admin/platform", settings);
      mutatePlatform();
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally { setSaving(false); }
  }

  const isMaintenance = settings.maintenance_mode === "true";
  const signupEnabled = settings.signup_enabled !== "false";
  const chatbotEnabled = settings.chatbot_enabled !== "false";

  return (
    <div className="space-y-6 max-w-2xl">

      {/* General */}
      <Section title="General">
        <div className="p-5 space-y-4">
          <div>
            <label className="block text-xs text-slate-500 font-mono uppercase tracking-wider mb-1">Company Name</label>
            <p className="text-xs text-slate-600 mb-2">Shown in the sidebar for all users.</p>
            <input value={settings.company_name} onChange={(e) => set("company_name", e.target.value)}
              placeholder="e.g. Acme Corp" className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
          </div>
          <div className="flex items-center justify-between py-2">
            <div>
              <p className="text-sm text-white font-medium">Allow new registrations</p>
              <p className="text-xs text-slate-500 mt-0.5">When off, the /register endpoint returns 403.</p>
            </div>
            <button onClick={() => set("signup_enabled", signupEnabled ? "false" : "true")}
              className="relative w-10 h-5 rounded-full transition-colors shrink-0"
              style={{ background: signupEnabled ? "#14B8A6" : "rgba(255,255,255,0.1)" }}>
              <span className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform"
                style={{ transform: signupEnabled ? "translateX(20px)" : "translateX(2px)" }} />
            </button>
          </div>
        </div>
      </Section>

      {/* Chatbot */}
      <Section title="Chatbot">
        <div className="p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-white font-medium">Chatbot active</p>
              <p className="text-xs text-slate-500 mt-0.5">When off, the chatbot returns HTTP 503 and shows an offline message to users.</p>
            </div>
            <button onClick={() => set("chatbot_enabled", chatbotEnabled ? "false" : "true")}
              className="relative w-10 h-5 rounded-full transition-colors shrink-0"
              style={{ background: chatbotEnabled ? "#14B8A6" : "rgba(255,255,255,0.1)" }}>
              <span className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform"
                style={{ transform: chatbotEnabled ? "translateX(20px)" : "translateX(2px)" }} />
            </button>
          </div>
          {!chatbotEnabled && (
            <div className="rounded border border-amber-500/20 px-4 py-3 text-xs text-amber-400 bg-amber-500/5">
              Chatbot is OFF — the /chat endpoint returns 503 until re-enabled.
            </div>
          )}
        </div>
      </Section>

      {/* Maintenance mode */}
      <Section title="Maintenance Mode">
        <div className="p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-white font-medium">Enable maintenance mode</p>
              <p className="text-xs text-slate-500 mt-0.5">Returns HTTP 503 for all non-admin API requests.</p>
            </div>
            <button onClick={() => set("maintenance_mode", isMaintenance ? "false" : "true")}
              className="relative w-10 h-5 rounded-full transition-colors shrink-0"
              style={{ background: isMaintenance ? "#f87171" : "rgba(255,255,255,0.1)" }}>
              <span className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform"
                style={{ transform: isMaintenance ? "translateX(20px)" : "translateX(2px)" }} />
            </button>
          </div>
          {isMaintenance && (
            <div className="rounded border border-red-500/20 px-4 py-3 text-xs text-red-400 bg-red-500/5">
              Maintenance mode is ON — users cannot access the API right now.
            </div>
          )}
          <div>
            <label className="block text-xs text-slate-500 font-mono uppercase tracking-wider mb-1">Custom message</label>
            <input value={settings.maintenance_message} onChange={(e) => set("maintenance_message", e.target.value)}
              placeholder="System maintenance in progress. Please try again shortly."
              className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
          </div>
        </div>
      </Section>

      {/* SMTP */}
      <Section title="Email / SMTP">
        <div className="p-5 space-y-3">
          <p className="text-xs text-slate-600">Used for password reset and invite emails. Leave blank to disable email.</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-500 font-mono mb-1">SMTP Host</label>
              <input value={settings.smtp_host} onChange={(e) => set("smtp_host", e.target.value)}
                placeholder="smtp.example.com" className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
            </div>
            <div>
              <label className="block text-xs text-slate-500 font-mono mb-1">Port</label>
              <input value={settings.smtp_port} onChange={(e) => set("smtp_port", e.target.value)}
                placeholder="587" className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
            </div>
            <div>
              <label className="block text-xs text-slate-500 font-mono mb-1">Username</label>
              <input value={settings.smtp_user} onChange={(e) => set("smtp_user", e.target.value)}
                placeholder="apikey" className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
            </div>
            <div>
              <label className="block text-xs text-slate-500 font-mono mb-1">Password / API Key</label>
              <input type="password" value={settings.smtp_password} onChange={(e) => set("smtp_password", e.target.value)}
                placeholder="••••••••" className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
            </div>
            <div>
              <label className="block text-xs text-slate-500 font-mono mb-1">From address</label>
              <input value={settings.smtp_from} onChange={(e) => set("smtp_from", e.target.value)}
                placeholder="noreply@yourapp.com" className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
            </div>
            <div className="flex items-center gap-3 pt-5">
              <button onClick={() => set("smtp_tls", settings.smtp_tls === "true" ? "false" : "true")}
                className="relative w-10 h-5 rounded-full transition-colors shrink-0"
                style={{ background: settings.smtp_tls === "true" ? "#14B8A6" : "rgba(255,255,255,0.1)" }}>
                <span className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform"
                  style={{ transform: settings.smtp_tls === "true" ? "translateX(20px)" : "translateX(2px)" }} />
              </button>
              <span className="text-xs text-slate-400">Use TLS (STARTTLS)</span>
            </div>
          </div>
        </div>
      </Section>

      {/* Save */}
      <div className="flex items-center gap-4">
        <button onClick={handleSave} disabled={saving}
          className="px-6 py-2.5 rounded font-medium text-sm disabled:opacity-50 transition-colors"
          style={{ background: "#14B8A6", color: "#0A0F1F" }}>
          {saving ? "Saving…" : "Save all settings"}
        </button>
        {saved && <p className="text-xs font-mono" style={{ color: "#14B8A6" }}>✓ Settings saved</p>}
      </div>
    </div>
  );
}

function AccessDenied() {
  return (
    <div className="flex flex-col items-center justify-center py-32 space-y-4">
      <div className="w-14 h-14 rounded-full flex items-center justify-center" style={{ background: "rgba(248,113,113,0.1)" }}>
        <svg className="w-7 h-7" style={{ color: "#f87171" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
      </div>
      <p className="text-white font-semibold">Administrator access required</p>
      <p className="text-xs text-slate-500">This page is only accessible to admin accounts.</p>
      <a href="/dashboard" className="text-xs font-mono mt-2" style={{ color: "#14B8A6" }}>← Back to dashboard</a>
    </div>
  );
}

// ── Activity Tab ──────────────────────────────────────────────────────────────

function _timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

function _fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function ActivityScannerRows({ entry }: { entry: ActivityEntry }) {
  const results = entry.scanner_results ?? {};
  const pairs = Object.entries(results).sort(([, a], [, b]) => b - a);
  if (!pairs.length) return <p className="text-xs text-slate-600 italic">No scanner results.</p>;
  return (
    <div className="space-y-2">
      {pairs.map(([name, score]) => {
        const isViol = entry.violation_scanners.includes(name);
        const pct = Math.min(Math.round(score * 100), 100);
        const color = isViol ? "#f87171" : score > 0.5 ? "#fbbf24" : "#14B8A6";
        return (
          <div key={name}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-mono" style={{ color: isViol ? "#f87171" : "#94a3b8" }}>{name}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono" style={{ color }}>{score.toFixed(3)}</span>
                <span className="text-xs font-mono px-1.5 py-0.5 rounded"
                  style={isViol ? { background: "rgba(248,113,113,0.12)", color: "#f87171" } : { background: "rgba(20,184,166,0.08)", color: "#14B8A6" }}>
                  {isViol ? "blocked" : "pass"}
                </span>
              </div>
            </div>
            <div className="h-1 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
              <div className="h-1 rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ActivityFeed({
  entries,
  selected,
  onSelect,
  newIds,
}: {
  entries: ActivityEntry[];
  selected: ActivityEntry | null;
  onSelect: (e: ActivityEntry) => void;
  newIds: Set<number>;
}) {
  const passCount = entries.filter((e) => e.is_valid).length;
  const blockCount = entries.filter((e) => !e.is_valid).length;

  return (
    <div className="rounded border overflow-hidden" style={{ background: "#0d1426", borderColor: "rgba(255,255,255,0.05)" }}>
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: "rgba(255,255,255,0.05)" }}>
        <p className="text-xs font-mono text-slate-400 uppercase tracking-wider">Requests</p>
        <div className="flex items-center gap-3">
          {entries.length > 0 && (
            <>
              <span className="text-xs font-mono" style={{ color: "#14B8A6" }}>{passCount} pass</span>
              <span className="text-xs font-mono" style={{ color: "#f87171" }}>{blockCount} blocked</span>
            </>
          )}
          <span className="text-xs font-mono text-slate-700">last {entries.length}</span>
        </div>
      </div>
      {entries.length === 0 ? (
        <div className="py-16 flex flex-col items-center justify-center text-center space-y-3">
          <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: "#14B8A6" }} />
          <p className="text-sm text-slate-500">No scans yet — waiting for traffic.</p>
        </div>
      ) : (
        <div className="divide-y" style={{ borderColor: "rgba(255,255,255,0.04)" }}>
          {entries.map((entry) => {
            const isNew = newIds.has(entry.id);
            const isSel = selected?.id === entry.id;
            return (
              <button key={entry.id} onClick={() => onSelect(entry)} className="w-full text-left px-4 py-3 transition-all"
                style={{
                  background: isNew ? "rgba(20,184,166,0.06)" : isSel ? "rgba(255,255,255,0.03)" : "transparent",
                  borderLeft: isSel ? "2px solid #14B8A6" : "2px solid transparent",
                }}>
                <div className="flex items-center gap-3">
                  <span className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ background: entry.is_valid ? "#14B8A6" : "#f87171" }} />
                  <span className="text-xs font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{
                      background: entry.direction === "input" ? "rgba(167,139,250,0.1)" : "rgba(251,191,36,0.1)",
                      color: entry.direction === "input" ? "#a78bfa" : "#fbbf24",
                    }}>
                    {entry.direction}
                  </span>
                  <span className="text-xs font-mono shrink-0"
                    style={{ color: entry.is_valid ? "#14B8A6" : "#f87171" }}>
                    {entry.is_valid ? "pass" : "blocked"}
                  </span>
                  {entry.violation_scanners.length > 0 && (
                    <span className="text-xs text-slate-600 truncate min-w-0">
                      {entry.violation_scanners.join(", ")}
                    </span>
                  )}
                  <span className="text-xs font-mono text-slate-700 ml-auto shrink-0">
                    {_fmtTime(entry.created_at)}
                  </span>
                </div>
                {(entry.connection_name || entry.ip_address) && (
                  <p className="text-xs text-slate-700 font-mono mt-1 pl-4 truncate">
                    {entry.connection_name ?? entry.ip_address}
                    {entry.connection_environment ? ` · ${entry.connection_environment}` : ""}
                  </p>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ActivityDetailPanel({ selected }: { selected: ActivityEntry | null }) {
  if (!selected) {
    return (
      <div className="rounded border p-12 flex items-center justify-center"
        style={{ background: "#0d1426", borderColor: "rgba(255,255,255,0.05)" }}>
        <p className="text-sm text-slate-500">Select a request from the feed.</p>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="rounded border px-5 py-4"
        style={{
          background: "#0d1426",
          borderColor: selected.is_valid ? "rgba(20,184,166,0.2)" : "rgba(248,113,113,0.25)",
        }}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono font-bold px-2.5 py-1 rounded"
              style={selected.is_valid
                ? { background: "rgba(20,184,166,0.1)", color: "#14B8A6" }
                : { background: "rgba(248,113,113,0.1)", color: "#f87171" }}>
              {selected.is_valid ? "✓ PASS" : "✗ BLOCKED"}
            </span>
            <span className="text-xs font-mono px-2 py-0.5 rounded"
              style={{
                background: selected.direction === "input" ? "rgba(167,139,250,0.1)" : "rgba(251,191,36,0.1)",
                color: selected.direction === "input" ? "#a78bfa" : "#fbbf24",
              }}>
              {selected.direction === "input" ? "POST /scan/prompt" : "POST /scan/output"}
            </span>
          </div>
          <span className="text-xs font-mono text-slate-600">{_timeAgo(selected.created_at)}</span>
        </div>
        <div className="flex flex-wrap gap-3 text-xs font-mono text-slate-600 mt-2">
          {selected.connection_name && <span>conn: {selected.connection_name}</span>}
          {selected.connection_environment && <span>env: {selected.connection_environment}</span>}
          {selected.ip_address && <span>ip: {selected.ip_address}</span>}
          {selected.max_risk_score > 0 && (
            <span style={{ color: selected.max_risk_score > 0.7 ? "#f87171" : "#fbbf24" }}>
              risk: {selected.max_risk_score.toFixed(3)}
            </span>
          )}
        </div>
        {selected.preview && (
          <div className="mt-3 px-3 py-2 rounded text-xs font-mono text-slate-400"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
            {selected.preview}{selected.preview.length >= 80 ? "…" : ""}
          </div>
        )}
      </div>

      <div className="rounded border p-4 space-y-4"
        style={{ background: "#0d1426", borderColor: "rgba(255,255,255,0.05)" }}>
        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500 uppercase tracking-wider font-mono">Scanner chain</p>
          <p className="text-xs font-mono text-slate-600">
            {Object.keys(selected.scanner_results ?? {}).length} ran
          </p>
        </div>
        <ActivityScannerRows entry={selected} />
      </div>

      {!selected.is_valid && selected.violation_scanners.length > 0 && (
        <div className="rounded border px-4 py-3 text-xs font-mono"
          style={{ background: "rgba(248,113,113,0.04)", borderColor: "rgba(248,113,113,0.15)", color: "#f87171" }}>
          Blocked by: <span className="font-bold">{selected.violation_scanners.join(", ")}</span>
        </div>
      )}
    </div>
  );
}

function ActivityTab({ entries }: { entries: ActivityEntry[] }) {
  const [subView, setSubView] = useState<"feed" | "connections">("feed");
  const [selected, setSelected] = useState<ActivityEntry | null>(null);
  const [connFilter, setConnFilter] = useState<string | null>(null);
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const prevTopId = useRef<number | null>(null);

  useEffect(() => {
    if (!entries.length) return;
    const top = entries[0];
    if (top.id !== prevTopId.current) {
      const incoming = entries
        .filter((e) => prevTopId.current === null || e.id > prevTopId.current)
        .map((e) => e.id);
      if (incoming.length) {
        setNewIds(new Set(incoming));
        setTimeout(() => setNewIds(new Set()), 1200);
      }
      prevTopId.current = top.id;
      setSelected((prev) => (prev === null ? top : prev));
    }
  }, [entries]);

  // Build connection summary from entries
  const connMap = new Map<string, { name: string; env: string | null; total: number; violations: number; lastAt: string | null }>();
  for (const e of entries) {
    const key = e.connection_name ?? e.ip_address ?? "Direct";
    const existing = connMap.get(key);
    if (existing) {
      existing.total += 1;
      if (!e.is_valid) existing.violations += 1;
      if (e.created_at && (!existing.lastAt || e.created_at > existing.lastAt)) existing.lastAt = e.created_at;
    } else {
      connMap.set(key, {
        name: e.connection_name ?? e.ip_address ?? "Direct",
        env: e.connection_environment,
        total: 1,
        violations: e.is_valid ? 0 : 1,
        lastAt: e.created_at,
      });
    }
  }
  const connList = Array.from(connMap.values()).sort((a, b) => b.total - a.total);

  const filteredEntries = connFilter
    ? entries.filter((e) => (e.connection_name ?? e.ip_address ?? "Direct") === connFilter)
    : entries;

  return (
    <div className="space-y-4">
      {/* Header + sub-tabs */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: "#14B8A6" }} />
          <p className="text-xs font-mono text-slate-500 uppercase tracking-wider">Live request monitor</p>
        </div>
        <div className="flex items-center gap-1 ml-4">
          {(["feed", "connections"] as const).map((v) => (
            <button key={v} onClick={() => { setSubView(v); setConnFilter(null); setSelected(null); }}
              className="px-3 py-1.5 text-xs font-medium rounded transition-colors capitalize"
              style={subView === v
                ? { background: "rgba(20,184,166,0.1)", color: "#14B8A6" }
                : { color: "#475569" }}>
              {v === "connections" ? "By Connection" : "Feed"}
            </button>
          ))}
        </div>
        <span className="text-xs font-mono text-slate-700 ml-auto">auto-refreshes every 3s</span>
      </div>

      {/* Feed view */}
      {subView === "feed" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
          <ActivityFeed entries={filteredEntries} selected={selected} onSelect={setSelected} newIds={newIds} />
          <div className="sticky top-24">
            <ActivityDetailPanel selected={selected} />
          </div>
        </div>
      )}

      {/* Connections view */}
      {subView === "connections" && !connFilter && (
        <div className="rounded border overflow-hidden" style={{ background: "#0d1426", borderColor: "rgba(255,255,255,0.05)" }}>
          <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: "rgba(255,255,255,0.05)" }}>
            <p className="text-xs font-mono text-slate-400 uppercase tracking-wider">Connections</p>
            <span className="text-xs font-mono text-slate-700">{connList.length} active in last 30 scans</span>
          </div>
          {connList.length === 0 ? (
            <div className="py-12 flex items-center justify-center">
              <p className="text-sm text-slate-500">No data yet.</p>
            </div>
          ) : (
            <div className="divide-y" style={{ borderColor: "rgba(255,255,255,0.04)" }}>
              {connList.map((conn) => (
                <button key={conn.name} onClick={() => { setConnFilter(conn.name); setSelected(null); }}
                  className="w-full text-left px-4 py-4 hover:bg-white/[0.02] transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: conn.violations > 0 ? "#f87171" : "#14B8A6" }} />
                      <div className="min-w-0">
                        <p className="text-sm text-slate-200 font-medium truncate">{conn.name}</p>
                        {conn.env && (
                          <p className="text-xs font-mono text-slate-600 mt-0.5">{conn.env}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-4 shrink-0 ml-4">
                      <div className="text-right">
                        <p className="text-xs font-mono text-slate-400">{conn.total} req</p>
                        {conn.violations > 0 && (
                          <p className="text-xs font-mono" style={{ color: "#f87171" }}>{conn.violations} blocked</p>
                        )}
                      </div>
                      <div className="text-right">
                        <p className="text-xs font-mono text-slate-700">{_timeAgo(conn.lastAt)}</p>
                      </div>
                      <span className="text-slate-700">›</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Connection drill-down */}
      {subView === "connections" && connFilter && (
        <div className="space-y-3">
          <button onClick={() => { setConnFilter(null); setSelected(null); }}
            className="flex items-center gap-2 text-xs font-mono transition-colors"
            style={{ color: "#14B8A6" }}>
            ← Back to connections
          </button>
          <p className="text-sm font-medium text-white">{connFilter}</p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
            <ActivityFeed entries={filteredEntries} selected={selected} onSelect={setSelected} newIds={newIds} />
            <div className="sticky top-24">
              <ActivityDetailPanel selected={selected} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS: { key: AdminTab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "users", label: "Users" },
  { key: "connections", label: "Connections" },
  { key: "guardrails", label: "Guardrails" },
  { key: "audits", label: "Audits" },
  { key: "activity", label: "Activity" },
  { key: "orgs", label: "Organizations" },
  { key: "billing", label: "Billing" },
  { key: "settings", label: "Settings" },
];

export default function AdminPage() {
  const [tab, setTab] = useState<AdminTab>("overview");
  const router = useRouter();

  const { data: me, isLoading: meLoading } = useSWR<Me>(
    "/auth/me", () => api.get<Me>("/auth/me"), { revalidateOnFocus: false },
  );

  const isAdmin = me?.role === "admin";

  const { data: stats } = useSWR<AdminStats>(
    isAdmin ? "/admin/stats" : null,
    () => api.get<AdminStats>("/admin/stats"),
  );
  const { data: users, mutate: mutateUsers } = useSWR<AdminUser[]>(
    isAdmin && tab === "users" ? "/admin/users" : null,
    () => api.get<AdminUser[]>("/admin/users"),
  );
  const { data: connections } = useSWR<AdminConnection[]>(
    isAdmin && tab === "connections" ? "/admin/connections" : null,
    () => api.get<AdminConnection[]>("/admin/connections"),
  );
  const { data: activity } = useSWR<ActivityEntry[]>(
    isAdmin && tab === "overview" ? "/admin/activity?limit=15" : null,
    () => api.get<ActivityEntry[]>("/admin/activity?limit=15"),
  );
  const { data: guardrails, mutate: mutateGuardrails } = useSWR<GuardrailEntry[]>(
    isAdmin && (tab === "guardrails" || tab === "overview") ? "/admin/guardrails" : null,
    () => api.get<GuardrailEntry[]>("/admin/guardrails"),
  );
  const { data: topViolations } = useSWR<TopViolation[]>(
    isAdmin && tab === "overview" ? "/admin/top-violations" : null,
    () => api.get<TopViolation[]>("/admin/top-violations"),
  );
  const { data: liveActivity } = useSWR<ActivityEntry[]>(
    isAdmin && tab === "activity" ? "/admin/activity?limit=30" : null,
    () => api.get<ActivityEntry[]>("/admin/activity?limit=30"),
    { refreshInterval: 3000 },
  );

  const { data: adminOrgs } = useSWR<OrgEntry[]>(
    isAdmin && tab === "users" ? "/admin/orgs" : null,
    () => api.get<OrgEntry[]>("/admin/orgs"),
    { revalidateOnFocus: false },
  );

  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [resetPwTarget, setResetPwTarget] = useState<AdminUser | null>(null);
  const [assignOrgTarget, setAssignOrgTarget] = useState<AdminUser | null>(null);
  const [roleLoading, setRoleLoading] = useState<number | null>(null);
  const [roleFilter, setRoleFilter] = useState("");
  const [toggling, setToggling] = useState<number | null>(null);

  const { data: platformSettings, mutate: mutatePlatform } = useSWR<Record<string, string>>(
    isAdmin ? "/admin/platform" : null,
    () => api.get<Record<string, string>>("/admin/platform"),
    { revalidateOnFocus: false },
  );


  async function handleRoleChange(user: AdminUser, newRole: string) {
    setRoleLoading(user.id);
    try { await api.patch(`/admin/users/${user.id}/role`, { role: newRole }); await mutateUsers(); }
    finally { setRoleLoading(null); }
  }

  async function handlePlanChange(user: AdminUser, newPlan: string) {
    setRoleLoading(user.id);
    try { await api.patch(`/admin/users/${user.id}/plan`, { plan: newPlan }); await mutateUsers(); }
    finally { setRoleLoading(null); }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try { await api.delete(`/admin/users/${deleteTarget.id}`); await mutateUsers(); }
    finally { setDeleteTarget(null); }
  }

  async function handleToggleGuardrail(id: number) {
    setToggling(id);
    try { await api.patch(`/admin/guardrails/${id}/toggle`); await mutateGuardrails(); }
    finally { setToggling(null); }
  }

  async function handleImpersonate(user: AdminUser) {
    try {
      const result = await api.post<{ access_token: string; username: string }>(`/admin/users/${user.id}/impersonate`, {});
      const currentToken = Cookies.get("token");
      if (currentToken) {
        Cookies.set("admin_token", currentToken, { expires: 1 });
      }
      Cookies.set("impersonating_user", result.username, { expires: 1 });
      Cookies.set("token", result.access_token, { expires: 1 });
      router.push("/dashboard");
      router.refresh();
    } catch {
      // silently ignore — user will see no change
    }
  }

  if (meLoading) return <div className="h-64 rounded animate-pulse" style={{ background: "#0d1426" }} />;
  if (!isAdmin) return <AccessDenied />;

  const filteredUsers = users?.filter((u) => roleFilter ? u.role === roleFilter : true);
  const maxViol = topViolations?.[0]?.count ?? 1;

  return (
    <div className="space-y-6 max-w-6xl">

      {/* ── Tab navigation ─────────────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-white/5 pb-0">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className="px-4 py-2.5 text-sm font-medium transition-colors relative"
            style={tab === t.key ? { color: "#14B8A6" } : { color: "#64748b" }}
          >
            {t.label}
            {tab === t.key && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t" style={{ background: "#14B8A6" }} />
            )}
          </button>
        ))}
      </div>

      {/* ── Overview ───────────────────────────────────────────────── */}
      {tab === "overview" && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
            {!stats ? <Sk h="h-20" cols={10} /> : (
              <>
                <StatCard label="Total Users" value={stats.total_users.toString()} color="#e2e8f0"
                  sub={`${stats.new_users_week} new this week`} />
                <StatCard label="Admins / Viewers" value={`${stats.admin_users} / ${stats.viewer_users}`}
                  color="#f87171" sub="role split" />
                <StatCard label="Platform Scans" value={stats.total_scans.toLocaleString()} color="#e2e8f0"
                  sub={`${stats.scans_today.toLocaleString()} today`} />
                <StatCard label="Pass Rate" value={`${stats.pass_rate.toFixed(1)}%`}
                  color={stats.pass_rate >= 95 ? "#14B8A6" : stats.pass_rate >= 80 ? "#fbbf24" : "#f87171"}
                  sub={`${stats.pass_rate_today.toFixed(1)}% today`} />
                <StatCard label="Violations" value={stats.total_violations.toLocaleString()}
                  color={stats.total_violations > 0 ? "#f87171" : "#14B8A6"}
                  sub={`${stats.violations_today} today`} />
                <StatCard label="Active Guardrails" value={`${stats.active_guardrails} / ${stats.total_guardrails}`}
                  color="#14B8A6" sub="scanning now" />
                <StatCard label="API Connections" value={stats.total_connections.toString()}
                  color={stats.blocked_connections > 0 ? "#f87171" : "#14B8A6"}
                  sub={stats.blocked_connections > 0 ? `${stats.blocked_connections} blocked` : "all active"}
                  warn={stats.blocked_connections > 0} />
                <StatCard label="Month Spend" value={`$${stats.total_month_spend.toFixed(2)}`}
                  color="#a78bfa" sub="across all connections" />
                <StatCard label="New Users / Week" value={stats.new_users_week.toString()}
                  color="#fbbf24" sub="registrations" />
                <StatCard label="Platform Health"
                  value={stats.pass_rate >= 95 ? "Good" : stats.pass_rate >= 80 ? "Degraded" : "Poor"}
                  color={stats.pass_rate >= 95 ? "#14B8A6" : stats.pass_rate >= 80 ? "#fbbf24" : "#f87171"}
                  sub="based on pass rate" />
              </>
            )}
          </div>

          {/* Violation bars + system status */}
          {stats && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                { label: "Violations Today", big: stats.violations_today, total: stats.scans_today, color: stats.violations_today > 0 ? "#f87171" : "#14B8A6" },
                { label: "All-Time Violations", big: stats.total_violations, total: stats.total_scans, color: "#fbbf24" },
              ].map(({ label, big, total, color }) => (
                <div key={label} className="rounded border border-white/5 px-5 py-4" style={{ background: "#0d1426" }}>
                  <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-3">{label}</p>
                  <div className="flex items-end gap-2">
                    <p className="text-3xl font-bold" style={{ color }}>{big.toLocaleString()}</p>
                    <p className="text-xs text-slate-600 pb-1 font-mono">of {total.toLocaleString()} scans</p>
                  </div>
                  <div className="mt-3 h-1.5 rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
                    <div className="h-1.5 rounded-full transition-all"
                      style={{ width: `${total > 0 ? Math.min((big / total) * 100, 100) : 0}%`, background: color }} />
                  </div>
                </div>
              ))}
              <div className="rounded border border-white/5 px-5 py-4" style={{ background: "#0d1426" }}>
                <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-4">System Status</p>
                <div className="space-y-3">
                  {[
                    { label: "Guardrail coverage", val: stats.active_guardrails > 0 ? "Active" : "None active", color: stats.active_guardrails > 0 ? "#14B8A6" : "#f87171" },
                    { label: "API connections", val: stats.blocked_connections > 0 ? `${stats.blocked_connections} blocked` : "All active", color: stats.blocked_connections > 0 ? "#f87171" : "#14B8A6" },
                    { label: "Platform health", val: stats.pass_rate >= 95 ? "Good" : stats.pass_rate >= 80 ? "Degraded" : "Poor", color: stats.pass_rate >= 95 ? "#14B8A6" : stats.pass_rate >= 80 ? "#fbbf24" : "#f87171" },
                    { label: "Month spend", val: `$${stats.total_month_spend.toFixed(2)}`, color: "#a78bfa" },
                  ].map(({ label, val, color }) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">{label}</span>
                      <span className="text-xs font-mono font-semibold" style={{ color }}>{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Blocked connections alert */}
          {stats && stats.blocked_connections > 0 && (
            <div className="rounded border-l-2 px-4 py-3 flex items-start gap-3"
              style={{ background: "rgba(248,113,113,0.05)", borderColor: "#f87171" }}>
              <svg className="w-4 h-4 shrink-0 mt-0.5" style={{ color: "#f87171" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <p className="text-xs text-slate-400 leading-relaxed">
                <span className="font-semibold" style={{ color: "#f87171" }}>
                  {stats.blocked_connections} API connection{stats.blocked_connections !== 1 ? "s" : ""} blocked
                </span>{" "}
                — violation alert thresholds exceeded. Review in the{" "}
                <button onClick={() => setTab("connections")} className="underline" style={{ color: "#f87171" }}>Connections tab</button>.
              </p>
            </div>
          )}

          {/* Top violated scanners + Guardrail health */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="rounded border border-white/5 p-5" style={{ background: "#0d1426" }}>
              <p className="text-xs text-slate-500 font-mono uppercase tracking-wider mb-4">Top Violated Scanners</p>
              {!topViolations ? <Sk h="h-40" /> : topViolations.length === 0 ? (
                <p className="text-xs text-slate-600 py-10 text-center font-mono">No violations recorded.</p>
              ) : (
                <div className="space-y-3">
                  {topViolations.map((v) => {
                    const pct = Math.round((v.count / maxViol) * 100);
                    return (
                      <div key={v.scanner} className="space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono text-slate-400 truncate max-w-[200px]">{v.scanner}</span>
                          <div className="flex items-center gap-3 shrink-0">
                            <span className="text-xs text-slate-600 font-mono">{pct}%</span>
                            <span className="text-xs font-semibold font-mono text-white w-8 text-right">{v.count}</span>
                          </div>
                        </div>
                        <div className="h-1 rounded-full" style={{ background: "rgba(255,255,255,0.04)" }}>
                          <div className="h-1 rounded-full transition-all"
                            style={{ width: `${pct}%`, background: `rgba(248,113,113,${0.35 + pct / 180})` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="rounded border border-white/5 p-5" style={{ background: "#0d1426" }}>
              <div className="flex items-center justify-between mb-4">
                <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">Guardrail Health</p>
                <button onClick={() => setTab("guardrails")} className="text-xs text-slate-600 hover:text-slate-400 transition-colors font-mono">
                  All guardrails →
                </button>
              </div>
              {!guardrails ? <Sk h="h-40" /> : (
                <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                  {guardrails.filter((g) => g.is_active).slice(0, 10).map((g) => (
                    <div key={g.id} className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: "#14B8A6" }} />
                        <span className="text-xs text-slate-400 truncate">{g.name}</span>
                        <span className="text-xs font-mono px-1.5 py-0.5 rounded shrink-0"
                          style={{ background: g.direction === "input" ? "rgba(20,184,166,0.08)" : "rgba(167,139,250,0.08)", color: g.direction === "input" ? "#14B8A6" : "#a78bfa" }}>
                          {g.direction}
                        </span>
                      </div>
                    </div>
                  ))}
                  {guardrails.filter((g) => !g.is_active).length > 0 && (
                    <p className="text-xs text-slate-700 font-mono pt-1">
                      + {guardrails.filter((g) => !g.is_active).length} inactive
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Recent platform activity */}
          <Section title="Recent Platform Activity"
            action={
              <button onClick={() => setTab("audits")} className="text-xs text-slate-600 hover:text-slate-400 transition-colors font-mono">
                Full audit log →
              </button>
            }
          >
            <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5">
                    {["Time", "Dir", "Status", "Risk", "Via", "Violations", "Preview"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {!activity ? Array.from({ length: 6 }).map((_, i) => (
                    <tr key={i} className="border-b border-white/5">
                      <td colSpan={7} className="px-4 py-3"><div className="h-3 rounded animate-pulse" style={{ background: "#111827" }} /></td>
                    </tr>
                  )) : activity.map((a) => {
                    const riskColor = a.max_risk_score >= 0.8 ? "#f87171" : a.max_risk_score >= 0.5 ? "#fbbf24" : "#94a3b8";
                    const envStyle = a.connection_environment ? (ENV_COLOR[a.connection_environment] ?? ENV_COLOR.staging) : null;
                    return (
                      <tr key={a.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.01] transition-colors">
                        <td className="px-4 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
                          {a.created_at ? format(new Date(a.created_at), "HH:mm:ss") : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600 font-mono">{a.direction}</td>
                        <td className="px-4 py-3">
                          <span className="text-xs font-mono px-2 py-0.5 rounded"
                            style={a.is_valid ? { background: "rgba(20,184,166,0.08)", color: "#14B8A6" } : { background: "rgba(248,113,113,0.08)", color: "#f87171" }}>
                            {a.is_valid ? "pass" : "block"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs font-mono" style={{ color: riskColor }}>{a.max_risk_score.toFixed(2)}</td>
                        <td className="px-4 py-3">
                          {a.connection_name ? (
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs text-slate-400 truncate max-w-[80px]">{a.connection_name}</span>
                              {envStyle && <span className="text-xs px-1 py-0.5 rounded font-mono capitalize shrink-0" style={envStyle}>{a.connection_environment}</span>}
                            </div>
                          ) : <span className="text-xs text-slate-700 font-mono">token</span>}
                        </td>
                        <td className="px-4 py-3 text-xs font-mono"
                          style={{ color: a.violation_scanners.length > 0 ? "#f87171" : "#334155" }}>
                          {a.violation_scanners.length > 0 ? a.violation_scanners.slice(0, 2).join(", ") + (a.violation_scanners.length > 2 ? " …" : "") : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500 max-w-[160px] truncate">{a.preview}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}

      {/* ── Users ──────────────────────────────────────────────────── */}
      {tab === "users" && (
        <Section
          title="User Management"
          action={
            <div className="flex items-center gap-3">
              <button onClick={() => downloadCSV("/admin/export/users", "talix-users.csv")}
                className="text-xs px-3 py-1.5 rounded font-mono border border-white/10 text-slate-400 hover:text-white transition-colors">
                ↓ Export CSV
              </button>
              <div className="flex gap-1 p-0.5 rounded" style={{ background: "rgba(255,255,255,0.04)" }}>
                {(["", "admin", "viewer"] as const).map((r) => (
                  <button key={r || "all"} onClick={() => setRoleFilter(r)}
                    className="text-xs px-2.5 py-1 rounded transition-colors"
                    style={roleFilter === r ? { background: "#14B8A6", color: "#0A0F1F" } : { color: "#64748b" }}>
                    {r === "" ? "All" : r}
                  </button>
                ))}
              </div>
              <button onClick={() => setShowCreate(!showCreate)}
                className="text-xs font-medium px-3 py-1.5 rounded transition-colors"
                style={showCreate ? { background: "rgba(255,255,255,0.05)", color: "#94a3b8" } : { background: "#14B8A6", color: "#0A0F1F" }}>
                {showCreate ? "✕ Cancel" : "+ New user"}
              </button>
            </div>
          }
        >
          {showCreate && (
            <CreateUserPanel
              onCreated={async () => { await mutateUsers(); setShowCreate(false); }}
              onCancel={() => setShowCreate(false)}
            />
          )}
          <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/5">
                  {["User", "Email", "Role", "Plan", "Org", "Connections", "Last Active", "Joined", "Actions"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!users ? Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td colSpan={9} className="px-4 py-3"><div className="h-4 rounded animate-pulse" style={{ background: "#111827" }} /></td>
                  </tr>
                )) : filteredUsers?.length === 0 ? (
                  <tr><td colSpan={9} className="px-4 py-10 text-center text-xs text-slate-600 font-mono">No users found.</td></tr>
                ) : filteredUsers?.map((u) => (
                  <tr key={u.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.01] transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                          style={{ background: u.role === "admin" ? "rgba(248,113,113,0.15)" : "rgba(20,184,166,0.1)", color: u.role === "admin" ? "#f87171" : "#14B8A6" }}>
                          {u.username[0].toUpperCase()}
                        </div>
                        <div>
                          <p className="text-xs font-medium text-white">{u.username}</p>
                          {u.full_name && <p className="text-xs text-slate-600">{u.full_name}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 font-mono">{u.email ?? <span className="text-slate-700">—</span>}</td>
                    <td className="px-4 py-3">
                      <span className="text-xs font-mono px-2 py-0.5 rounded capitalize"
                        style={u.role === "admin" ? { background: "rgba(248,113,113,0.1)", color: "#f87171" } : { background: "rgba(20,184,166,0.08)", color: "#14B8A6" }}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs font-mono px-2 py-0.5 rounded capitalize"
                        style={
                          (u.plan ?? "free") === "enterprise" ? { background: "rgba(167,139,250,0.1)", color: "#a78bfa" }
                          : (u.plan ?? "free") === "pro"        ? { background: "rgba(20,184,166,0.08)", color: "#14B8A6" }
                          :                                       { background: "rgba(148,163,184,0.08)", color: "#94a3b8" }
                        }>
                        {u.plan ?? "free"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {u.org_name ? (
                        <span className="text-xs font-mono px-2 py-0.5 rounded truncate max-w-[100px] block"
                          style={{ background: "rgba(99,102,241,0.1)", color: "#a5b4fc" }}>
                          {u.org_name}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-700 font-mono">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 font-mono">
                      {u.connection_count} conn · {u.total_requests.toLocaleString()} req
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 font-mono">{timeAgo(u.last_active_at)}</td>
                    <td className="px-4 py-3 text-xs text-slate-600 font-mono">
                      {u.created_at ? format(new Date(u.created_at), "MM/dd/yy") : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <UserActions user={u} onRoleChange={(role) => handleRoleChange(u, role)}
                        onPlanChange={(plan) => handlePlanChange(u, plan)}
                        onResetPw={() => setResetPwTarget(u)} onDelete={() => setDeleteTarget(u)}
                        onImpersonate={() => handleImpersonate(u)}
                        onAssignOrg={() => setAssignOrgTarget(u)}
                        roleLoading={roleLoading === u.id} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {users && (
              <div className="px-4 py-3 border-t border-white/5 flex items-center justify-between">
                <p className="text-xs text-slate-700 font-mono">{filteredUsers?.length ?? 0} of {users.length} users shown</p>
                <p className="text-xs text-slate-700 font-mono">
                  {users.filter((u) => u.role === "admin").length} admin · {users.filter((u) => u.role === "viewer").length} viewer
                </p>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ── Connections ─────────────────────────────────────────────── */}
      {tab === "connections" && (
        <Section title="All API Connections">
          <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/5">
                  {["Connection", "Owner", "Env", "Status", "Requests", "Violations", "Month Spend", "Last Active"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!connections ? Array.from({ length: 3 }).map((_, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td colSpan={8} className="px-4 py-3"><div className="h-4 rounded animate-pulse" style={{ background: "#111827" }} /></td>
                  </tr>
                )) : connections.length === 0 ? (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-xs text-slate-600 font-mono">No API connections found.</td></tr>
                ) : connections.map((c) => {
                  const envStyle = ENV_COLOR[c.environment] ?? ENV_COLOR.staging;
                  const violRate = c.total_requests > 0 ? (c.total_violations / c.total_requests) * 100 : 0;
                  const spendPct = c.max_monthly_spend && c.max_monthly_spend > 0
                    ? (c.month_spend / c.max_monthly_spend) * 100 : null;
                  return (
                    <tr key={c.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.01] transition-colors">
                      <td className="px-4 py-3">
                        <p className="text-xs font-medium text-white">{c.name}</p>
                        <p className="text-xs text-slate-600 font-mono">id:{c.id}</p>
                      </td>
                      <td className="px-4 py-3">
                        <p className="text-xs text-slate-400">{c.username}</p>
                        {c.full_name && <p className="text-xs text-slate-600">{c.full_name}</p>}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-mono px-1.5 py-0.5 rounded capitalize" style={envStyle}>{c.environment}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-mono px-1.5 py-0.5 rounded"
                          style={c.status === "active" ? { background: "rgba(20,184,166,0.08)", color: "#14B8A6" } : { background: "rgba(248,113,113,0.1)", color: "#f87171" }}>
                          {c.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-400 font-mono">{c.total_requests.toLocaleString()}</td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-mono" style={{ color: c.total_violations > 0 ? "#f87171" : "#475569" }}>
                          {c.total_violations}
                        </span>
                        {c.total_requests > 0 && (
                          <span className="text-xs text-slate-700 font-mono ml-1">({violRate.toFixed(0)}%)</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-mono" style={{
                          color: spendPct !== null && spendPct >= 90 ? "#f87171" : spendPct !== null && spendPct >= 70 ? "#fbbf24" : "#a78bfa",
                        }}>
                          ${c.month_spend.toFixed(2)}
                        </span>
                        {c.max_monthly_spend && (
                          <span className="text-xs text-slate-700 font-mono ml-1">/ ${c.max_monthly_spend.toFixed(0)}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 font-mono">{timeAgo(c.last_active_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {connections && (
              <div className="px-4 py-3 border-t border-white/5">
                <p className="text-xs text-slate-700 font-mono">
                  {connections.length} connections · {connections.filter((c) => c.status === "blocked").length} blocked ·{" "}
                  ${connections.reduce((s, c) => s + c.month_spend, 0).toFixed(2)} month spend
                </p>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ── Guardrails ──────────────────────────────────────────────── */}
      {tab === "guardrails" && (
        <Section title="All Guardrails">
          <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
            {!guardrails ? (
              <div className="p-6 space-y-2"><Sk h="h-10" cols={6} /></div>
            ) : (
              <>
                {(["input", "output"] as const).map((dir) => {
                  const list = guardrails.filter((g) => g.direction === dir);
                  return (
                    <div key={dir}>
                      <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2"
                        style={{ background: "rgba(255,255,255,0.01)" }}>
                        <span className="text-xs font-mono font-semibold capitalize px-2 py-0.5 rounded"
                          style={dir === "input" ? { background: "rgba(20,184,166,0.1)", color: "#14B8A6" } : { background: "rgba(167,139,250,0.1)", color: "#a78bfa" }}>
                          {dir}
                        </span>
                        <span className="text-xs text-slate-600 font-mono">
                          {list.filter((g) => g.is_active).length} active · {list.filter((g) => !g.is_active).length} inactive
                        </span>
                      </div>
                      {list.map((g) => (
                        <div key={g.id} className="flex items-center justify-between px-5 py-3 border-b border-white/5 last:border-0">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: g.is_active ? "#14B8A6" : "#334155" }} />
                            <span className="text-xs text-slate-300 truncate">{g.name}</span>
                            <span className="text-xs font-mono text-slate-600 shrink-0">{g.scanner_type}</span>
                          </div>
                          <button
                            onClick={() => handleToggleGuardrail(g.id)}
                            disabled={toggling === g.id}
                            className="text-xs px-3 py-1 rounded border ml-4 shrink-0 transition-colors disabled:opacity-40"
                            style={g.is_active
                              ? { borderColor: "rgba(20,184,166,0.3)", color: "#14B8A6" }
                              : { borderColor: "rgba(255,255,255,0.08)", color: "#475569" }}>
                            {toggling === g.id ? "…" : g.is_active ? "On" : "Off"}
                          </button>
                        </div>
                      ))}
                    </div>
                  );
                })}
                <div className="px-5 py-3 border-t border-white/5">
                  <p className="text-xs text-slate-700 font-mono">
                    {guardrails.filter((g) => g.is_active).length} active · {guardrails.filter((g) => !g.is_active).length} inactive · {guardrails.length} total
                  </p>
                </div>
              </>
            )}
          </div>
        </Section>
      )}

      {/* ── Activity ────────────────────────────────────────────────── */}
      {tab === "activity" && (
        <ActivityTab entries={liveActivity ?? []} />
      )}

      {/* ── Audits ──────────────────────────────────────────────────── */}
      {tab === "audits" && (
        <Section title="Platform Audit Log">
          <AuditsTab isAdmin={isAdmin} />
        </Section>
      )}

      {/* ── Organizations ───────────────────────────────────────── */}
      {tab === "orgs" && (
        <OrgsTab />
      )}

      {/* ── Billing ─────────────────────────────────────────────── */}
      {tab === "billing" && <BillingAdminTab />}

      {/* ── Settings ────────────────────────────────────────────── */}
      {tab === "settings" && (
        <SettingsTab platformSettings={platformSettings} mutatePlatform={mutatePlatform} />
      )}

      {/* Modals */}
      {deleteTarget && <DeleteModal user={deleteTarget} onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)} />}
      {resetPwTarget && <ResetPasswordModal user={resetPwTarget} onClose={() => setResetPwTarget(null)} />}
      {assignOrgTarget && (
        <AssignOrgModal
          user={assignOrgTarget}
          orgs={adminOrgs ?? []}
          onClose={() => setAssignOrgTarget(null)}
          onSaved={async () => { await mutateUsers(); setAssignOrgTarget(null); }}
        />
      )}
    </div>
  );
}
