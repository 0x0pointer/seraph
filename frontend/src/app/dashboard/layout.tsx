"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useRef, useEffect } from "react";
import Cookies from "js-cookie";
import useSWR, { mutate } from "swr";
import { api } from "@/lib/api";
import NotificationBell from "@/components/dashboard/NotificationBell";

interface OrgInfo {
  id: number;
  name: string;
  role: string;
}

interface UserInfo {
  id: number;
  username: string;
  full_name: string | null;
  email: string | null;
  role: string;
  org_id: number | null;
  team_id: number | null;
  orgs: OrgInfo[];
}

const baseNavItems = [
  { href: "/dashboard", label: "Overview", exact: true },
  { href: "/dashboard/guardrails", label: "Guardrails" },
  { href: "/dashboard/audit", label: "Audit Log" },
  { href: "/dashboard/abuse", label: "Abuse Cases" },
  { href: "/dashboard/analytics", label: "Analytics" },
  { href: "/dashboard/apis", label: "APIs" },
];

const bottomNavItems = [
  { href: "/dashboard/support", label: "Support" },
  { href: "/dashboard/billing", label: "Billing" },
  { href: "/dashboard/settings", label: "Settings" },
];

const adminNavItems = [
  { href: "/dashboard/admin", label: "Admin Panel" },
  { href: "/dashboard/announcements", label: "Announcements" },
];

const orgNavItem = { href: "/dashboard/organization", label: "Organization" };

function OrgSwitcher({ user }: { user: UserInfo }) {
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (!user.orgs || user.orgs.length === 0) return null;

  const activeOrg = user.orgs.find((o) => o.id === user.org_id);
  const otherOrgs = user.orgs.filter((o) => o.id !== user.org_id);

  async function switchTo(orgId: number | null) {
    setSwitching(true);
    setOpen(false);
    try {
      await api.patch("/auth/switch-org", { org_id: orgId });
      // Revalidate all SWR caches that depend on org context
      await mutate("/auth/me");
      await mutate("/auth/plan");
      await mutate("/org");
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div ref={ref} className="relative mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={switching}
        className="w-full flex items-center justify-between gap-1 px-1 py-0.5 rounded text-left transition-colors hover:bg-white/5"
        style={{ minWidth: 0 }}
      >
        <span className="text-xs font-medium truncate" style={{ color: "#14B8A6" }}>
          {switching ? "Switching…" : (activeOrg?.name ?? "No organization")}
        </span>
        <svg
          className="w-3 h-3 shrink-0 transition-transform"
          style={{ color: "#14B8A6", transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-50 rounded-lg border border-white/10 overflow-hidden shadow-xl"
          style={{ background: "#0A0F1F", minWidth: "160px" }}
        >
          {otherOrgs.map((org) => (
            <button
              key={org.id}
              onClick={() => switchTo(org.id)}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs text-slate-300 hover:bg-white/5 transition-colors"
            >
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: "#14B8A6" }} />
              <span className="truncate">{org.name}</span>
              <span className="ml-auto text-slate-600 font-mono capitalize shrink-0">{org.role.replace("org_", "")}</span>
            </button>
          ))}
          {user.org_id !== null && (
            <>
              {otherOrgs.length > 0 && <div className="border-t border-white/5" />}
              <button
                onClick={() => switchTo(null)}
                className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs text-slate-500 hover:bg-white/5 transition-colors"
              >
                <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-slate-700" />
                Personal (no org)
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const { data: user } = useSWR<UserInfo>(
    "/auth/me",
    () => api.get<UserInfo>("/auth/me"),
    { revalidateOnFocus: false },
  );

  // Shared with NotificationBell — SWR deduplicates the request automatically
  const { data: notifCount } = useSWR<{ count: number }>(
    "/notifications/unread-count",
    () => api.get<{ count: number }>("/notifications/unread-count"),
    { refreshInterval: 20000, revalidateOnFocus: false },
  );

  const adminToken = typeof window !== "undefined" ? Cookies.get("admin_token") : undefined;
  const impersonatingUser = typeof window !== "undefined" ? Cookies.get("impersonating_user") : undefined;

  // Build nav items: inject Organization link for users who belong to an org
  const navItems = user?.org_id ? [...baseNavItems, orgNavItem] : baseNavItems;
  const allNavItems = [...navItems, ...bottomNavItems, ...adminNavItems];

  function handleLogout() {
    Cookies.remove("token");
    Cookies.remove("admin_token");
    Cookies.remove("impersonating_user");
    router.push("/login");
  }

  function exitImpersonation() {
    const orig = Cookies.get("admin_token");
    if (orig) {
      Cookies.set("token", orig, { expires: 1 });
      Cookies.remove("admin_token");
      Cookies.remove("impersonating_user");
      router.push("/dashboard");
      router.refresh();
    }
  }

  function isActive(item: { href: string; exact?: boolean }) {
    return item.exact ? pathname === item.href : pathname.startsWith(item.href);
  }

  const currentTitle = allNavItems.find((i) => isActive(i))?.label ?? "Dashboard";

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "#0A0F1F" }}>
      {/* Sidebar */}
      <aside className="w-56 flex flex-col border-r border-white/5 shrink-0" style={{ background: "#0d1426" }}>
        {/* Logo */}
        <div className="px-5 py-5 border-b border-white/5">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="w-5 h-5 rounded-sm" style={{ background: "#14B8A6" }} />
            <span className="text-white font-semibold text-sm tracking-tight">Project 73</span>
            <span className="font-mono font-bold tracking-widest px-1 py-0.5 rounded" style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6", fontSize: "0.55rem", letterSpacing: "0.1em" }}>BETA</span>
          </Link>
          {user && user.orgs && user.orgs.length > 0 && (
            <OrgSwitcher user={user} />
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          <p className="text-xs text-slate-600 font-mono tracking-widest uppercase px-2 mb-3">
            Navigation
          </p>
          {navItems.map((item) => {
            const active = isActive(item);
            return (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors"
                style={{
                  background: active ? "rgba(20,184,166,0.08)" : "transparent",
                  color: active ? "#14B8A6" : "#94a3b8",
                  borderLeft: active ? "2px solid #14B8A6" : "2px solid transparent",
                }}
              >
                {item.label}
              </Link>
            );
          })}

        </nav>

        {/* Bottom nav — Support · Settings · (admin: Admin Panel · Announcements) */}
        <div className="px-3 pb-2 space-y-0.5">
          <div className="mx-2 mb-3 border-t border-white/5" />

          {/* Support + Settings (all users) */}
          {bottomNavItems.map((item) => {
            const active = pathname.startsWith(item.href);
            const isSupport = item.href.includes("support");
            const unread = isSupport ? (notifCount?.count ?? 0) : 0;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors"
                style={{
                  background: active ? "rgba(20,184,166,0.08)" : "transparent",
                  color: active ? "#14B8A6" : "#94a3b8",
                  borderLeft: active ? "2px solid #14B8A6" : "2px solid transparent",
                }}
              >
                {isSupport ? (
                  <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z" />
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                )}
                <span className="flex-1">{item.label}</span>
                {isSupport && unread > 0 && (
                  <span
                    className="text-white font-bold rounded-full flex items-center justify-center shrink-0"
                    style={{ background: "#f87171", fontSize: "9px", minWidth: unread > 9 ? "16px" : "14px", height: "14px", padding: "0 3px" }}
                  >
                    {unread > 99 ? "99+" : unread}
                  </span>
                )}
              </Link>
            );
          })}

          {/* Admin Panel + Announcements (admins only) */}
          {user?.role === "admin" && (
            <>
              <div className="mx-2 my-2 border-t border-white/5" />
              {adminNavItems.map((item) => {
                const active = isActive(item);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors"
                    style={{
                      background: active ? "rgba(248,113,113,0.08)" : "transparent",
                      color: active ? "#f87171" : "#64748b",
                      borderLeft: active ? "2px solid #f87171" : "2px solid transparent",
                    }}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </>
          )}
        </div>

        {/* User info + sign out */}
        <div className="px-3 py-4 border-t border-white/5 space-y-2">
          {user ? (
            <div
              className="px-3 py-2.5 rounded space-y-1"
              style={{ background: "#0A0F1F" }}
            >
              <div className="flex items-center gap-2">
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                  style={{
                    background: user.role === "admin" ? "rgba(248,113,113,0.2)" : "rgba(20,184,166,0.15)",
                    color: user.role === "admin" ? "#f87171" : "#14B8A6",
                  }}
                >
                  {user.username[0].toUpperCase()}
                </div>
                <p className="text-xs text-white truncate font-medium">
                  {user.full_name ?? user.username}
                </p>
              </div>
              <div className="flex items-center justify-between">
                <span
                  className="text-xs font-mono px-1.5 py-0.5 rounded capitalize"
                  style={
                    user.role === "admin"
                      ? { background: "rgba(248,113,113,0.1)", color: "#f87171" }
                      : { background: "rgba(20,184,166,0.08)", color: "#14B8A6" }
                  }
                >
                  {user.role}
                </span>
                <span className="text-xs text-slate-700 font-mono truncate ml-2">
                  @{user.username}
                </span>
              </div>
            </div>
          ) : (
            <div className="h-14 rounded animate-pulse" style={{ background: "#0A0F1F" }} />
          )}
          <button
            onClick={handleLogout}
            className="w-full text-left px-3 py-2 rounded text-xs text-slate-600 hover:text-slate-400 transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header
          className="flex items-center justify-between px-8 py-4 border-b border-white/5 shrink-0"
          style={{ background: "#0d1426" }}
        >
          <h1 className="text-sm font-medium text-white">{currentTitle}</h1>
          <div className="flex items-center gap-3">
            {user?.role === "admin" && (
              <span
                className="text-xs font-mono px-2 py-0.5 rounded"
                style={{ background: "rgba(248,113,113,0.08)", color: "#f87171" }}
              >
                admin
              </span>
            )}
            <NotificationBell />
            <button
              onClick={handleLogout}
              className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
            >
              Sign out
            </button>
          </div>
        </header>
        {/* Impersonation banner */}
        {adminToken && impersonatingUser && (
          <div className="px-8 py-2.5 flex items-center justify-between shrink-0"
            style={{ background: "rgba(251,191,36,0.08)", borderBottom: "1px solid rgba(251,191,36,0.2)" }}>
            <div className="flex items-center gap-2.5">
              <svg className="w-3.5 h-3.5 shrink-0" style={{ color: "#fbbf24" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <p className="text-xs" style={{ color: "#fbbf24" }}>
                You are impersonating <span className="font-mono font-semibold">{impersonatingUser}</span>
              </p>
            </div>
            <button onClick={exitImpersonation}
              className="text-xs font-medium px-3 py-1 rounded transition-colors"
              style={{ background: "rgba(251,191,36,0.15)", color: "#fbbf24", border: "1px solid rgba(251,191,36,0.3)" }}>
              Exit impersonation
            </button>
          </div>
        )}
        <main className="flex-1 overflow-y-auto p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
