"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useRef, useEffect } from "react";
import Cookies from "js-cookie";
import useSWR, { mutate } from "swr";
import { api } from "@/lib/api";
import NotificationBell from "@/components/dashboard/NotificationBell";
import ThemeToggle from "@/components/dashboard/ThemeToggle";

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
  { href: "/dashboard/settings", label: "Settings" },
];

const adminNavItems = [
  { href: "/dashboard/admin", label: "Admin Panel" },
  { href: "/dashboard/announcements", label: "Announcements" },
];

const orgNavItem = { href: "/dashboard/organization", label: "Organization" };

function NavIcon({ href, active }: Readonly<{ href: string; active: boolean }>) {
  const color = active ? "var(--purple)" : "var(--text-dim)";
  const w = "w-4 h-4 shrink-0";
  if (href === "/dashboard")
    return <svg className={w} style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor"><rect x="3" y="3" width="7" height="7" rx="1" strokeWidth={1.5}/><rect x="14" y="3" width="7" height="7" rx="1" strokeWidth={1.5}/><rect x="3" y="14" width="7" height="7" rx="1" strokeWidth={1.5}/><rect x="14" y="14" width="7" height="7" rx="1" strokeWidth={1.5}/></svg>;
  if (href.includes("guardrails"))
    return <svg className={w} style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>;
  if (href.includes("audit"))
    return <svg className={w} style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>;
  if (href.includes("abuse"))
    return <svg className={w} style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>;
  if (href.includes("analytics"))
    return <svg className={w} style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>;
  if (href.includes("apis"))
    return <svg className={w} style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>;
  if (href.includes("organization"))
    return <svg className={w} style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>;
  return null;
}

function OrgSwitcher({ user }: { user: UserInfo }) {
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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
        className="w-full flex items-center justify-between gap-1 px-1 py-0.5 rounded text-left transition-colors"
        style={{ minWidth: 0 }}
      >
        <span className="text-xs font-medium truncate" style={{ color: "var(--purple)" }}>
          {switching ? "Switching…" : (activeOrg?.name ?? "No organization")}
        </span>
        <svg
          className="w-3 h-3 shrink-0 transition-transform"
          style={{ color: "var(--purple)", transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-50 rounded-lg overflow-hidden shadow-xl"
          style={{ background: "var(--bg)", border: "1px solid var(--border-input)", minWidth: "160px" }}
        >
          {otherOrgs.map((org) => (
            <button
              key={org.id}
              onClick={() => switchTo(org.id)}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors"
              style={{ color: "var(--text-muted)" }}
            >
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: "var(--purple)" }} />
              <span className="truncate">{org.name}</span>
              <span className="ml-auto font-mono capitalize shrink-0" style={{ color: "var(--text-dim)" }}>{org.role.replace("org_", "")}</span>
            </button>
          ))}
          {user.org_id !== null && (
            <>
              {otherOrgs.length > 0 && <div style={{ borderTop: "1px solid var(--border)" }} />}
              <button
                onClick={() => switchTo(null)}
                className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors"
                style={{ color: "var(--text-dim)" }}
              >
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: "var(--text-dim)" }} />
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

  const { data: notifCount } = useSWR<{ count: number }>(
    "/notifications/unread-count",
    () => api.get<{ count: number }>("/notifications/unread-count"),
    { refreshInterval: 20000, revalidateOnFocus: false },
  );

  const adminToken = typeof window !== "undefined" ? Cookies.get("admin_token") : undefined;
  const impersonatingUser = typeof window !== "undefined" ? Cookies.get("impersonating_user") : undefined;

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
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Sidebar */}
      <aside
        className="w-56 flex flex-col shrink-0"
        style={{ background: "var(--card)", borderRight: "1px solid var(--border)" }}
      >
        {/* Logo */}
        <div className="px-5 py-5" style={{ borderBottom: "1px solid var(--border)" }}>
          <Link href="/" className="flex items-center gap-2.5">
            <span className="w-5 h-5 rounded-sm" style={{ background: "var(--purple)" }} />
            <span className="font-semibold text-sm tracking-tight" style={{ color: "var(--text)" }}>Seraph</span>
            <span
              className="font-mono font-bold tracking-widest px-1 py-0.5 rounded"
              style={{ background: "rgba(92,240,151,0.15)", color: "var(--purple)", fontSize: "0.55rem", letterSpacing: "0.1em" }}
            >BETA</span>
          </Link>
          {user && user.orgs && user.orgs.length > 0 && (
            <OrgSwitcher user={user} />
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {navItems.map((item) => {
            const active = isActive(item);
            return (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors"
                style={{
                  background: active ? "rgba(92,240,151,0.08)" : "transparent",
                  color: active ? "var(--purple)" : "var(--text-muted)",
                  borderLeft: active ? "2px solid var(--purple)" : "2px solid transparent",
                  fontWeight: active ? 500 : 400,
                }}
              >
                <NavIcon href={item.href} active={active} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Bottom nav */}
        <div className="px-3 pb-2 space-y-0.5">
          <div className="mx-2 mb-3" style={{ borderTop: "1px solid var(--border)" }} />

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
                  background: active ? "rgba(92,240,151,0.1)" : "transparent",
                  color: active ? "var(--purple)" : "var(--text-muted)",
                  borderLeft: active ? "2px solid var(--purple)" : "2px solid transparent",
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

          {user?.role === "admin" && (
            <>
              <div className="mx-2 my-2" style={{ borderTop: "1px solid var(--border)" }} />
              {adminNavItems.map((item) => {
                const active = isActive(item);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors"
                    style={{
                      background: active ? "rgba(248,113,113,0.08)" : "transparent",
                      color: active ? "#f87171" : "var(--text-dim)",
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
        <div className="px-3 py-4 space-y-2" style={{ borderTop: "1px solid var(--border)" }}>
          {user ? (
            <div className="px-3 py-2.5 rounded space-y-1" style={{ background: "var(--card2)" }}>
              <div className="flex items-center gap-2">
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                  style={{
                    background: user.role === "admin" ? "rgba(248,113,113,0.2)" : "rgba(92,240,151,0.15)",
                    color: user.role === "admin" ? "#f87171" : "var(--purple)",
                  }}
                >
                  {user.username[0].toUpperCase()}
                </div>
                <p className="text-xs truncate font-medium" style={{ color: "var(--text)" }}>
                  {user.full_name ?? user.username}
                </p>
              </div>
              <div className="flex items-center justify-between">
                <span
                  className="text-xs font-mono px-1.5 py-0.5 rounded capitalize"
                  style={
                    user.role === "admin"
                      ? { background: "rgba(248,113,113,0.1)", color: "#f87171" }
                      : { background: "rgba(92,240,151,0.1)", color: "var(--purple)" }
                  }
                >
                  {user.role}
                </span>
                <span className="text-xs font-mono truncate ml-2" style={{ color: "var(--text-dim)" }}>
                  @{user.username}
                </span>
              </div>
            </div>
          ) : (
            <div className="h-14 rounded animate-pulse" style={{ background: "var(--card2)" }} />
          )}
          <button
            onClick={handleLogout}
            className="w-full text-left px-3 py-2 rounded text-xs transition-colors hover:opacity-80"
            style={{ color: "var(--text-dim)" }}
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header
          className="flex items-center justify-between px-8 py-4 shrink-0"
          style={{ background: "var(--card)", borderBottom: "1px solid var(--border)" }}
        >
          <h1 className="text-sm font-medium" style={{ color: "var(--text)" }}>{currentTitle}</h1>
          <div className="flex items-center gap-3">
            {user?.role === "admin" && (
              <span
                className="text-xs font-mono px-2 py-0.5 rounded"
                style={{ background: "rgba(248,113,113,0.08)", color: "#f87171" }}
              >
                admin
              </span>
            )}
            <ThemeToggle />
            <NotificationBell />
            <button
              onClick={handleLogout}
              className="text-xs transition-colors hover:opacity-70"
              style={{ color: "var(--text-dim)" }}
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
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <p className="text-xs" style={{ color: "#fbbf24" }}>
                Impersonating <span className="font-mono font-semibold">{impersonatingUser}</span>
              </p>
            </div>
            <button onClick={exitImpersonation}
              className="text-xs font-medium px-3 py-1 rounded transition-colors"
              style={{ background: "rgba(251,191,36,0.15)", color: "#fbbf24", border: "1px solid rgba(251,191,36,0.3)" }}>
              Exit impersonation
            </button>
          </div>
        )}

        <main className="flex-1 overflow-y-auto p-8" style={{ background: "var(--bg)" }}>
          {children}
        </main>
      </div>
    </div>
  );
}
