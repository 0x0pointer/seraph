"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { format } from "date-fns";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Me { id: number; username: string; role: string; org_id: number | null; team_id: number | null; }

interface OrgInfo {
  id: number; name: string; plan: string; user_limit: number | null;
  created_at: string | null;
  owner_id: number | null; owner_username: string | null; member_count: number;
}

interface OrgMember {
  id: number; username: string; full_name: string | null;
  email: string | null; role: string; created_at: string | null;
  team_id: number | null;
}

interface TeamInfo {
  id: number; name: string; org_id: number;
  created_by_username: string | null; member_count: number;
}

interface TeamMember {
  id: number; username: string; full_name: string | null;
  email: string | null; role: string;
}

interface OrgInvite {
  id: number; email: string; role: string; token: string;
  invited_by_username: string | null; created_at: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const inputStyle = { background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#e2e8f0" };

const ROLE_STYLES: Record<string, { background: string; color: string }> = {
  admin:     { background: "rgba(248,113,113,0.1)",  color: "#f87171" },
  org_admin: { background: "rgba(251,191,36,0.1)",   color: "#fbbf24" },
  viewer:    { background: "rgba(20,184,166,0.08)",  color: "#14B8A6" },
};

const ROLE_LABEL: Record<string, string> = {
  admin: "Super Admin", org_admin: "Org Admin", viewer: "Member",
};

function RolePill({ role }: { role: string }) {
  const style = ROLE_STYLES[role] ?? ROLE_STYLES.viewer;
  return (
    <span className="text-xs font-mono px-2 py-0.5 rounded capitalize" style={style}>
      {ROLE_LABEL[role] ?? role}
    </span>
  );
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const d = Math.floor(diff / 86400000);
    if (d === 0) return "today";
    if (d === 1) return "yesterday";
    return `${d} days ago`;
  } catch { return "—"; }
}

// ── Invite link copy ──────────────────────────────────────────────────────────

function InviteLink({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);
  const link = `${typeof window !== "undefined" ? window.location.origin : ""}/join?invite=${token}`;

  function copy() {
    navigator.clipboard.writeText(link).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex items-center gap-2 mt-1">
      <code className="text-xs font-mono px-2 py-1 rounded truncate max-w-xs"
        style={{ background: "#0A0F1F", color: "#94a3b8" }}>
        {link.slice(0, 60)}{link.length > 60 ? "…" : ""}
      </code>
      <button onClick={copy}
        className="text-xs px-2 py-1 rounded border transition-colors shrink-0"
        style={copied
          ? { borderColor: "rgba(20,184,166,0.4)", color: "#14B8A6" }
          : { borderColor: "rgba(255,255,255,0.08)", color: "#64748b" }}>
        {copied ? "✓ Copied" : "Copy"}
      </button>
    </div>
  );
}

// ── Teams section ─────────────────────────────────────────────────────────────

function TeamsSection({
  canManage, orgId, myTeamId, allMembers,
}: {
  canManage: boolean; orgId: number; myTeamId: number | null; allMembers: OrgMember[];
}) {
  const { data: teams, mutate: mutateTeams } = useSWR<TeamInfo[]>(
    "/teams", () => api.get<TeamInfo[]>("/teams"), { revalidateOnFocus: false },
  );

  const [expanded, setExpanded] = useState<number | null>(null);
  const [teamMembers, setTeamMembers] = useState<Record<number, TeamMember[]>>({});
  const [creating, setCreating] = useState(false);
  const [newTeamName, setNewTeamName] = useState("");
  const [addingUserId, setAddingUserId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function loadMembers(teamId: number) {
    const members = await api.get<TeamMember[]>(`/teams/${teamId}/members`);
    setTeamMembers((prev) => ({ ...prev, [teamId]: members }));
  }

  async function handleExpand(teamId: number) {
    if (expanded === teamId) { setExpanded(null); return; }
    setExpanded(teamId);
    await loadMembers(teamId);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault(); setError(""); setBusy(true);
    try {
      await api.post("/teams", { name: newTeamName.trim() });
      setNewTeamName(""); setCreating(false);
      await mutateTeams();
    } catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
    finally { setBusy(false); }
  }

  async function handleDelete(team: TeamInfo) {
    if (!confirm(`Delete team "${team.name}"? Members will be unassigned.`)) return;
    await api.delete(`/teams/${team.id}`);
    await mutateTeams();
    if (expanded === team.id) setExpanded(null);
  }

  async function handleAddMember(teamId: number) {
    if (!addingUserId) return;
    setBusy(true);
    try {
      await api.patch(`/teams/${teamId}/members/${addingUserId}`, {});
      setAddingUserId("");
      await loadMembers(teamId);
      await mutateTeams();
    } catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
    finally { setBusy(false); }
  }

  async function handleRemoveMember(teamId: number, userId: number) {
    await api.delete(`/teams/${teamId}/members/${userId}`);
    await loadMembers(teamId);
    await mutateTeams();
  }

  const assignableMembers = allMembers.filter((m) => m.role !== "admin");

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">Teams</p>
        {canManage && !creating && (
          <button onClick={() => setCreating(true)}
            className="text-xs font-medium px-3 py-1.5 rounded transition-colors"
            style={{ background: "#14B8A6", color: "#0A0F1F" }}>
            + New team
          </button>
        )}
      </div>

      {creating && (
        <form onSubmit={handleCreate}
          className="rounded border p-4 flex items-end gap-3"
          style={{ background: "#0d1426", borderColor: "rgba(20,184,166,0.2)" }}>
          <div className="flex-1">
            <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Team name</label>
            <input
              value={newTeamName} onChange={(e) => setNewTeamName(e.target.value)}
              required placeholder="e.g. Engineering" autoFocus
              className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle}
            />
          </div>
          <button type="submit" disabled={busy}
            className="px-4 py-2 rounded text-sm font-medium disabled:opacity-50"
            style={{ background: "#14B8A6", color: "#0A0F1F" }}>
            {busy ? "Creating…" : "Create"}
          </button>
          <button type="button" onClick={() => setCreating(false)}
            className="text-xs text-slate-600 hover:text-slate-400">Cancel</button>
        </form>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}

      {!teams ? (
        <div className="h-20 rounded animate-pulse" style={{ background: "#0d1426" }} />
      ) : teams.length === 0 ? (
        <div className="rounded border border-white/5 p-8 text-center" style={{ background: "#0d1426" }}>
          <p className="text-xs text-slate-600 font-mono">
            No teams yet. Create a team to group members and share connections.
          </p>
        </div>
      ) : (
        <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
          {teams.map((team) => (
            <div key={team.id} className="border-b border-white/5 last:border-0">
              {/* Team row */}
              <div className="flex items-center justify-between px-4 py-3">
                <button
                  onClick={() => handleExpand(team.id)}
                  className="flex items-center gap-3 flex-1 text-left min-w-0"
                >
                  <div className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                    style={{ background: "rgba(99,102,241,0.15)", color: "#a5b4fc" }}>
                    {team.name[0]?.toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-xs font-medium text-white truncate">{team.name}</p>
                      {myTeamId === team.id && (
                        <span className="text-xs font-mono px-1.5 py-0.5 rounded shrink-0"
                          style={{ background: "rgba(99,102,241,0.1)", color: "#a5b4fc" }}>
                          your team
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-600 font-mono">
                      {team.member_count} member{team.member_count !== 1 ? "s" : ""}
                      {team.created_by_username && ` · created by @${team.created_by_username}`}
                    </p>
                  </div>
                </button>
                <div className="flex items-center gap-2 shrink-0 ml-3">
                  <span className="text-xs text-slate-700 font-mono">{expanded === team.id ? "▲" : "▼"}</span>
                  {canManage && (
                    <button onClick={() => handleDelete(team)}
                      className="text-xs px-2 py-1 rounded border transition-colors"
                      style={{ borderColor: "rgba(248,113,113,0.2)", color: "#f87171" }}>
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {/* Expanded: members + add member */}
              {expanded === team.id && (
                <div className="px-4 pb-4 space-y-3 border-t border-white/5 pt-3"
                  style={{ background: "rgba(99,102,241,0.02)" }}>
                  {/* Member list */}
                  {(teamMembers[team.id] ?? []).length === 0 ? (
                    <p className="text-xs text-slate-600 font-mono">No members in this team yet.</p>
                  ) : (
                    <div className="space-y-1">
                      {(teamMembers[team.id] ?? []).map((m) => (
                        <div key={m.id} className="flex items-center justify-between py-1.5 px-2 rounded"
                          style={{ background: "rgba(255,255,255,0.02)" }}>
                          <div className="flex items-center gap-2">
                            <div className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold"
                              style={{ background: "rgba(99,102,241,0.15)", color: "#a5b4fc" }}>
                              {m.username[0].toUpperCase()}
                            </div>
                            <span className="text-xs text-white">{m.username}</span>
                            {m.full_name && <span className="text-xs text-slate-600">{m.full_name}</span>}
                          </div>
                          {canManage && (
                            <button onClick={() => handleRemoveMember(team.id, m.id)}
                              className="text-xs text-slate-600 hover:text-red-400 transition-colors font-mono">
                              remove
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Add member dropdown */}
                  {canManage && (
                    <div className="flex items-center gap-2 pt-1">
                      <div className="relative flex-1">
                        <select value={addingUserId} onChange={(e) => setAddingUserId(e.target.value)}
                          className="w-full rounded px-3 py-1.5 text-xs outline-none appearance-none pr-7"
                          style={inputStyle}>
                          <option value="">— Select member to add —</option>
                          {assignableMembers
                            .filter((m) => !(teamMembers[team.id] ?? []).some((tm) => tm.id === m.id))
                            .map((m) => (
                              <option key={m.id} value={m.id}>
                                @{m.username}{m.full_name ? ` (${m.full_name})` : ""}
                                {m.team_id ? " ⚠ already in a team" : ""}
                              </option>
                            ))}
                        </select>
                        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none" style={{ fontSize: 9 }}>▾</span>
                      </div>
                      <button
                        onClick={() => handleAddMember(team.id)}
                        disabled={!addingUserId || busy}
                        className="text-xs px-3 py-1.5 rounded font-medium disabled:opacity-40 transition-colors"
                        style={{ background: "rgba(99,102,241,0.15)", color: "#a5b4fc", border: "1px solid rgba(99,102,241,0.25)" }}>
                        Add
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Invite form ───────────────────────────────────────────────────────────────

function InviteForm({ onInvited }: { onInvited: () => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<OrgInvite | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setSaving(true);
    try {
      const inv = await api.post<OrgInvite>("/org/invite", { email, role });
      setResult(inv);
      setEmail(""); setRole("viewer");
      onInvited();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create invite");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded border border-white/5 p-5 space-y-4" style={{ background: "#0d1426" }}>
      <p className="text-xs font-mono text-slate-400 uppercase tracking-wider">Invite New Member</p>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-48">
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Email</label>
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            required placeholder="colleague@company.com"
            className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Role</label>
          <div className="relative">
            <select value={role} onChange={(e) => setRole(e.target.value)}
              className="rounded px-3 py-2 text-sm outline-none appearance-none pr-7" style={inputStyle}>
              <option value="viewer">Member</option>
              <option value="org_admin">Org Admin</option>
            </select>
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none text-xs">▾</span>
          </div>
        </div>
        <button type="submit" disabled={saving}
          className="px-5 py-2 rounded text-sm font-medium disabled:opacity-50"
          style={{ background: "#14B8A6", color: "#0A0F1F" }}>
          {saving ? "Sending…" : "Generate invite"}
        </button>
      </form>
      {error && <p className="text-xs text-red-400">{error}</p>}
      {result && (
        <div className="rounded border border-white/5 p-3 space-y-1" style={{ background: "#0A0F1F" }}>
          <p className="text-xs text-slate-400">
            Invite link for <span className="text-white font-mono">{result.email}</span> ({ROLE_LABEL[result.role] ?? result.role}):
          </p>
          <InviteLink token={result.token} />
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OrganizationPage() {
  const { data: me } = useSWR<Me>("/auth/me", () => api.get<Me>("/auth/me"), { revalidateOnFocus: false });

  const canManage = me?.role === "admin" || me?.role === "org_admin";
  const hasOrg = !!me?.org_id;

  const { data: org, isLoading: orgLoading, mutate: mutateOrg } = useSWR<OrgInfo>(
    hasOrg ? "/org" : null,
    () => api.get<OrgInfo>("/org"),
    { revalidateOnFocus: false },
  );

  const { data: members, mutate: mutateMembers } = useSWR<OrgMember[]>(
    hasOrg && canManage ? "/org/members" : null,
    () => api.get<OrgMember[]>("/org/members"),
    { revalidateOnFocus: false },
  );

  const { data: invites, mutate: mutateInvites } = useSWR<OrgInvite[]>(
    hasOrg && canManage ? "/org/invites" : null,
    () => api.get<OrgInvite[]>("/org/invites"),
    { revalidateOnFocus: false },
  );

  const [editingName, setEditingName] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [roleLoading, setRoleLoading] = useState<number | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [cancellingInvite, setCancellingInvite] = useState<number | null>(null);
  const [expandedInvite, setExpandedInvite] = useState<number | null>(null);
  const [changingPlan, setChangingPlan] = useState(false);
  const [planError, setPlanError] = useState("");

  async function handleSaveName(e: React.FormEvent) {
    e.preventDefault();
    setSavingName(true);
    try {
      await api.put("/org", { name: orgName });
      await mutateOrg();
      setEditingName(false);
    } finally {
      setSavingName(false);
    }
  }

  async function handlePlanChange(newPlan: string) {
    setPlanError(""); setChangingPlan(true);
    try {
      await api.patch("/org/plan", { plan: newPlan });
      await mutateOrg();
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : "Failed to change plan");
    } finally { setChangingPlan(false); }
  }

  async function handleRoleChange(member: OrgMember, newRole: string) {
    setRoleLoading(member.id);
    try {
      await api.patch(`/org/members/${member.id}/role`, { role: newRole });
      await mutateMembers();
    } catch { /* silently ignore */ }
    finally { setRoleLoading(null); }
  }

  async function handleRemove(member: OrgMember) {
    if (!confirm(`Remove ${member.username} from the organization?`)) return;
    setRemovingId(member.id);
    try {
      await api.delete(`/org/members/${member.id}`);
      await mutateMembers();
    } finally { setRemovingId(null); }
  }

  async function handleCancelInvite(invite: OrgInvite) {
    setCancellingInvite(invite.id);
    try {
      await api.delete(`/org/invites/${invite.id}`);
      await mutateInvites();
    } finally { setCancellingInvite(null); }
  }

  if (!me) {
    return <div className="h-48 rounded animate-pulse" style={{ background: "#0d1426" }} />;
  }

  if (!hasOrg) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <div className="w-14 h-14 rounded-full flex items-center justify-center"
          style={{ background: "rgba(20,184,166,0.08)" }}>
          <svg className="w-7 h-7" style={{ color: "#14B8A6" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
          </svg>
        </div>
        <p className="text-white font-semibold">No organization</p>
        <p className="text-xs text-slate-500 max-w-xs text-center leading-relaxed">
          You are not part of any organization yet. Ask a super admin to assign you to one, or accept an invite link.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">

      {/* ── Org header ─────────────────────────────────────────────── */}
      <div className="rounded border border-white/5 p-6" style={{ background: "#0d1426" }}>
        {orgLoading ? (
          <div className="h-10 rounded animate-pulse" style={{ background: "#111827" }} />
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold"
                  style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}>
                  {org?.name?.[0]?.toUpperCase() ?? "O"}
                </div>
                {editingName ? (
                  <form onSubmit={handleSaveName} className="flex items-center gap-2">
                    <input
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      autoFocus
                      className="rounded px-3 py-1.5 text-sm outline-none"
                      style={inputStyle}
                    />
                    <button type="submit" disabled={savingName}
                      className="text-xs px-3 py-1.5 rounded font-medium disabled:opacity-50"
                      style={{ background: "#14B8A6", color: "#0A0F1F" }}>
                      {savingName ? "…" : "Save"}
                    </button>
                    <button type="button" onClick={() => setEditingName(false)}
                      className="text-xs text-slate-600 hover:text-slate-400">Cancel</button>
                  </form>
                ) : (
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold text-white">{org?.name}</h2>
                    {canManage && (
                      <button
                        onClick={() => { setOrgName(org?.name ?? ""); setEditingName(true); }}
                        className="text-xs text-slate-600 hover:text-slate-400 transition-colors">
                        Edit
                      </button>
                    )}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-4 text-xs text-slate-500 font-mono pl-12">
                <span>{org?.member_count ?? 0}{org?.user_limit != null ? ` / ${org.user_limit}` : ""} member{(org?.member_count ?? 0) !== 1 ? "s" : ""}</span>
                {org?.owner_username && <span>Owner: <span className="text-slate-400">{org.owner_username}</span></span>}
                {org?.created_at && <span>Created {timeAgo(org.created_at)}</span>}
              </div>
            </div>
            <div className="flex flex-col items-end gap-2">
              <RolePill role={me.role} />
              {/* Plan badge */}
              {org && (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono px-2 py-0.5 rounded capitalize"
                    style={
                      (org.plan ?? "free") === "enterprise" ? { background: "rgba(167,139,250,0.1)", color: "#a78bfa" }
                      : (org.plan ?? "free") === "pro"       ? { background: "rgba(20,184,166,0.08)", color: "#14B8A6" }
                      :                                        { background: "rgba(148,163,184,0.08)", color: "#94a3b8" }
                    }>
                    {org.plan ?? "free"}
                  </span>
                  {canManage && (
                    <div className="relative">
                      <select
                        value={org.plan ?? "free"}
                        onChange={(e) => handlePlanChange(e.target.value)}
                        disabled={changingPlan}
                        className="text-xs rounded px-2 py-1 outline-none appearance-none pr-5 disabled:opacity-40"
                        style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#64748b", fontSize: "11px" }}
                      >
                        <option value="free">Free</option>
                        <option value="pro">Pro</option>
                        <option value="enterprise">Enterprise</option>
                      </select>
                      <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none" style={{ fontSize: 9 }}>▾</span>
                    </div>
                  )}
                </div>
              )}
              {planError && <p className="text-xs" style={{ color: "#f87171" }}>{planError}</p>}
            </div>
          </div>
        )}
      </div>

      {/* ── Members ────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">Members</p>
          <p className="text-xs text-slate-600 font-mono">{members?.length ?? 0}{org?.user_limit != null ? ` / ${org.user_limit}` : ""} total</p>
        </div>
        {org?.user_limit != null && (org.member_count ?? 0) >= org.user_limit && (
          <div className="rounded px-3 py-2 text-xs flex items-center gap-2"
            style={{ background: "rgba(251,191,36,0.07)", border: "1px solid rgba(251,191,36,0.2)", color: "#fbbf24" }}>
            <span>▲</span>
            User limit reached ({org.member_count} / {org.user_limit}). Upgrade your plan to invite more members.
          </div>
        )}
        <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5">
                {["Member", "Email", "Role", "Joined", ...(canManage ? ["Actions"] : [])].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!members ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td colSpan={canManage ? 5 : 4} className="px-4 py-3">
                      <div className="h-4 rounded animate-pulse" style={{ background: "#111827" }} />
                    </td>
                  </tr>
                ))
              ) : members.length === 0 ? (
                <tr>
                  <td colSpan={canManage ? 5 : 4} className="px-4 py-12 text-center text-xs text-slate-600 font-mono">
                    No members yet. Invite someone to get started.
                  </td>
                </tr>
              ) : members.map((m) => (
                <tr key={m.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.01] transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                        style={ROLE_STYLES[m.role] ?? ROLE_STYLES.viewer}>
                        {m.username[0].toUpperCase()}
                      </div>
                      <div>
                        <p className="text-xs font-medium text-white">{m.username}</p>
                        {m.full_name && <p className="text-xs text-slate-600">{m.full_name}</p>}
                      </div>
                      {m.id === me.id && (
                        <span className="text-xs text-slate-700 font-mono">(you)</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 font-mono">{m.email ?? "—"}</td>
                  <td className="px-4 py-3"><RolePill role={m.role} /></td>
                  <td className="px-4 py-3 text-xs text-slate-600 font-mono">
                    {m.created_at ? format(new Date(m.created_at), "MM/dd/yy") : "—"}
                  </td>
                  {canManage && (
                    <td className="px-4 py-3">
                      {m.id !== me.id && m.role !== "admin" && (
                        <div className="flex items-center gap-2">
                          <div className="relative">
                            <select
                              value={m.role}
                              onChange={(e) => handleRoleChange(m, e.target.value)}
                              disabled={roleLoading === m.id}
                              className="text-xs rounded px-2 py-1 outline-none appearance-none pr-5 disabled:opacity-40"
                              style={{ ...inputStyle, fontSize: "11px" }}
                            >
                              <option value="viewer">Member</option>
                              <option value="org_admin">Org Admin</option>
                            </select>
                            <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none" style={{ fontSize: 9 }}>▾</span>
                          </div>
                          <button
                            onClick={() => handleRemove(m)}
                            disabled={removingId === m.id}
                            className="text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40"
                            style={{ borderColor: "rgba(248,113,113,0.2)", color: "#f87171" }}>
                            {removingId === m.id ? "…" : "Remove"}
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Teams ──────────────────────────────────────────────────── */}
      <TeamsSection
        canManage={canManage}
        orgId={org?.id ?? 0}
        myTeamId={me.team_id}
        allMembers={members ?? []}
      />

      {/* ── Invite members ─────────────────────────────────────────── */}
      {canManage && (
        <>
          <InviteForm onInvited={() => mutateInvites()} />

          {/* Pending invites */}
          {invites && invites.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">
                Pending Invites ({invites.length})
              </p>
              <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
                {invites.map((inv) => (
                  <div key={inv.id} className="border-b border-white/5 last:border-0">
                    <div className="flex items-center justify-between px-4 py-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                          style={{ background: "rgba(251,191,36,0.1)", color: "#fbbf24" }}>
                          ?
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs text-white font-mono truncate">{inv.email}</p>
                          <p className="text-xs text-slate-600">
                            Invited {timeAgo(inv.created_at)}
                            {inv.invited_by_username && ` by ${inv.invited_by_username}`}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 shrink-0 ml-4">
                        <RolePill role={inv.role} />
                        <button
                          onClick={() => setExpandedInvite(expandedInvite === inv.id ? null : inv.id)}
                          className="text-xs text-slate-600 hover:text-slate-300 font-mono transition-colors">
                          link {expandedInvite === inv.id ? "▲" : "▼"}
                        </button>
                        <button
                          onClick={() => handleCancelInvite(inv)}
                          disabled={cancellingInvite === inv.id}
                          className="text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40"
                          style={{ borderColor: "rgba(248,113,113,0.2)", color: "#f87171" }}>
                          {cancellingInvite === inv.id ? "…" : "Revoke"}
                        </button>
                      </div>
                    </div>
                    {expandedInvite === inv.id && (
                      <div className="px-4 pb-3">
                        <InviteLink token={inv.token} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
