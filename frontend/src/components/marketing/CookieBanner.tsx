"use client";

import Link from "next/link";
import { useState, useEffect } from "react";

export default function CookieBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const consent = localStorage.getItem("cookie_consent");
    if (!consent) setVisible(true);
  }, []);

  function accept() {
    localStorage.setItem("cookie_consent", "accepted");
    setVisible(false);
  }

  function decline() {
    localStorage.setItem("cookie_consent", "declined");
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-white/5"
      style={{ background: "rgba(10,15,31,0.97)", backdropFilter: "blur(16px)" }}
    >
      <div className="max-w-6xl mx-auto px-6 py-4 flex flex-col sm:flex-row items-start sm:items-center gap-4">
        <p className="text-xs text-slate-400 leading-relaxed flex-1">
          We use essential cookies to keep you logged in and remember your preferences.
          No advertising or tracking cookies are used.{" "}
          <Link href="/cookies" className="underline underline-offset-2 hover:text-white transition-colors" style={{ color: "#14B8A6" }}>
            Cookie Policy
          </Link>
          {" "}·{" "}
          <Link href="/privacy" className="underline underline-offset-2 hover:text-white transition-colors" style={{ color: "#14B8A6" }}>
            Privacy Policy
          </Link>
        </p>
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={decline}
            className="text-xs px-4 py-2 rounded border border-white/10 text-slate-400 hover:text-white hover:border-white/20 transition-colors"
          >
            Decline non-essential
          </button>
          <button
            onClick={accept}
            className="text-xs px-4 py-2 rounded font-medium transition-opacity hover:opacity-90"
            style={{ background: "#14B8A6", color: "#0A0F1F" }}
          >
            Accept cookies
          </button>
        </div>
      </div>
    </div>
  );
}
