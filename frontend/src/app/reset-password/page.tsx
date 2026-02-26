"use client";

import { Suspense, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

const inputStyle: React.CSSProperties = {
  background: "#0d1426",
  border: "1px solid rgba(255,255,255,0.08)",
};

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetPasswordForm />
    </Suspense>
  );
}

function ResetPasswordForm() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) setError("Missing reset token. Please request a new link.");
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "Reset failed. The link may have expired.");
        return;
      }
      setDone(true);
    } catch {
      setError("Cannot reach the backend.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex" style={{ background: "#0A0F1F" }}>
      {/* Left panel */}
      <div className="hidden lg:flex flex-col justify-between w-2/5 border-r border-white/5 p-12" style={{ background: "#0d1426" }}>
        <Link href="/" className="flex items-center gap-2.5">
          <span className="w-5 h-5 rounded-sm" style={{ background: "#14B8A6" }} />
          <span className="text-white font-semibold text-sm tracking-tight">Talix Shield</span>
        </Link>
        <div>
          <p className="text-2xl font-bold text-white tracking-tight leading-snug mb-4">
            Guard every prompt.<br />Every response.
          </p>
          <p className="text-sm text-slate-500 leading-relaxed">
            One API. Full audit trail. Real-time monitoring.
          </p>
        </div>
        <p className="text-xs text-slate-700">© 2024 Talix Shield</p>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-sm">
          <Link href="/login" className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-400 transition-colors mb-8">
            <span>←</span> Back to sign in
          </Link>

          {done ? (
            <div className="space-y-6">
              <div>
                <h1 className="text-2xl font-bold text-white tracking-tight mb-1">Password updated</h1>
                <p className="text-sm text-slate-500">You can now sign in with your new password.</p>
              </div>
              <div className="rounded border-l-2 px-4 py-4"
                style={{ background: "rgba(20,184,166,0.05)", borderColor: "#14B8A6" }}>
                <p className="text-xs text-slate-400">Your password has been changed successfully.</p>
              </div>
              <Link
                href="/login"
                className="block w-full py-2.5 rounded text-sm font-medium text-center transition-opacity"
                style={{ background: "#14B8A6", color: "#0A0F1F" }}
              >
                Sign in
              </Link>
            </div>
          ) : (
            <>
              <div className="mb-8">
                <h1 className="text-2xl font-bold text-white tracking-tight mb-1">Set new password</h1>
                <p className="text-sm text-slate-500">Choose a strong password for your account.</p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">
                    New password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    autoFocus
                    disabled={!token}
                    className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors disabled:opacity-40"
                    style={inputStyle}
                    onFocus={(e) => (e.target.style.borderColor = "#14B8A6")}
                    onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
                    placeholder="Min. 6 characters"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">
                    Confirm new password
                  </label>
                  <input
                    type="password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    disabled={!token}
                    className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors disabled:opacity-40"
                    style={inputStyle}
                    onFocus={(e) => (e.target.style.borderColor = "#14B8A6")}
                    onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
                    placeholder="••••••••"
                  />
                </div>

                {error && (
                  <p className="text-xs text-red-400 border border-red-400/20 rounded px-3 py-2.5"
                    style={{ background: "rgba(248,113,113,0.05)" }}>
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={loading || !token}
                  className="w-full py-2.5 rounded text-sm font-medium transition-opacity disabled:opacity-50"
                  style={{ background: "#14B8A6", color: "#0A0F1F" }}
                >
                  {loading ? "Updating…" : "Set new password"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
