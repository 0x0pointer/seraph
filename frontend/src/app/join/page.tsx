"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Cookies from "js-cookie";
import Link from "next/link";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

interface InviteInfo {
  email: string;
  role: string;
  org_name: string;
  invited_by: string | null;
}

const ROLE_LABEL: Record<string, string> = {
  org_admin: "Org Admin",
  viewer: "Member",
};

function JoinPageContent() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("invite") ?? "";

  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) { setLoadError("No invite token found in URL."); return; }
    fetch(`${BASE_URL}/org/invite/validate?token=${encodeURIComponent(token)}`)
      .then((r) => r.ok ? r.json() : r.json().then((d: { detail?: string }) => Promise.reject(d.detail ?? "Invalid invite")))
      .then((data: InviteInfo) => setInvite(data))
      .catch((e) => setLoadError(typeof e === "string" ? e : "Invalid or expired invite link"));
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setSaving(true);
    try {
      const res = await fetch(`${BASE_URL}/org/invite/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, username, password, full_name: fullName }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Failed to join");
      Cookies.set("token", data.access_token, { expires: 1 });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSaving(false);
    }
  }

  if (!token || loadError) {
    return (
      <div className="text-center space-y-4">
        <div className="w-12 h-12 rounded-full flex items-center justify-center mx-auto"
          style={{ background: "rgba(248,113,113,0.1)" }}>
          <svg className="w-6 h-6" style={{ color: "#f87171" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
        <p className="text-white font-semibold">Invalid invite</p>
        <p className="text-xs text-slate-500">{loadError || "This invite link is missing or invalid."}</p>
        <Link href="/login" className="text-xs font-mono" style={{ color: "#5CF097" }}>← Go to login</Link>
      </div>
    );
  }

  if (!invite) {
    return <div className="h-32 rounded animate-pulse" style={{ background: "#111827" }} />;
  }

  return (
    <div className="space-y-6">
      {/* Org invite info */}
      <div className="rounded border border-white/5 p-4 text-center" style={{ background: "#0A0F1F" }}>
        <div className="w-10 h-10 rounded-lg flex items-center justify-center text-sm font-bold mx-auto mb-3"
          style={{ background: "rgba(92,240,151,0.12)", color: "#5CF097" }}>
          {invite.org_name[0]?.toUpperCase()}
        </div>
        <p className="text-xs text-slate-500 mb-1">You&apos;ve been invited to join</p>
        <p className="text-white font-semibold">{invite.org_name}</p>
        <div className="flex items-center justify-center gap-3 mt-2">
          <span className="text-xs font-mono px-2 py-0.5 rounded"
            style={{ background: "rgba(92,240,151,0.08)", color: "#5CF097" }}>
            {ROLE_LABEL[invite.role] ?? invite.role}
          </span>
          {invite.invited_by && (
            <span className="text-xs text-slate-600">invited by <span className="text-slate-400">{invite.invited_by}</span></span>
          )}
        </div>
      </div>

      {/* Registration form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Email</label>
          <input value={invite.email} disabled
            className="w-full rounded px-3 py-2 text-sm opacity-60 cursor-not-allowed"
            style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.06)", color: "#94a3b8" }} />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Full Name</label>
          <input value={fullName} onChange={(e) => setFullName(e.target.value)}
            placeholder="Jane Smith"
            className="w-full rounded px-3 py-2 text-sm outline-none"
            style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#e2e8f0" }} />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Username *</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)}
            required placeholder="jane.smith" minLength={3}
            className="w-full rounded px-3 py-2 text-sm outline-none"
            style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#e2e8f0" }} />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">Password *</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            required minLength={6} placeholder="Min. 6 characters"
            className="w-full rounded px-3 py-2 text-sm outline-none"
            style={{ background: "#0A0F1F", border: "1px solid rgba(255,255,255,0.08)", color: "#e2e8f0" }} />
        </div>
        {error && <p className="text-xs text-red-400">{error}</p>}
        <button type="submit" disabled={saving}
          className="w-full py-2.5 rounded text-sm font-medium disabled:opacity-50 transition-opacity"
          style={{ background: "#5CF097", color: "#fff" }}>
          {saving ? "Joining…" : `Join ${invite.org_name}`}
        </button>
      </form>

      <p className="text-center text-xs text-slate-600">
        Already have an account?{" "}
        <Link href="/login" className="underline" style={{ color: "#5CF097" }}>Sign in</Link>
      </p>
    </div>
  );
}

export default function JoinPage() {
  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "#0A0F1F" }}>
      <div className="w-full max-w-sm space-y-6">
        {/* Header */}
        <div className="text-center">
          <div className="flex items-center justify-center gap-2 mb-6">
            <span className="w-5 h-5 rounded-sm" style={{ background: "#5CF097" }} />
            <span className="text-white font-semibold text-sm">Seraph</span>
          </div>
          <h1 className="text-xl font-bold text-white">Join your team</h1>
          <p className="text-xs text-slate-500 mt-1">Create your account to get started</p>
        </div>

        <div className="rounded-lg border border-white/5 p-6" style={{ background: "#0d1426" }}>
          <Suspense fallback={<div className="h-32 rounded animate-pulse" style={{ background: "#111827" }} />}>
            <JoinPageContent />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
