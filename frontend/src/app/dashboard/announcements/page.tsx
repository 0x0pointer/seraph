"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

interface Announcement {
  id: number;
  title: string;
  body: string | null;
  type: string;
  created_by_name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

const TYPE_META: Record<string, { label: string; color: string; bg: string; desc: string }> = {
  announcement: { label: "Announcement", color: "#f97316", bg: "rgba(249,115,22,0.1)", desc: "Important platform messages shown to all users" },
  news:         { label: "News & Updates", color: "#a78bfa", bg: "rgba(167,139,250,0.1)", desc: "Product updates, new features, and changelog" },
};

function fmt(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

const inputStyle = {
  background: "#0A0F1F",
  border: "1px solid rgba(255,255,255,0.08)",
  color: "#e2e8f0",
  borderRadius: "6px",
} as const;

const labelCls = "block text-xs font-medium text-slate-400 mb-1.5";

export default function AnnouncementsPage() {
  const { data: items, mutate } = useSWR<Announcement[]>(
    "/announcements",
    () => api.get("/announcements"),
    { revalidateOnFocus: false },
  );

  const [editing, setEditing] = useState<Announcement | null>(null);
  const [creating, setCreating] = useState(false);

  // Form state
  const [form, setForm] = useState({ title: "", body: "", type: "announcement" });
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Announcement | null>(null);
  const [toggling, setToggling] = useState<number | null>(null);

  function set(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  function openCreate() {
    setForm({ title: "", body: "", type: "announcement" });
    setEditing(null);
    setCreating(true);
  }

  function openEdit(item: Announcement) {
    setForm({ title: item.title, body: item.body ?? "", type: item.type });
    setEditing(item);
    setCreating(true);
  }

  function cancelForm() { setCreating(false); setEditing(null); }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      if (editing) {
        await api.put(`/announcements/${editing.id}`, form);
      } else {
        await api.post("/announcements", form);
      }
      await mutate();
      setCreating(false);
      setEditing(null);
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(item: Announcement) {
    setToggling(item.id);
    try { await api.patch(`/announcements/${item.id}/toggle`, {}); await mutate(); }
    finally { setToggling(null); }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    await api.delete(`/announcements/${deleteTarget.id}`);
    await mutate();
    setDeleteTarget(null);
  }

  const active = items?.filter((i) => i.is_active).length ?? 0;
  const archived = items?.filter((i) => !i.is_active).length ?? 0;

  return (
    <div className="max-w-4xl space-y-8">

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white tracking-tight mb-1">Announcements</h1>
          <p className="text-sm text-slate-500">Broadcast announcements and news to all users via the notification bell.</p>
        </div>
        <button
          onClick={openCreate}
          className="px-4 py-2 rounded text-sm font-medium shrink-0 transition-opacity hover:opacity-90"
          style={{ background: "#14B8A6", color: "#0A0F1F" }}
        >
          + New announcement
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total created", value: items?.length ?? "—", color: "#94a3b8" },
          { label: "Currently active", value: active, color: "#14B8A6" },
          { label: "Archived", value: archived, color: "#475569" },
        ].map((s) => (
          <div key={s.label} className="rounded-lg px-5 py-4 border border-white/5" style={{ background: "#0d1426" }}>
            <p className="text-2xl font-bold tracking-tight" style={{ color: s.color }}>{String(s.value)}</p>
            <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Type legend */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {Object.entries(TYPE_META).map(([key, meta]) => (
          <div key={key} className="flex items-start gap-3 rounded-lg px-4 py-3 border border-white/5" style={{ background: "#0d1426" }}>
            <span className="text-xs font-mono px-2 py-0.5 rounded shrink-0 mt-0.5" style={{ background: meta.bg, color: meta.color }}>
              {meta.label}
            </span>
            <p className="text-xs text-slate-500">{meta.desc}</p>
          </div>
        ))}
      </div>

      {/* Create / Edit form */}
      {creating && (
        <div className="rounded-lg border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
          <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
            <p className="text-sm font-medium text-white">{editing ? "Edit announcement" : "New announcement"}</p>
            <button onClick={cancelForm} className="text-slate-500 hover:text-white transition-colors text-lg leading-none">×</button>
          </div>
          <form onSubmit={handleSave} className="px-6 py-6 space-y-5">
            {/* Type selector */}
            <div>
              <label className={labelCls}>Type</label>
              <div className="flex gap-3">
                {Object.entries(TYPE_META).map(([key, meta]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => set("type", key)}
                    className="flex-1 py-2.5 px-4 rounded border text-xs font-medium transition-colors text-left"
                    style={
                      form.type === key
                        ? { background: meta.bg, borderColor: meta.color, color: meta.color }
                        : { background: "transparent", borderColor: "rgba(255,255,255,0.08)", color: "#475569" }
                    }
                  >
                    <span className="block font-semibold mb-0.5">{meta.label}</span>
                    <span className="font-normal opacity-80">{meta.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Title */}
            <div>
              <label className={labelCls}>Title</label>
              <input
                required
                value={form.title}
                onChange={(e) => set("title", e.target.value)}
                placeholder="e.g. Scheduled maintenance on March 1st"
                className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600"
                style={inputStyle}
              />
            </div>

            {/* Body */}
            <div>
              <label className={labelCls}>
                Body <span className="text-slate-600 font-normal">(optional — shown as preview under the title)</span>
              </label>
              <textarea
                rows={4}
                value={form.body}
                onChange={(e) => set("body", e.target.value)}
                placeholder="Additional details, links, or context…"
                className="w-full px-3 py-2 text-sm outline-none placeholder:text-slate-600 resize-none"
                style={inputStyle}
              />
            </div>

            {/* Preview */}
            {form.title && (
              <div>
                <label className={labelCls}>Preview in notification bell</label>
                <div className="flex items-start gap-3 p-3 rounded border border-white/5" style={{ background: "#0A0F1F" }}>
                  <div
                    className="w-7 h-7 rounded flex items-center justify-center shrink-0 text-sm font-bold"
                    style={{ background: TYPE_META[form.type]?.bg, color: TYPE_META[form.type]?.color }}
                  >
                    {form.type === "announcement" ? "!" : "★"}
                  </div>
                  <div>
                    <p className="text-xs font-medium text-white">{form.title}</p>
                    {form.body && <p className="text-xs text-slate-600 mt-0.5 line-clamp-2">{form.body}</p>}
                    <p className="text-xs mt-1" style={{ color: "#334155" }}>just now</p>
                  </div>
                </div>
              </div>
            )}

            <div className="flex items-center gap-3 pt-1">
              <button
                type="submit"
                disabled={saving || !form.title.trim()}
                className="px-5 py-2 rounded text-sm font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ background: "#14B8A6", color: "#0A0F1F" }}
              >
                {saving ? "Saving…" : editing ? "Save changes" : "Publish announcement"}
              </button>
              <button type="button" onClick={cancelForm} className="text-sm text-slate-500 hover:text-white transition-colors">
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* List */}
      <div className="rounded-lg border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
        <div className="px-6 py-4 border-b border-white/5">
          <p className="text-sm font-medium text-white">All announcements</p>
        </div>

        {!items ? (
          <div className="p-6 space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-14 rounded animate-pulse" style={{ background: "#0A0F1F" }} />)}</div>
        ) : items.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-sm text-slate-600 mb-2">No announcements yet.</p>
            <button onClick={openCreate} className="text-xs" style={{ color: "#14B8A6" }}>Create your first one →</button>
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr style={{ background: "#0A0F1F" }}>
                {["Type", "Title", "Created by", "Date", "Status", "Actions"].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-slate-500 font-medium border-b border-white/5">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const meta = TYPE_META[item.type] ?? TYPE_META.announcement;
                return (
                  <tr key={item.id} className="border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors">
                    <td className="px-4 py-3">
                      <span className="font-mono px-2 py-0.5 rounded" style={{ background: meta.bg, color: meta.color }}>
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium text-white">{item.title}</p>
                      {item.body && <p className="text-slate-600 mt-0.5 max-w-xs truncate">{item.body}</p>}
                    </td>
                    <td className="px-4 py-3 text-slate-500">{item.created_by_name}</td>
                    <td className="px-4 py-3 text-slate-600 whitespace-nowrap">{fmt(item.created_at)}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleToggle(item)}
                        disabled={toggling === item.id}
                        className="font-mono px-2 py-0.5 rounded border transition-colors disabled:opacity-50"
                        style={
                          item.is_active
                            ? { background: "rgba(20,184,166,0.08)", color: "#14B8A6", borderColor: "rgba(20,184,166,0.2)" }
                            : { background: "rgba(71,85,105,0.15)", color: "#64748b", borderColor: "rgba(255,255,255,0.06)" }
                        }
                      >
                        {toggling === item.id ? "…" : item.is_active ? "Active" : "Archived"}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <button onClick={() => openEdit(item)} className="text-slate-500 hover:text-white transition-colors">
                          Edit
                        </button>
                        <button onClick={() => setDeleteTarget(item)} className="hover:text-white transition-colors" style={{ color: "#f87171" }}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Delete confirm */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.7)" }}>
          <div className="rounded-lg border border-white/10 p-6 max-w-sm w-full mx-4" style={{ background: "#0d1426" }}>
            <p className="text-sm font-semibold text-white mb-2">Delete announcement?</p>
            <p className="text-xs text-slate-500 mb-5">
              &ldquo;{deleteTarget.title}&rdquo; will be permanently removed from all notification feeds.
            </p>
            <div className="flex gap-3">
              <button onClick={handleDelete}
                className="flex-1 py-2 rounded text-sm font-medium"
                style={{ background: "rgba(248,113,113,0.15)", color: "#f87171", border: "1px solid rgba(248,113,113,0.3)" }}>
                Delete
              </button>
              <button onClick={() => setDeleteTarget(null)}
                className="flex-1 py-2 rounded text-sm border border-white/10 text-slate-400 hover:text-white transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
