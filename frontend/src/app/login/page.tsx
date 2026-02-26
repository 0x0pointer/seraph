"use client";

import { useState } from "react";
import Link from "next/link";
import Cookies from "js-cookie";

type Mode = "login" | "forgot-password" | "forgot-username";

const inputStyle: React.CSSProperties = {
  background: "#0d1426",
  border: "1px solid rgba(255,255,255,0.08)",
};

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("login");

  return (
    <div className="min-h-screen flex" style={{ background: "#0A0F1F" }}>
      {/* Left panel */}
      <div className="hidden lg:flex flex-col justify-between w-2/5 border-r border-white/5 p-12" style={{ background: "#0d1426" }}>
        <Link href="/" className="flex items-center gap-2.5">
          <span className="w-5 h-5 rounded-sm" style={{ background: "#14B8A6" }} />
          <span className="text-white font-semibold text-sm tracking-tight">Project 73</span>
        </Link>
        <div>
          <p className="text-2xl font-bold text-white tracking-tight leading-snug mb-4">
            Guard every prompt.<br />Every response.
          </p>
          <p className="text-sm text-slate-500 leading-relaxed">
            One API. Full audit trail. Real-time monitoring.
          </p>
        </div>
        <p className="text-xs text-slate-700">© 2026 Project 73 Security</p>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-sm">
          {mode === "login" && <LoginForm onForgotPassword={() => setMode("forgot-password")} onForgotUsername={() => setMode("forgot-username")} />}
          {mode === "forgot-password" && <ForgotPasswordForm onBack={() => setMode("login")} />}
          {mode === "forgot-username" && <ForgotUsernameForm onBack={() => setMode("login")} />}
        </div>
      </div>
    </div>
  );
}

// ── Login form ─────────────────────────────────────────────────────────────────

function LoginForm({ onForgotPassword, onForgotUsername }: { onForgotPassword: () => void; onForgotUsername: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Invalid credentials");
        return;
      }
      const data = await res.json();
      Cookies.set("token", data.access_token, { expires: 1 / 24, sameSite: "lax" });
      window.location.href = "/dashboard";
    } catch {
      setError("Cannot reach the backend. Is it running on port 8000?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white tracking-tight mb-1">Welcome back</h1>
        <p className="text-sm text-slate-500">
          No account?{" "}
          <Link href="/register" className="transition-colors hover:text-white" style={{ color: "#14B8A6" }}>
            Create one
          </Link>
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
            className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
            style={inputStyle}
            onFocus={(e) => (e.target.style.borderColor = "#14B8A6")}
            onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
            placeholder="admin"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
            style={inputStyle}
            onFocus={(e) => (e.target.style.borderColor = "#14B8A6")}
            onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
            placeholder="••••••••"
          />
        </div>

        {error && (
          <p className="text-xs text-red-400 border border-red-400/20 rounded px-3 py-2.5" style={{ background: "rgba(248,113,113,0.05)" }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 rounded text-sm font-medium transition-opacity disabled:opacity-50"
          style={{ background: "#14B8A6", color: "#0A0F1F" }}
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="mt-6 flex items-center justify-center gap-4">
        <button onClick={onForgotPassword} className="text-xs text-slate-600 hover:text-slate-400 transition-colors">
          Forgot password?
        </button>
        <span className="text-slate-700 text-xs">·</span>
        <button onClick={onForgotUsername} className="text-xs text-slate-600 hover:text-slate-400 transition-colors">
          Forgot username?
        </button>
      </div>
    </>
  );
}

// ── Forgot password form ───────────────────────────────────────────────────────

function ForgotPasswordForm({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Something went wrong");
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
    <>
      <button onClick={onBack} className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-400 transition-colors mb-8">
        <span>←</span> Back to sign in
      </button>

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white tracking-tight mb-1">Reset password</h1>
        <p className="text-sm text-slate-500">
          Enter your account email and we&apos;ll send you a reset link.
        </p>
      </div>

      {done ? (
        <div className="space-y-4">
          <div className="rounded border-l-2 px-4 py-4 space-y-1"
            style={{ background: "rgba(20,184,166,0.05)", borderColor: "#14B8A6" }}>
            <p className="text-sm font-medium text-white">Check your inbox</p>
            <p className="text-xs text-slate-400 leading-relaxed">
              If <span className="font-mono text-slate-300">{email}</span> is registered, a password reset link
              has been sent. It expires in 1 hour.
            </p>
          </div>
          <button onClick={onBack} className="text-xs font-mono" style={{ color: "#14B8A6" }}>
            ← Back to sign in
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">Email address</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
              style={inputStyle}
              onFocus={(e) => (e.target.style.borderColor = "#14B8A6")}
              onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
              placeholder="you@company.com"
            />
          </div>

          {error && (
            <p className="text-xs text-red-400 border border-red-400/20 rounded px-3 py-2.5" style={{ background: "rgba(248,113,113,0.05)" }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded text-sm font-medium transition-opacity disabled:opacity-50"
            style={{ background: "#14B8A6", color: "#0A0F1F" }}
          >
            {loading ? "Sending…" : "Send reset link"}
          </button>
        </form>
      )}
    </>
  );
}

// ── Forgot username form ───────────────────────────────────────────────────────

function ForgotUsernameForm({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/forgot-username", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Something went wrong");
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
    <>
      <button onClick={onBack} className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-400 transition-colors mb-8">
        <span>←</span> Back to sign in
      </button>

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white tracking-tight mb-1">Forgot username</h1>
        <p className="text-sm text-slate-500">
          Enter the email address on your account and we&apos;ll send your username.
        </p>
      </div>

      {done ? (
        <div className="space-y-4">
          <div className="rounded border-l-2 px-4 py-4 space-y-1"
            style={{ background: "rgba(20,184,166,0.05)", borderColor: "#14B8A6" }}>
            <p className="text-sm font-medium text-white">Check your inbox</p>
            <p className="text-xs text-slate-400 leading-relaxed">
              If <span className="font-mono text-slate-300">{email}</span> is registered, your username
              has been sent to that address.
            </p>
          </div>
          <button onClick={onBack} className="text-xs font-mono" style={{ color: "#14B8A6" }}>
            ← Back to sign in
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">Email address</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
              style={inputStyle}
              onFocus={(e) => (e.target.style.borderColor = "#14B8A6")}
              onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
              placeholder="you@company.com"
            />
          </div>

          {error && (
            <p className="text-xs text-red-400 border border-red-400/20 rounded px-3 py-2.5" style={{ background: "rgba(248,113,113,0.05)" }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded text-sm font-medium transition-opacity disabled:opacity-50"
            style={{ background: "#14B8A6", color: "#0A0F1F" }}
          >
            {loading ? "Sending…" : "Send my username"}
          </button>
        </form>
      )}
    </>
  );
}
