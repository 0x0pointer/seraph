"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import Cookies from "js-cookie";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

interface UserInfo { id: number; username: string; full_name: string | null; email: string | null; role: string; }
interface Ticket {
  id: number; user_id: number | null; name: string; email: string; subject: string;
  category: string; priority: string; description: string; status: string;
  created_at: string; updated_at: string; response_count: number;
  responses: TicketResp[];
}
interface TicketResp { id: number; responder_name: string; message: string; is_staff: boolean; created_at: string; }
interface Stats { total: number; open: number; in_progress: number; resolved: number; closed: number; }

const categories = [
  { value: "bug", label: "Bug Report" },
  { value: "feature", label: "Feature Request" },
  { value: "question", label: "General Question" },
  { value: "billing", label: "Billing & Plans" },
  { value: "security", label: "Security Issue" },
  { value: "integration", label: "API / Integration Help" },
];
const priorities = [
  { value: "low", label: "Low", color: "var(--text-dim)" },
  { value: "medium", label: "Medium", color: "#f59e0b" },
  { value: "high", label: "High", color: "#f97316" },
  { value: "urgent", label: "Urgent", color: "#f87171" },
];

const statusColors: Record<string, { bg: string; color: string; label: string }> = {
  open:        { bg: "rgba(92,240,151,0.1)",  color: "#5CF097", label: "Open" },
  in_progress: { bg: "rgba(251,191,36,0.1)",  color: "#fbbf24", label: "In Progress" },
  resolved:    { bg: "rgba(148,163,184,0.1)", color: "var(--text-muted)", label: "Resolved" },
  closed:      { bg: "rgba(71,85,105,0.15)",  color: "var(--text-dim)", label: "Closed" },
};

function priorityColor(p: string) {
  return priorities.find((x) => x.value === p)?.color ?? "#64748b";
}

function fmt(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

const inputStyle = { background: "var(--card)", border: "1px solid var(--border-input)", color: "var(--text)", borderRadius: "6px" } as const;
const labelCls = "block text-xs font-medium text-slate-400 mb-1.5";

// ─────────────────────────────────────────────────────────────────────────────
// Staff view
// ─────────────────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const s = statusColors[status] ?? statusColors.open;
  return (
    <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ background: s.bg, color: s.color }}>
      {s.label}
    </span>
  );
}

function StaffView({ currentUser }: { currentUser: UserInfo }) {
  const router = useRouter();
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [impersonating, setImpersonating] = useState(false);

  const qs = new URLSearchParams();
  if (statusFilter) qs.set("status", statusFilter);
  if (priorityFilter) qs.set("priority", priorityFilter);
  if (search) qs.set("search", search);

  const { data: stats } = useSWR<Stats>("/support/stats", () => api.get("/support/stats"), { refreshInterval: 15000 });
  const { data: tickets, mutate: mutateList } = useSWR<Ticket[]>(
    `/support/tickets?${qs.toString()}`,
    () => api.get(`/support/tickets?${qs.toString()}`),
    { refreshInterval: 15000 }
  );

  async function loadTicket(id: number) {
    const t = await api.get<Ticket>(`/support/tickets/${id}`);
    setSelected(t);
  }

  async function sendReply() {
    if (!selected || !reply.trim()) return;
    setSending(true);
    try {
      await api.post(`/support/tickets/${selected.id}/responses`, { message: reply });
      setReply("");
      await loadTicket(selected.id);
      mutateList();
    } finally {
      setSending(false);
    }
  }

  async function setStatus(s: string) {
    if (!selected) return;
    await api.patch(`/support/tickets/${selected.id}/status`, { status: s });
    await loadTicket(selected.id);
    mutateList();
  }

  async function impersonateUser() {
    if (!selected?.user_id) return;
    setImpersonating(true);
    try {
      const res = await api.post<{ access_token: string; username: string }>(`/admin/users/${selected.user_id}/impersonate`, {});
      const adminToken = Cookies.get("token");
      if (adminToken) Cookies.set("admin_token", adminToken, { expires: 1 });
      Cookies.set("token", res.access_token, { expires: 1 });
      Cookies.set("impersonating_user", res.username, { expires: 1 });
      router.push("/dashboard");
      router.refresh();
    } catch {
      alert("Could not impersonate this user.");
    } finally {
      setImpersonating(false);
    }
  }

  const statCards = [
    { label: "Total", value: stats?.total ?? "—", color: "var(--text-muted)" },
    { label: "Open", value: stats?.open ?? "—", color: "#5CF097" },
    { label: "In Progress", value: stats?.in_progress ?? "—", color: "#fbbf24" },
    { label: "Resolved", value: stats?.resolved ?? "—", color: "var(--text-muted)" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white tracking-tight mb-1">Support Inbox</h1>
        <p className="text-sm text-slate-500">Review and respond to customer tickets.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        {statCards.map((s) => (
          <div key={s.label} className="rounded-lg px-5 py-4 border border-white/5" style={{ background: "var(--card)" }}>
            <p className="text-2xl font-bold tracking-tight" style={{ color: s.color }}>{String(s.value)}</p>
            <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Main panel */}
      <div className="flex gap-4 h-[620px]">

        {/* Ticket list */}
        <div className="w-80 shrink-0 flex flex-col rounded-lg border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
          {/* Filters */}
          <div className="px-3 py-3 border-b border-white/5 space-y-2">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search subject, email…"
              className="w-full px-3 py-1.5 text-xs outline-none rounded placeholder:text-slate-600"
              style={inputStyle}
            />
            <div className="flex gap-2">
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                className="flex-1 px-2 py-1.5 text-xs outline-none rounded" style={inputStyle}>
                <option value="">All statuses</option>
                {Object.entries(statusColors).map(([v, s]) => <option key={v} value={v}>{s.label}</option>)}
              </select>
              <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}
                className="flex-1 px-2 py-1.5 text-xs outline-none rounded" style={inputStyle}>
                <option value="">All priorities</option>
                {priorities.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto">
            {!tickets ? (
              <div className="p-4 space-y-2">{[...Array(5)].map((_, i) => (
                <div key={i} className="h-16 rounded animate-pulse" style={{ background: "var(--bg)" }} />
              ))}</div>
            ) : tickets.length === 0 ? (
              <p className="text-xs text-slate-600 text-center mt-8">No tickets found.</p>
            ) : tickets.map((t) => (
              <button
                key={t.id}
                onClick={() => loadTicket(t.id)}
                className="w-full text-left px-4 py-3 border-b border-white/5 hover:bg-white/5 transition-colors"
                style={selected?.id === t.id ? { background: "rgba(92,240,151,0.06)" } : {}}
              >
                <div className="flex items-start justify-between gap-2 mb-1">
                  <span className="text-xs font-medium text-white truncate">{t.subject}</span>
                  <span className="w-1.5 h-1.5 rounded-full shrink-0 mt-1.5" style={{ background: priorityColor(t.priority) }} />
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={t.status} />
                  <span className="text-xs text-slate-600 truncate">{t.email}</span>
                </div>
                <p className="text-xs text-slate-600 mt-1">{new Date(t.created_at).toLocaleDateString()}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Ticket detail */}
        <div className="flex-1 flex flex-col rounded-lg border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
          {!selected ? (
            <div className="flex-1 flex items-center justify-center">
              <p className="text-sm text-slate-600">Select a ticket to view details</p>
            </div>
          ) : (
            <>
              {/* Header */}
              <div className="px-6 py-4 border-b border-white/5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <StatusBadge status={selected.status} />
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded capitalize"
                        style={{ background: `${priorityColor(selected.priority)}15`, color: priorityColor(selected.priority) }}>
                        {selected.priority}
                      </span>
                      <span className="text-xs text-slate-600 font-mono">{categories.find(c => c.value === selected.category)?.label}</span>
                    </div>
                    <h2 className="text-sm font-semibold text-white">{selected.subject}</h2>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {selected.name} · <a href={`mailto:${selected.email}`} className="hover:text-white" style={{ color: "#5CF097" }}>{selected.email}</a>
                      {" "}· #{selected.id} · {fmt(selected.created_at)}
                    </p>
                  </div>
                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0">
                    {selected.user_id && (
                      <button
                        onClick={impersonateUser}
                        disabled={impersonating}
                        className="text-xs px-3 py-1.5 rounded border border-white/10 text-slate-400 hover:text-white hover:border-white/20 transition-colors disabled:opacity-50"
                      >
                        {impersonating ? "…" : "Impersonate user"}
                      </button>
                    )}
                    <select
                      value={selected.status}
                      onChange={(e) => setStatus(e.target.value)}
                      className="text-xs px-2 py-1.5 rounded outline-none"
                      style={inputStyle}
                    >
                      {Object.entries(statusColors).map(([v, s]) => <option key={v} value={v}>{s.label}</option>)}
                    </select>
                  </div>
                </div>
              </div>

              {/* Thread */}
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                {/* Original message */}
                <div className="rounded-lg p-4 border border-white/5" style={{ background: "var(--bg)" }}>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-medium text-white">{selected.name}</p>
                    <p className="text-xs text-slate-600">{fmt(selected.created_at)}</p>
                  </div>
                  <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-wrap">{selected.description}</p>
                </div>

                {/* Responses */}
                {selected.responses.map((r) => (
                  <div key={r.id} className={`rounded-lg p-4 border ${r.is_staff ? "border-[#5CF097]/30" : "border-white/5"}`}
                    style={{ background: r.is_staff ? "rgba(92,240,151,0.04)" : "var(--card)" }}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <p className="text-xs font-medium text-white">{r.responder_name}</p>
                        {r.is_staff && (
                          <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: "rgba(92,240,151,0.1)", color: "#5CF097" }}>
                            staff
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-600">{fmt(r.created_at)}</p>
                    </div>
                    <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-wrap">{r.message}</p>
                  </div>
                ))}
              </div>

              {/* Reply box */}
              <div className="px-6 py-4 border-t border-white/5">
                <textarea
                  rows={3}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="Type your reply…"
                  className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600 resize-none rounded mb-3"
                  style={inputStyle}
                />
                <div className="flex items-center justify-between">
                  <div className="flex gap-2">
                    {(["resolved", "closed"] as const).map((s) => (
                      <button key={s} onClick={() => setStatus(s)}
                        className="text-xs px-3 py-1.5 rounded border border-white/10 text-slate-500 hover:text-white hover:border-white/20 transition-colors capitalize">
                        Mark {s}
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={sendReply}
                    disabled={sending || !reply.trim()}
                    className="text-xs px-4 py-1.5 rounded font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
                    style={{ background: "#5CF097", color: "var(--card)" }}
                  >
                    {sending ? "Sending…" : "Send reply"}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// User view
// ─────────────────────────────────────────────────────────────────────────────

function UserView({ currentUser }: { currentUser: UserInfo }) {
  const [tab, setTab] = useState<"submit" | "my">("submit");
  const [form, setForm] = useState({
    name: currentUser.full_name ?? currentUser.username,
    email: currentUser.email ?? "",
    subject: "", category: "question", priority: "medium", description: "",
  });
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [followUp, setFollowUp] = useState("");
  const [sendingFollowUp, setSendingFollowUp] = useState(false);

  const { data: myTickets, mutate: mutateMyTickets } = useSWR<Ticket[]>(
    "/support/my-tickets",
    () => api.get("/support/my-tickets"),
    { revalidateOnFocus: false }
  );

  function set(field: string, value: string) { setForm((f) => ({ ...f, [field]: value })); }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.post("/support/tickets", form);
      setSubmitted(true);
      mutateMyTickets();
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    setSubmitted(false);
    setForm((f) => ({ ...f, subject: "", category: "question", priority: "medium", description: "" }));
  }

  async function loadTicket(id: number) {
    const t = await api.get<Ticket>(`/support/tickets/${id}`);
    setSelectedTicket(t);
  }

  async function sendFollowUp() {
    if (!selectedTicket || !followUp.trim()) return;
    setSendingFollowUp(true);
    try {
      await api.post(`/support/tickets/${selectedTicket.id}/responses`, { message: followUp });
      setFollowUp("");
      await loadTicket(selectedTicket.id);
      mutateMyTickets();
    } finally {
      setSendingFollowUp(false);
    }
  }

  const selectedPriority = priorities.find((p) => p.value === form.priority)!;

  return (
    <div className="max-w-5xl space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-white tracking-tight mb-1">Support</h1>
        <p className="text-sm text-slate-500">Get help, report issues, or send us feedback.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2">

          {/* Tabs */}
          <div className="flex gap-1 p-1 rounded mb-5 w-fit" style={{ background: "var(--bg)" }}>
            {([["submit", "Submit a request"], ["my", `My tickets${myTickets?.length ? ` (${myTickets.length})` : ""}`]] as const).map(([t, l]) => (
              <button key={t} onClick={() => { setTab(t); setSelectedTicket(null); }}
                className="px-4 py-1.5 rounded text-xs font-medium transition-colors"
                style={tab === t ? { background: "var(--card)", color: "var(--text)" } : { color: "var(--text-dim)" }}>
                {l}
              </button>
            ))}
          </div>

          {/* Submit tab */}
          {tab === "submit" && (
            <div className="rounded-lg border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
              <div className="px-6 py-4 border-b border-white/5">
                <p className="text-sm font-medium text-white">Submit a support request</p>
                <p className="text-xs text-slate-500 mt-0.5">We typically respond within 1–2 business days.</p>
              </div>

              {submitted ? (
                <div className="px-6 py-14 text-center">
                  <div className="w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4" style={{ background: "rgba(92,240,151,0.12)" }}>
                    <svg className="w-6 h-6" style={{ color: "#5CF097" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <p className="text-base font-semibold text-white mb-2">Request received</p>
                  <p className="text-sm text-slate-500 mb-6">We&apos;ll reply to <span className="text-slate-300">{form.email}</span> soon.</p>
                  <div className="flex gap-3 justify-center">
                    <button onClick={reset} className="text-xs px-4 py-2 rounded border border-white/10 text-slate-400 hover:text-white transition-colors">
                      Submit another
                    </button>
                    <button onClick={() => setTab("my")} className="text-xs px-4 py-2 rounded font-medium" style={{ background: "#5CF097", color: "var(--card)" }}>
                      View my tickets
                    </button>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="px-6 py-6 space-y-5">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className={labelCls}>Your name</label>
                      <input required value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Full name"
                        className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600" style={inputStyle} />
                    </div>
                    <div>
                      <label className={labelCls}>Email address</label>
                      <input required type="email" value={form.email} onChange={(e) => set("email", e.target.value)} placeholder="you@company.com"
                        className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600" style={inputStyle} />
                    </div>
                  </div>
                  <div>
                    <label className={labelCls}>Subject</label>
                    <input required value={form.subject} onChange={(e) => set("subject", e.target.value)} placeholder="Briefly describe your issue"
                      className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600" style={inputStyle} />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className={labelCls}>Category</label>
                      <select value={form.category} onChange={(e) => set("category", e.target.value)} className="w-full px-3 py-2 text-sm outline-none" style={inputStyle}>
                        {categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className={labelCls}>Priority</label>
                      <select value={form.priority} onChange={(e) => set("priority", e.target.value)} className="w-full px-3 py-2 text-sm outline-none" style={inputStyle}>
                        {priorities.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-2 rounded text-xs"
                    style={{ background: `${selectedPriority.color}10`, border: `1px solid ${selectedPriority.color}25` }}>
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: selectedPriority.color }} />
                    <span style={{ color: selectedPriority.color }}>{selectedPriority.label}</span>
                  </div>
                  <div>
                    <label className={labelCls}>Description <span className="text-slate-600 font-normal">(be as specific as possible)</span></label>
                    <textarea required rows={6} value={form.description} onChange={(e) => set("description", e.target.value)}
                      placeholder="Describe the issue in detail. Include steps to reproduce, expected vs actual behaviour, and any error messages."
                      className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600 resize-none" style={inputStyle} />
                  </div>
                  <button type="submit" disabled={submitting}
                    className="px-5 py-2.5 rounded text-sm font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
                    style={{ background: "#5CF097", color: "var(--card)" }}>
                    {submitting ? "Sending…" : "Submit request"}
                  </button>
                </form>
              )}
            </div>
          )}

          {/* My tickets tab */}
          {tab === "my" && !selectedTicket && (
            <div className="rounded-lg border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
              <div className="px-6 py-4 border-b border-white/5">
                <p className="text-sm font-medium text-white">My tickets</p>
              </div>
              {!myTickets ? (
                <div className="p-6 space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-12 rounded animate-pulse" style={{ background: "var(--bg)" }} />)}</div>
              ) : myTickets.length === 0 ? (
                <div className="px-6 py-10 text-center">
                  <p className="text-sm text-slate-600 mb-3">No tickets yet.</p>
                  <button onClick={() => setTab("submit")} className="text-xs px-4 py-2 rounded font-medium" style={{ background: "#5CF097", color: "var(--card)" }}>
                    Submit a request
                  </button>
                </div>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr style={{ background: "var(--bg)" }}>
                      {["Subject", "Category", "Priority", "Status", "Replies", "Created"].map((h) => (
                        <th key={h} className="text-left px-4 py-3 text-slate-500 font-medium border-b border-white/5">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {myTickets.map((t) => (
                      <tr key={t.id} onClick={() => loadTicket(t.id)}
                        className="cursor-pointer hover:bg-white/5 transition-colors border-b border-white/5 last:border-0">
                        <td className="px-4 py-3 text-white font-medium">{t.subject}</td>
                        <td className="px-4 py-3 text-slate-500">{categories.find(c => c.value === t.category)?.label}</td>
                        <td className="px-4 py-3">
                          <span className="font-mono capitalize" style={{ color: priorityColor(t.priority) }}>{t.priority}</span>
                        </td>
                        <td className="px-4 py-3"><StatusBadge status={t.status} /></td>
                        <td className="px-4 py-3 text-slate-500">{t.response_count}</td>
                        <td className="px-4 py-3 text-slate-600">{new Date(t.created_at).toLocaleDateString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Ticket detail (user) */}
          {tab === "my" && selectedTicket && (
            <div className="rounded-lg border border-white/5 overflow-hidden" style={{ background: "var(--card)" }}>
              <div className="px-6 py-4 border-b border-white/5 flex items-center gap-3">
                <button onClick={() => setSelectedTicket(null)} className="text-slate-500 hover:text-white transition-colors">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <div>
                  <p className="text-sm font-medium text-white">{selectedTicket.subject}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <StatusBadge status={selectedTicket.status} />
                    <span className="text-xs text-slate-600">#{selectedTicket.id}</span>
                  </div>
                </div>
              </div>
              <div className="px-6 py-4 space-y-4 max-h-96 overflow-y-auto">
                <div className="rounded-lg p-4 border border-white/5" style={{ background: "var(--bg)" }}>
                  <p className="text-xs font-medium text-white mb-1">{selectedTicket.name} <span className="text-slate-600 font-normal">(you)</span></p>
                  <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-wrap">{selectedTicket.description}</p>
                </div>
                {selectedTicket.responses.map((r) => (
                  <div key={r.id} className={`rounded-lg p-4 border ${r.is_staff ? "border-[#5CF097]/30" : "border-white/5"}`}
                    style={{ background: r.is_staff ? "rgba(92,240,151,0.04)" : "var(--card)" }}>
                    <div className="flex items-center gap-2 mb-1">
                      <p className="text-xs font-medium text-white">{r.responder_name}</p>
                      {r.is_staff && <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: "rgba(92,240,151,0.1)", color: "#5CF097" }}>staff</span>}
                      <span className="text-xs text-slate-600 ml-auto">{fmt(r.created_at)}</span>
                    </div>
                    <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-wrap">{r.message}</p>
                  </div>
                ))}
              </div>
              {selectedTicket.status !== "closed" && selectedTicket.status !== "resolved" && (
                <div className="px-6 py-4 border-t border-white/5">
                  <textarea rows={3} value={followUp} onChange={(e) => setFollowUp(e.target.value)}
                    placeholder="Add a follow-up message…"
                    className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600 resize-none rounded mb-3" style={inputStyle} />
                  <button onClick={sendFollowUp} disabled={sendingFollowUp || !followUp.trim()}
                    className="text-xs px-4 py-1.5 rounded font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
                    style={{ background: "#5CF097", color: "var(--card)" }}>
                    {sendingFollowUp ? "Sending…" : "Send follow-up"}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Contact cards */}
        <div className="space-y-4">
          <div className="rounded-lg border border-white/5 p-5" style={{ background: "var(--card)" }}>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded flex items-center justify-center shrink-0 mt-0.5" style={{ background: "rgba(92,240,151,0.1)" }}>
                <svg className="w-4 h-4" style={{ color: "#5CF097" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-medium text-white mb-0.5">Email support</p>
                <p className="text-xs text-slate-500 mb-2">For non-urgent issues and billing questions.</p>
                <a href="mailto:support@seraph.io" className="text-xs font-mono hover:text-white transition-colors" style={{ color: "#5CF097" }}>support@seraph.io</a>
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-white/5 p-5" style={{ background: "var(--card)" }}>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded flex items-center justify-center shrink-0 mt-0.5" style={{ background: "rgba(248,113,113,0.1)" }}>
                <svg className="w-4 h-4" style={{ color: "#f87171" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-medium text-white mb-0.5">Security disclosures</p>
                <p className="text-xs text-slate-500 mb-2">Found a vulnerability? Please reach out privately.</p>
                <a href="mailto:security@seraph.io" className="text-xs font-mono hover:text-white transition-colors" style={{ color: "#f87171" }}>security@seraph.io</a>
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-white/5 p-5" style={{ background: "var(--card)" }}>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded flex items-center justify-center shrink-0 mt-0.5" style={{ background: "rgba(148,163,184,0.08)" }}>
                <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-medium text-white mb-0.5">Documentation</p>
                <p className="text-xs text-slate-500 mb-2">API reference, scanner guides, integration examples.</p>
                <a href="/docs" className="text-xs font-mono hover:text-white transition-colors" style={{ color: "var(--text-muted)" }}>/docs →</a>
              </div>
            </div>
          </div>
          <div className="rounded-lg px-4 py-3 border border-white/5" style={{ background: "rgba(92,240,151,0.03)" }}>
            <p className="text-xs text-slate-600 leading-relaxed">
              <span className="text-slate-500 font-medium">Response times:</span> Urgent &lt;4h · High &lt;24h · Medium &lt;2 days · Low &lt;5 days
            </p>
          </div>
        </div>
      </div>

    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Root — pick view based on role
// ─────────────────────────────────────────────────────────────────────────────

export default function SupportPage() {
  const { data: user } = useSWR<UserInfo>("/auth/me", () => api.get<UserInfo>("/auth/me"), { revalidateOnFocus: false });

  if (!user) return <div className="h-32 rounded animate-pulse" style={{ background: "var(--card)" }} />;

  const isStaff = user.role === "admin" || user.role === "support";
  return isStaff ? <StaffView currentUser={user} /> : <UserView currentUser={user} />;
}
