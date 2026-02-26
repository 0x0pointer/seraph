"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";

interface UnifiedNotif {
  id: number;
  source: "notification" | "announcement";
  type: string;
  title: string;
  body: string | null;
  ticket_id: number | null;
  is_read: boolean;
  created_at: string;
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const TYPE_STYLE: Record<string, { icon: string; color: string; bg: string; label: string }> = {
  ticket_new:      { icon: "✦", color: "#14B8A6", bg: "rgba(20,184,166,0.12)",  label: "New ticket" },
  ticket_response: { icon: "↩", color: "#a78bfa", bg: "rgba(167,139,250,0.12)", label: "Reply" },
  ticket_followup: { icon: "↪", color: "#fbbf24", bg: "rgba(251,191,36,0.12)",  label: "Follow-up" },
  announcement:    { icon: "!",  color: "#f97316", bg: "rgba(249,115,22,0.12)",  label: "Announcement" },
  news:            { icon: "★",  color: "#a78bfa", bg: "rgba(167,139,250,0.12)", label: "News" },
};

function getStyle(type: string) {
  return TYPE_STYLE[type] ?? TYPE_STYLE.ticket_new;
}

// Group notifications by source type for section headers
type Group = { label: string; items: UnifiedNotif[] };

function groupNotifs(items: UnifiedNotif[]): Group[] {
  const announcements = items.filter((n) => n.source === "announcement");
  const personal = items.filter((n) => n.source === "notification");

  const groups: Group[] = [];
  if (announcements.length) groups.push({ label: "Announcements & News", items: announcements });
  if (personal.length) groups.push({ label: "Activity", items: personal });
  return groups;
}

export default function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const { data: countData, mutate: mutateCount } = useSWR<{ count: number }>(
    "/notifications/unread-count",
    () => api.get("/notifications/unread-count"),
    { refreshInterval: 20000 },
  );

  const { data: notifications, mutate: mutateList } = useSWR<UnifiedNotif[]>(
    open ? "/notifications" : null,
    () => api.get("/notifications"),
    { revalidateOnFocus: false },
  );

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const count = countData?.count ?? 0;

  async function handleClick(n: UnifiedNotif) {
    if (!n.is_read) {
      if (n.source === "announcement") {
        await api.patch(`/notifications/announcements/${n.id}/read`, {});
      } else {
        await api.patch(`/notifications/${n.id}/read`, {});
      }
      mutateList();
      mutateCount();
    }
    setOpen(false);
    if (n.ticket_id || n.source === "notification") router.push("/dashboard/support");
  }

  async function markAllRead() {
    await api.patch("/notifications/read-all/mark", {});
    mutateList();
    mutateCount();
  }

  const groups = notifications ? groupNotifs(notifications) : [];
  const totalItems = notifications?.length ?? 0;

  return (
    <div ref={ref} className="relative">
      {/* Bell */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex items-center justify-center w-8 h-8 rounded transition-colors hover:bg-white/5"
        aria-label="Notifications"
      >
        <svg
          className="w-4 h-4"
          style={{ color: count > 0 ? "#e2e8f0" : "#475569" }}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {count > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 flex items-center justify-center rounded-full text-white font-bold"
            style={{ background: "#f87171", fontSize: "9px", minWidth: count > 9 ? "16px" : "14px", height: "14px", padding: "0 3px", lineHeight: 1 }}
          >
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute right-0 top-10 w-84 rounded-lg border border-white/5 overflow-hidden shadow-2xl z-50"
          style={{ background: "#0d1426", width: "340px" }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <p className="text-xs font-semibold text-white">
              Notifications
              {count > 0 && (
                <span className="ml-2 text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: "rgba(248,113,113,0.1)", color: "#f87171" }}>
                  {count} unread
                </span>
              )}
            </p>
            {count > 0 && (
              <button onClick={markAllRead} className="text-xs text-slate-500 hover:text-white transition-colors">
                Mark all read
              </button>
            )}
          </div>

          {/* Body */}
          <div className="max-h-96 overflow-y-auto">
            {!notifications ? (
              <div className="p-4 space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-12 rounded animate-pulse" style={{ background: "#0A0F1F" }} />
                ))}
              </div>
            ) : totalItems === 0 ? (
              <div className="px-4 py-10 text-center">
                <p className="text-xs text-slate-600">Nothing here yet.</p>
              </div>
            ) : (
              groups.map((group) => (
                <div key={group.label}>
                  {/* Section header */}
                  <div className="px-4 py-2 border-b border-white/5" style={{ background: "#0A0F1F" }}>
                    <p className="text-xs font-mono uppercase tracking-widest" style={{ color: "#334155" }}>
                      {group.label}
                    </p>
                  </div>

                  {group.items.map((n) => {
                    const s = getStyle(n.type);
                    return (
                      <button
                        key={`${n.source}-${n.id}`}
                        onClick={() => handleClick(n)}
                        className="w-full flex items-start gap-3 px-4 py-3 border-b border-white/5 last:border-0 text-left transition-colors hover:bg-white/5"
                        style={!n.is_read ? { background: "rgba(255,255,255,0.015)" } : {}}
                      >
                        {/* Icon */}
                        <div
                          className="w-7 h-7 rounded flex items-center justify-center shrink-0 mt-0.5 text-sm font-bold"
                          style={{ background: s.bg, color: s.color }}
                        >
                          {s.icon}
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <span
                                className="text-xs font-mono mr-1.5 px-1 py-0.5 rounded"
                                style={{ background: s.bg, color: s.color, fontSize: "9px" }}
                              >
                                {s.label}
                              </span>
                              <p className={`text-xs leading-snug mt-0.5 ${n.is_read ? "text-slate-400" : "text-white font-medium"}`}>
                                {n.title}
                              </p>
                            </div>
                            {!n.is_read && (
                              <span className="w-1.5 h-1.5 rounded-full shrink-0 mt-1" style={{ background: "#14B8A6" }} />
                            )}
                          </div>
                          {n.body && (
                            <p className="text-xs text-slate-600 mt-0.5 line-clamp-2 leading-relaxed">{n.body}</p>
                          )}
                          <p className="text-xs mt-1" style={{ color: "#2d3f52" }}>{timeAgo(n.created_at)}</p>
                        </div>
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          {totalItems > 0 && (
            <div className="px-4 py-2.5 border-t border-white/5 flex items-center justify-between">
              <button
                onClick={() => { setOpen(false); router.push("/dashboard/support"); }}
                className="text-xs text-slate-500 hover:text-white transition-colors"
              >
                Go to Support →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
