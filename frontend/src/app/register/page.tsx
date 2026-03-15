"use client";

import { useState, useRef } from "react";
import Link from "next/link";
import Cookies from "js-cookie";
import { Turnstile, type TurnstileInstance } from "@marsidev/react-turnstile";

// Cloudflare Turnstile test site key — always passes in development.
// Replace with your real site key from dash.cloudflare.com → Turnstile.
const TURNSTILE_SITE_KEY =
  process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "1x00000000000000000000AA";

interface PasswordRule {
  label: string;
  test: (v: string) => boolean;
}

const PASSWORD_RULES: PasswordRule[] = [
  { label: "At least 8 characters", test: (v) => v.length >= 8 },
  { label: "Uppercase letter", test: (v) => /[A-Z]/.test(v) },
  { label: "Lowercase letter", test: (v) => /[a-z]/.test(v) },
  { label: "Number", test: (v) => /[0-9]/.test(v) },
  { label: "Special character (!@#$…)", test: (v) => /[^A-Za-z0-9]/.test(v) },
];

function PasswordStrength({ password }: { password: string }) {
  if (!password) return null;
  const passed = PASSWORD_RULES.filter((r) => r.test(password)).length;
  const color =
    passed <= 2 ? "#f87171" : passed <= 3 ? "#fb923c" : passed === 4 ? "#facc15" : "#5CF097";
  const label = ["", "Weak", "Weak", "Fair", "Good", "Strong"][passed];

  return (
    <div className="mt-2 space-y-2">
      <div className="flex gap-1">
        {PASSWORD_RULES.map((_, i) => (
          <div
            key={i}
            className="h-1 flex-1 rounded-full transition-all duration-300"
            style={{ background: i < passed ? color : "#1a2236" }}
          />
        ))}
      </div>
      <div className="space-y-1">
        {PASSWORD_RULES.map((rule) => {
          const ok = rule.test(password);
          return (
            <div key={rule.label} className="flex items-center gap-1.5">
              <span className="text-xs" style={{ color: ok ? "#5CF097" : "#475569" }}>
                {ok ? "✓" : "○"}
              </span>
              <span className="text-xs" style={{ color: ok ? "#94a3b8" : "#475569" }}>
                {rule.label}
              </span>
            </div>
          );
        })}
      </div>
      {passed > 0 && (
        <p className="text-xs font-mono" style={{ color }}>
          {label}
        </p>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: "#0d1426",
  border: "1px solid rgba(255,255,255,0.08)",
};

export default function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const turnstileRef = useRef<TurnstileInstance>(null);

  const allRulesPassed = PASSWORD_RULES.every((r) => r.test(password));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!allRulesPassed) {
      setError("Password does not meet all requirements");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    if (!turnstileToken) {
      setError("Please complete the CAPTCHA");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName,
          email,
          username,
          password,
          turnstile_token: turnstileToken,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Registration failed. Please try again.");
        turnstileRef.current?.reset();
        setTurnstileToken(null);
        return;
      }

      const data = await res.json();
      Cookies.set("token", data.access_token, { expires: 1 / 24, sameSite: "lax" });
      window.location.href = "/dashboard";
    } catch {
      setError("Cannot reach the backend. Is it running on port 8000?");
      turnstileRef.current?.reset();
      setTurnstileToken(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex" style={{ background: "#0A0F1F" }}>
      {/* Left panel */}
      <div
        className="hidden lg:flex flex-col justify-between w-2/5 border-r border-white/5 p-12"
        style={{ background: "#0d1426" }}
      >
        <Link href="/" className="flex items-center gap-2.5">
          <span className="w-5 h-5 rounded-sm" style={{ background: "#5CF097" }} />
          <span className="text-white font-semibold text-sm tracking-tight">Seraph</span>
        </Link>
        <div>
          <p className="text-2xl font-bold text-white tracking-tight leading-snug mb-4">
            Guard every prompt.<br />Every response.
          </p>
          <p className="text-sm text-slate-500 leading-relaxed">
            One API. Full audit trail. Real-time monitoring.
          </p>
        </div>
        <p className="text-xs text-slate-700">© 2026 Seraph</p>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-white tracking-tight mb-1">Create an account</h1>
            <p className="text-sm text-slate-500">
              Already have one?{" "}
              <Link href="/login" className="transition-colors hover:text-white" style={{ color: "#5CF097" }}>
                Sign in
              </Link>
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Full name */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">
                Full name
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                autoFocus
                autoComplete="name"
                placeholder="Jane Smith"
                className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
                style={inputStyle}
                onFocus={(e) => (e.target.style.borderColor = "#5CF097")}
                onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
              />
            </div>

            {/* Email */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                placeholder="jane@example.com"
                className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
                style={inputStyle}
                onFocus={(e) => (e.target.style.borderColor = "#5CF097")}
                onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
              />
            </div>

            {/* Username */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                placeholder="janesmith"
                className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
                style={inputStyle}
                onFocus={(e) => (e.target.style.borderColor = "#5CF097")}
                onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
              />
            </div>

            {/* Password */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="new-password"
                placeholder="••••••••"
                className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
                style={inputStyle}
                onFocus={(e) => (e.target.style.borderColor = "#5CF097")}
                onBlur={(e) => (e.target.style.borderColor = "rgba(255,255,255,0.08)")}
              />
              <PasswordStrength password={password} />
            </div>

            {/* Confirm password */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">
                Confirm password
              </label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                autoComplete="new-password"
                placeholder="••••••••"
                className="w-full rounded px-3 py-2.5 text-sm text-white outline-none transition-colors"
                style={{
                  ...inputStyle,
                  borderColor:
                    confirm && password !== confirm
                      ? "rgba(248,113,113,0.5)"
                      : confirm && password === confirm
                      ? "rgba(92,240,151,0.5)"
                      : "rgba(255,255,255,0.08)",
                }}
                onFocus={(e) => {
                  if (!confirm || password === confirm) e.target.style.borderColor = "#5CF097";
                }}
                onBlur={(e) => {
                  e.target.style.borderColor =
                    confirm && password !== confirm
                      ? "rgba(248,113,113,0.5)"
                      : confirm && password === confirm
                      ? "rgba(92,240,151,0.5)"
                      : "rgba(255,255,255,0.08)";
                }}
              />
              {confirm && password !== confirm && (
                <p className="text-xs mt-1.5" style={{ color: "#f87171" }}>Passwords do not match</p>
              )}
            </div>

            {/* Cloudflare Turnstile */}
            <div>
              <Turnstile
                ref={turnstileRef}
                siteKey={TURNSTILE_SITE_KEY}
                onSuccess={setTurnstileToken}
                onExpire={() => setTurnstileToken(null)}
                onError={() => setTurnstileToken(null)}
                options={{ theme: "dark", size: "normal" }}
              />
            </div>

            {error && (
              <p
                className="text-xs text-red-400 border border-red-400/20 rounded px-3 py-2.5"
                style={{ background: "rgba(248,113,113,0.05)" }}
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !turnstileToken || !allRulesPassed || password !== confirm}
              className="w-full py-2.5 rounded text-sm font-medium transition-opacity disabled:opacity-40"
              style={{ background: "#5CF097", color: "#fff" }}
            >
              {loading ? "Creating account…" : "Create account"}
            </button>
          </form>

          <p className="mt-6 text-xs text-slate-600 text-center leading-relaxed">
            New accounts have viewer access. Contact an admin to upgrade.
          </p>
        </div>
      </div>
    </div>
  );
}
