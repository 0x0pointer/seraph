"use client";

import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

interface UserInfo { id: number; username: string; full_name: string | null; email: string | null; role: string; org_id: number | null; team_id: number | null; }
interface ApiTokenInfo { api_token: string; created: boolean; }

const inputStyle = {
  background: "var(--bg)",
  border: "1px solid var(--border-input)",
  color: "var(--text)",
};

/* ── Account section loading skeleton ── */
const SKELETON_KEYS = ["sk-1", "sk-2", "sk-3"] as const;

function AccountSkeleton() {
  return (
    <div className="space-y-2">
      {SKELETON_KEYS.map((k) => (
        <div key={k} className="h-8 rounded animate-pulse" style={{ background: "var(--card2)" }} />
      ))}
    </div>
  );
}

/* ── Read-only profile display ── */
function ProfileDisplay({ user, profileMsg, profileErr }: Readonly<{
  user: UserInfo;
  profileMsg: string;
  profileErr: boolean;
}>) {
  return (
    <div className="space-y-3">
      {profileMsg && !profileErr && (
        <p className="text-xs px-3 py-2.5 rounded border font-mono mb-2"
          style={{ color: "#5CF097", background: "rgba(92,240,151,0.05)", borderColor: "rgba(92,240,151,0.15)" }}>
          {profileMsg}
        </p>
      )}
      {[
        { label: "Username", value: user.username, color: "var(--text)" },
        { label: "Full name", value: user.full_name ?? "---", color: "var(--text)" },
        { label: "Email", value: user.email ?? "---", color: "var(--text)" },
        { label: "Role", value: user.role, color: "#5CF097" },
        { label: "User ID", value: `#${user.id}`, color: "var(--text)" },
      ].map(({ label, value, color }) => (
        <div key={label} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
          <span className="text-xs text-slate-500">{label}</span>
          <span className="text-xs font-mono capitalize" style={{ color }}>{value}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Profile edit form ── */
function ProfileEditForm({
  user, profileForm, setProfileForm, profileMsg, profileErr, profileSaving,
  onSubmit, onCancel,
}: Readonly<{
  user: UserInfo;
  profileForm: { username: string; full_name: string; email: string };
  setProfileForm: React.Dispatch<React.SetStateAction<{ username: string; full_name: string; email: string }>>;
  profileMsg: string;
  profileErr: boolean;
  profileSaving: boolean;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
}>) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {[
        { label: "Username", key: "username" as const, type: "text", placeholder: user.username },
        { label: "Full name", key: "full_name" as const, type: "text", placeholder: user.full_name ?? "" },
        { label: "Email", key: "email" as const, type: "email", placeholder: user.email ?? "" },
      ].map(({ label, key, type, placeholder }) => (
        <div key={key}>
          <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">{label}</label>
          <input
            type={type}
            value={profileForm[key]}
            onChange={(e) => setProfileForm((f) => ({ ...f, [key]: e.target.value }))}
            placeholder={placeholder}
            className="w-full rounded px-3 py-2 text-sm outline-none placeholder:text-slate-700"
            style={inputStyle}
          />
        </div>
      ))}
      {/* Read-only fields */}
      {[
        { label: "Role", value: user.role, color: "#5CF097" },
        { label: "User ID", value: `#${user.id}`, color: "var(--text)" },
      ].map(({ label, value, color }) => (
        <div key={label} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
          <span className="text-xs text-slate-500">{label}</span>
          <span className="text-xs font-mono" style={{ color }}>{value}</span>
        </div>
      ))}
      {profileMsg && (
        <p className="text-xs px-3 py-2.5 rounded border font-mono"
          style={profileErr
            ? { color: "#f87171", background: "rgba(248,113,113,0.05)", borderColor: "rgba(248,113,113,0.15)" }
            : { color: "#5CF097", background: "rgba(92,240,151,0.05)", borderColor: "rgba(92,240,151,0.15)" }}>
          {profileMsg}
        </p>
      )}
      <div className="flex items-center gap-3 pt-1">
        <button
          type="submit"
          disabled={profileSaving}
          className="text-xs font-medium px-4 py-2 rounded disabled:opacity-50"
          style={{ background: "#5CF097", color: "#0A0F1F" }}
        >
          {profileSaving ? "Saving..." : "Save changes"}
        </button>
        <button type="button" onClick={onCancel} className="text-xs text-slate-500 hover:text-white transition-colors">
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { data: user, mutate: mutateUser } = useSWR<UserInfo>("/auth/me", () => api.get<UserInfo>("/auth/me"));

  // Profile edit
  const [editingProfile, setEditingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState({ username: "", full_name: "", email: "" });
  const [profileMsg, setProfileMsg] = useState("");
  const [profileErr, setProfileErr] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);

  function openEditProfile() {
    if (!user) return;
    setProfileForm({ username: user.username, full_name: user.full_name ?? "", email: user.email ?? "" });
    setProfileMsg("");
    setEditingProfile(true);
  }

  function cancelEditProfile() { setEditingProfile(false); setProfileMsg(""); }

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setProfileMsg(""); setProfileErr(false);
    setProfileSaving(true);
    try {
      const updated = await api.patch<UserInfo>("/auth/me", {
        username: profileForm.username.trim() || undefined,
        full_name: profileForm.full_name.trim() || undefined,
        email: profileForm.email.trim() || undefined,
      });
      await mutateUser(updated, false);
      setProfileMsg("Profile updated.");
      setEditingProfile(false);
    } catch (err) {
      setProfileMsg(err instanceof Error ? err.message : "Failed to save.");
      setProfileErr(true);
    } finally {
      setProfileSaving(false);
    }
  }

  // Password
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [msg, setMsg] = useState("");
  const [msgErr, setMsgErr] = useState(false);

  // API token
  const { data: tokenData, mutate: mutateToken, isLoading: tokenLoading } = useSWR<ApiTokenInfo>(
    "/auth/api-token",
    () => api.get<ApiTokenInfo>("/auth/api-token"),
  );
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [snippetTab, setSnippetTab] = useState("curl");

  const token = tokenData?.api_token ?? "";

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setMsg(""); setMsgErr(false);
    if (newPw !== confirmPw) { setMsg("New passwords do not match."); setMsgErr(true); return; }
    try {
      await api.post("/auth/change-password", { current_password: currentPw, new_password: newPw });
      setMsg("Password updated."); setCurrentPw(""); setNewPw(""); setConfirmPw("");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Failed."); setMsgErr(true);
    }
  }

  async function handleRegenerate() {
    if (!confirmRegen) { setConfirmRegen(true); return; }
    setRegenerating(true);
    setConfirmRegen(false);
    try {
      const fresh = await api.post<ApiTokenInfo>("/auth/api-token/regenerate", {});
      await mutateToken(fresh, false);
      setRevealed(true);
    } finally {
      setRegenerating(false);
    }
  }

  function handleCopyToken() {
    if (!token) return;
    navigator.clipboard.writeText(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  function handleCopySnippet(key: string, text: string) {
    navigator.clipboard.writeText(text);
    setCopiedSnippet(key);
    setTimeout(() => setCopiedSnippet(null), 1500);
  }

  const maskedToken = token
    ? token.slice(0, 15) + "••••••••••••••••••••••••••••••••" + token.slice(-4)
    : "";
  const display = revealed ? token : maskedToken;

  const snippets = [
    {
      key: "curl",
      lang: "bash",
      label: "cURL",
      code: `curl -X POST http://localhost:8000/api/scan/prompt \\
  -H "Authorization: Bearer ${token || "YOUR_API_TOKEN"}" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "user prompt here"}'`,
    },
    {
      key: "python",
      lang: "python",
      label: "Python",
      code: `import httpx

response = httpx.post(
    "http://localhost:8000/api/scan/prompt",
    headers={"Authorization": "Bearer ${token || "YOUR_API_TOKEN"}"},
    json={"text": "user prompt here"},
)
print(response.json())`,
    },
    {
      key: "ts",
      lang: "typescript",
      label: "TypeScript",
      code: `const res = await fetch("http://localhost:8000/api/scan/prompt", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: "Bearer ${token || "YOUR_API_TOKEN"}",
  },
  body: JSON.stringify({ text: "user prompt here" }),
});
const data = await res.json();`,
    },
  ];

  return (
    <div className="max-w-2xl space-y-6">

      {/* Account */}
      <div className="rounded border border-white/5 p-6" style={{ background: "var(--card)" }}>
        <div className="flex items-center justify-between mb-5">
          <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">Account</p>
          {user && !editingProfile && (
            <button
              onClick={openEditProfile}
              className="text-xs font-medium px-3 py-1 rounded border border-white/10 text-slate-400 hover:text-white hover:border-white/20 transition-colors"
            >
              Edit profile
            </button>
          )}
        </div>

        {!user && <AccountSkeleton />}
        {user && editingProfile && (
          <ProfileEditForm
            user={user}
            profileForm={profileForm}
            setProfileForm={setProfileForm}
            profileMsg={profileMsg}
            profileErr={profileErr}
            profileSaving={profileSaving}
            onSubmit={handleSaveProfile}
            onCancel={cancelEditProfile}
          />
        )}
        {user && !editingProfile && (
          <ProfileDisplay user={user} profileMsg={profileMsg} profileErr={profileErr} />
        )}
      </div>

      {/* Change password */}
      <div className="rounded border border-white/5 p-6" style={{ background: "var(--card)" }}>
        <p className="text-xs text-slate-500 uppercase tracking-widest font-mono mb-5">Change Password</p>
        <form onSubmit={handleChangePassword} className="space-y-4">
          {[
            { label: "Current password", val: currentPw, set: setCurrentPw },
            { label: "New password", val: newPw, set: setNewPw },
            { label: "Confirm new password", val: confirmPw, set: setConfirmPw },
          ].map(({ label, val, set }) => (
            <div key={label}>
              <label className="block text-xs text-slate-500 mb-1.5 uppercase tracking-wider">{label}</label>
              <input type="password" value={val} onChange={(e) => set(e.target.value)} required
                className="w-full rounded px-3 py-2 text-sm outline-none" style={inputStyle} />
            </div>
          ))}
          {msg && (
            <p className="text-xs px-3 py-2.5 rounded border font-mono"
              style={msgErr
                ? { color: "#f87171", background: "rgba(248,113,113,0.05)", borderColor: "rgba(248,113,113,0.15)" }
                : { color: "#5CF097", background: "rgba(92,240,151,0.05)", borderColor: "rgba(92,240,151,0.15)" }}>
              {msg}
            </p>
          )}
          <button type="submit" className="text-xs font-medium px-4 py-2 rounded" style={{ background: "#5CF097", color: "#0A0F1F" }}>
            Update password
          </button>
        </form>
      </div>

      {/* API Token */}
      <div className="rounded border border-white/5 p-6" style={{ background: "var(--card)" }}>
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">API Token</p>
          <span
            className="text-xs font-mono px-2 py-0.5 rounded"
            style={{ background: "rgba(92,240,151,0.08)", color: "#5CF097" }}
          >
            ts_live_…
          </span>
        </div>
        <p className="text-xs text-slate-500 leading-relaxed mb-5">
          Use this token to authenticate requests from your application. Pass it as a{" "}
          <code className="text-[#5CF097] font-mono">Bearer</code> token in the{" "}
          <code className="text-[#5CF097] font-mono">Authorization</code> header.
          It never expires — regenerate if compromised.
        </p>

        {/* Token display */}
        <div className="rounded border border-white/5 overflow-hidden mb-4" style={{ background: "var(--bg)" }}>
          <div className="flex items-center justify-between px-4 py-2 border-b border-white/5">
            <span className="text-xs text-slate-600 font-mono">Authorization: Bearer</span>
            <div className="flex items-center gap-4">
              <button
                onClick={() => setRevealed((v) => !v)}
                className="text-xs font-mono transition-colors hover:text-slate-300"
                style={{ color: "#475569" }}
              >
                {revealed ? "hide" : "reveal"}
              </button>
              <button
                onClick={handleCopyToken}
                disabled={!token}
                className="text-xs font-mono transition-colors disabled:opacity-30"
                style={{ color: copied ? "#5CF097" : "#475569" }}
              >
                {copied ? "copied!" : "copy"}
              </button>
            </div>
          </div>
          <div className="px-4 py-3 min-h-[40px] flex items-center">
            {tokenLoading ? (
              <div className="h-4 w-3/4 rounded animate-pulse" style={{ background: "#1a2236" }} />
            ) : (
              <code
                className="text-xs font-mono break-all select-all"
                style={{ color: revealed ? "#5CF097" : "#334155" }}
              >
                {display || "—"}
              </code>
            )}
          </div>
        </div>

        {/* Regenerate */}
        <div className="flex items-center gap-3 mb-6">
          {confirmRegen ? (
            <>
              <span className="text-xs text-slate-500">This will invalidate your current token. Continue?</span>
              <button
                onClick={handleRegenerate}
                disabled={regenerating}
                className="text-xs font-medium px-3 py-1.5 rounded disabled:opacity-40"
                style={{ background: "rgba(248,113,113,0.12)", color: "#f87171" }}
              >
                {regenerating ? "Regenerating…" : "Yes, regenerate"}
              </button>
              <button
                onClick={() => setConfirmRegen(false)}
                className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={handleRegenerate}
              disabled={regenerating || tokenLoading}
              className="text-xs font-medium px-3 py-1.5 rounded border border-white/10 text-slate-400 hover:text-white hover:border-white/20 transition-colors disabled:opacity-40"
            >
              Regenerate token
            </button>
          )}
        </div>

        {/* Usage snippets */}
        <p className="text-xs text-slate-500 uppercase tracking-widest font-mono mb-4">Usage examples</p>
        <div className="flex gap-1 p-1 rounded w-fit mb-4" style={{ background: "var(--bg)" }}>
          {snippets.map((s) => (
            <button
              key={s.key}
              onClick={() => setSnippetTab(s.key)}
              className="px-3 py-1.5 rounded text-xs font-medium transition-colors"
              style={
                snippetTab === s.key
                  ? { background: "#5CF097", color: "#0A0F1F" }
                  : { color: "var(--text-dim)" }
              }
            >
              {s.label}
            </button>
          ))}
        </div>
        {snippets.filter((s) => s.key === snippetTab).map((s) => (
          <div key={s.key} className="rounded border border-white/5 overflow-hidden" style={{ background: "var(--bg)" }}>
            <div className="flex items-center justify-between px-4 py-2 border-b border-white/5">
              <span className="text-xs text-slate-600 font-mono">{s.lang}</span>
              <button
                onClick={() => handleCopySnippet(s.key, s.code)}
                className="text-xs font-mono transition-colors"
                style={{ color: copiedSnippet === s.key ? "#5CF097" : "#475569" }}
              >
                {copiedSnippet === s.key ? "copied!" : "copy"}
              </button>
            </div>
            <pre
              className="px-4 py-4 text-xs font-mono text-slate-400 overflow-x-auto whitespace-pre leading-relaxed"
              style={{ fontFamily: "ui-monospace, SFMono-Regular, monospace" }}
            >
              {s.code}
            </pre>
          </div>
        ))}

        {/* Security note */}
        <div
          className="mt-5 rounded border-l-2 px-4 py-3 text-xs text-slate-500 leading-relaxed"
          style={{ background: "var(--bg)", borderColor: "rgba(251,146,60,0.4)" }}
        >
          <strong className="text-slate-300">Keep this token secret.</strong> Never expose it in
          client-side code, commit it to a repository, or share it in logs. Store it in an environment
          variable or a secrets manager. If you believe it has been compromised, regenerate it immediately.
        </div>
      </div>

    </div>
  );
}
