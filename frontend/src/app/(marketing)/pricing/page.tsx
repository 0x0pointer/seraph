"use client";

import { useState } from "react";
import Link from "next/link";
import Cookies from "js-cookie";

const PAID_PLANS = ["starter", "pro"] as const;
type PaidPlan = typeof PAID_PLANS[number];

const tiers = [
  {
    name: "Free",
    plan: null,
    price: "$0",
    sub: "forever",
    desc: "Evaluate and prototype — no credit card required.",
    highlight: false,
    features: [
      { text: "1,000 scans / month", note: null },
      { text: "1 user", note: "Single-seat only" },
      { text: "Core security scanners", note: "Prompt Injection, PII, Toxicity + 2 more" },
      { text: "7-day audit log retention", note: null },
      { text: "1 API connection", note: null },
      { text: "REST API access", note: null },
      { text: "Community support", note: null },
    ],
    cta: "Start free",
    href: "/register",
  },
  {
    name: "Starter",
    plan: "starter" as PaidPlan,
    price: "$29",
    sub: "per month",
    desc: "For small apps and indie developers shipping AI features.",
    highlight: false,
    features: [
      { text: "25,000 scans / month", note: null },
      { text: "Up to 3 users", note: null },
      { text: "All 39 scanners", note: "Input & output, fully configurable" },
      { text: "30-day audit log retention", note: null },
      { text: "5 API connections", note: null },
      { text: "REST API access", note: null },
      { text: "Email support", note: null },
    ],
    cta: "Get started",
    href: "/register",
  },
  {
    name: "Pro",
    plan: "pro" as PaidPlan,
    price: "$99",
    sub: "per month",
    desc: "Full guardrail coverage for teams shipping AI to production.",
    highlight: true,
    badge: "Most popular",
    features: [
      { text: "250,000 scans / month", note: null },
      { text: "Up to 15 users", note: "Org-level plan with role-based access" },
      { text: "All 39 scanners", note: "Custom thresholds & configurations" },
      { text: "90-day audit log retention", note: null },
      { text: "Unlimited API connections", note: null },
      { text: "Analytics & abuse detection", note: null },
      { text: "Organizations & teams", note: null },
      { text: "99.5% uptime SLA", note: null },
      { text: "Priority support", note: null },
    ],
    cta: "Start free trial",
    href: "/register",
  },
  {
    name: "Enterprise",
    plan: null,
    price: "Custom",
    sub: "contact us",
    desc: "Unlimited scale, dedicated engineering, and SLA guarantees.",
    highlight: false,
    features: [
      { text: "Unlimited scans", note: null },
      { text: "Unlimited users", note: "No seat cap" },
      { text: "All 39 scanners + custom builds", note: null },
      { text: "1-year audit log retention", note: null },
      { text: "Unlimited API connections", note: null },
      { text: "SSO / SAML", note: null },
      { text: "On-premise deployment", note: null },
      { text: "Dedicated support engineer", note: null },
      { text: "99.9% uptime SLA", note: null },
      { text: "Security review & pen-test support", note: null },
    ],
    cta: "Talk to sales",
    href: "mailto:sales@project73.ai",
  },
];

const scannerGroups = [
  {
    label: "Prompt attacks",
    color: "#f87171",
    bg: "rgba(248,113,113,0.08)",
    scanners: ["Prompt Injection", "Jailbreak", "Invisible Text"],
  },
  {
    label: "Data protection",
    color: "#a78bfa",
    bg: "rgba(167,139,250,0.08)",
    scanners: ["PII Detection", "Secrets & Tokens", "Regex patterns"],
  },
  {
    label: "Content safety",
    color: "#14B8A6",
    bg: "rgba(20,184,166,0.08)",
    scanners: ["Toxicity", "Bias", "Language filtering"],
  },
  {
    label: "Output quality",
    color: "#fbbf24",
    bg: "rgba(251,191,36,0.08)",
    scanners: ["Hallucination", "Relevance", "Factual consistency"],
  },
  {
    label: "Policy enforcement",
    color: "#f97316",
    bg: "rgba(249,115,22,0.08)",
    scanners: ["Ban Topics", "Ban Competitors", "Custom word lists"],
  },
  {
    label: "Link & code safety",
    color: "#94a3b8",
    bg: "rgba(148,163,184,0.08)",
    scanners: ["Malicious URLs", "Code detection", "No refusal check"],
  },
];

const faqs = [
  {
    q: "What counts as a scan?",
    a: "Each call to POST /scan/prompt or POST /scan/output counts as one scan, regardless of how many scanners are active on that request.",
  },
  {
    q: "Can I change plans later?",
    a: "Yes — upgrade or downgrade at any time. If you upgrade mid-cycle, you're charged the prorated difference immediately. Downgrades take effect at the next billing date.",
  },
  {
    q: "Which scanners are included in the Free tier?",
    a: "The Free tier includes 5 core security scanners: Prompt Injection, Anonymize (PII), Toxicity, Ban Topics, and Ban Substrings. All 39 scanners are available on Starter, Pro, and Enterprise.",
  },
  {
    q: "Is there a free trial for Pro?",
    a: "Yes — the Pro trial gives you full access for 14 days with no credit card required. You'll be prompted to add a payment method at the end of the trial.",
  },
  {
    q: "What is the difference between Starter and Pro?",
    a: "Starter is designed for small apps and solo developers — 25,000 scans, 3 users, 5 connections. Pro is for growing teams with 250,000 scans, 15 users, unlimited connections, analytics, org management, and a 99.5% SLA.",
  },
  {
    q: "What is on-premise deployment?",
    a: "Enterprise customers can run the entire Project 73 stack inside their own infrastructure. We provide Docker images, Helm charts, and a dedicated engineer for the initial rollout.",
  },
];

async function startCheckout(plan: PaidPlan): Promise<void> {
  const token = Cookies.get("token");
  const res = await fetch("/api/billing/checkout", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ plan, entity: "user" }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to start checkout" }));
    throw new Error(err.detail || "Failed to start checkout");
  }
  const data = await res.json();
  if (data.url) window.location.href = data.url;
}

export default function PricingPage() {
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [loadingPlan, setLoadingPlan] = useState<PaidPlan | null>(null);
  const [checkoutError, setCheckoutError] = useState("");

  async function handleUpgrade(plan: PaidPlan) {
    const token = Cookies.get("token");
    if (!token) {
      window.location.href = `/register?plan=${plan}`;
      return;
    }
    setCheckoutError("");
    setLoadingPlan(plan);
    try {
      await startCheckout(plan);
    } catch (e) {
      setCheckoutError(e instanceof Error ? e.message : "Failed to start checkout");
    } finally {
      setLoadingPlan(null);
    }
  }

  return (
    <div style={{ background: "#0A0F1F" }} className="min-h-screen">
      <div className="max-w-6xl mx-auto px-6 py-28">

        {/* Header */}
        <div className="max-w-2xl mb-20">
          <p className="text-xs font-mono tracking-widest uppercase mb-4" style={{ color: "#14B8A6" }}>Pricing</p>
          <h1 className="text-4xl font-bold text-white tracking-tight mb-4">
            Security that scales with you
          </h1>
          <p className="text-slate-400 leading-relaxed">
            No seat fees. No per-scanner charges. Pick a plan, point your API calls at Project 73 Security, and every prompt and response is protected.
          </p>
        </div>

        {checkoutError && (
          <div className="mb-8 px-4 py-3 rounded text-sm"
            style={{ background: "rgba(248,113,113,0.07)", border: "1px solid rgba(248,113,113,0.2)", color: "#f87171" }}>
            {checkoutError}
          </div>
        )}

        {/* Tier cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5 mb-20">
          {tiers.map((tier) => (
            <div
              key={tier.name}
              className="rounded-lg flex flex-col relative overflow-hidden"
              style={{
                background: tier.highlight ? "#0d1426" : "#0A0F1F",
                border: tier.highlight ? "1px solid rgba(20,184,166,0.25)" : "1px solid rgba(255,255,255,0.06)",
              }}
            >
              {/* Top accent */}
              <div
                className="absolute top-0 left-0 right-0 h-px"
                style={{ background: tier.highlight ? "linear-gradient(90deg, #14B8A6 0%, transparent 70%)" : "linear-gradient(90deg, rgba(255,255,255,0.06) 0%, transparent 70%)" }}
              />

              <div className="p-8 flex flex-col flex-1">
                {/* Badge */}
                {"badge" in tier && tier.badge && (
                  <span
                    className="self-start text-xs font-mono px-2 py-0.5 rounded mb-4"
                    style={{ background: "rgba(20,184,166,0.1)", color: "#14B8A6" }}
                  >
                    {tier.badge}
                  </span>
                )}

                <h2 className="text-base font-semibold text-white mb-2">{tier.name}</h2>
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="text-4xl font-bold tracking-tight text-white">{tier.price}</span>
                  <span className="text-sm text-slate-500">{tier.sub}</span>
                </div>
                <p className="text-sm text-slate-500 mb-8 leading-relaxed">{tier.desc}</p>

                <ul className="space-y-3 mb-10 flex-1">
                  {tier.features.map((f) => (
                    <li key={f.text} className="flex items-start gap-3">
                      <svg className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: "#14B8A6" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                      </svg>
                      <span>
                        <span className="text-sm text-slate-300">{f.text}</span>
                        {f.note && <span className="block text-xs text-slate-600 mt-0.5">{f.note}</span>}
                      </span>
                    </li>
                  ))}
                </ul>

                {/* CTA */}
                {tier.plan ? (
                  <button
                    onClick={() => handleUpgrade(tier.plan!)}
                    disabled={loadingPlan === tier.plan}
                    className="block w-full text-center py-2.5 px-4 rounded text-sm font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
                    style={
                      tier.highlight
                        ? { background: "#14B8A6", color: "#0A0F1F" }
                        : { border: "1px solid rgba(255,255,255,0.1)", color: "#e2e8f0" }
                    }
                  >
                    {loadingPlan === tier.plan ? "Redirecting…" : tier.cta}
                  </button>
                ) : tier.href.startsWith("mailto") ? (
                  <a
                    href={tier.href}
                    className="block text-center py-2.5 px-4 rounded text-sm font-medium transition-opacity hover:opacity-90"
                    style={{ border: "1px solid rgba(255,255,255,0.1)", color: "#e2e8f0" }}
                  >
                    {tier.cta}
                  </a>
                ) : (
                  <Link
                    href={tier.href}
                    className="block text-center py-2.5 px-4 rounded text-sm font-medium transition-opacity hover:opacity-90"
                    style={{ border: "1px solid rgba(255,255,255,0.1)", color: "#e2e8f0" }}
                  >
                    {tier.cta}
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Scanner coverage */}
        <div className="mb-20">
          <div className="mb-8">
            <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>Scanner coverage</p>
            <h2 className="text-2xl font-bold text-white tracking-tight">What Project 73 Security protects against</h2>
            <p className="text-sm text-slate-500 mt-2">All categories available on Pro and Enterprise. Core security scanners on Free.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {scannerGroups.map((g) => (
              <div
                key={g.label}
                className="rounded-lg p-5 border border-white/5"
                style={{ background: "#0d1426" }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <span
                    className="text-xs font-mono px-2 py-0.5 rounded"
                    style={{ background: g.bg, color: g.color }}
                  >
                    {g.label}
                  </span>
                </div>
                <ul className="space-y-1.5">
                  {g.scanners.map((s) => (
                    <li key={s} className="flex items-center gap-2 text-xs text-slate-500">
                      <span className="w-1 h-1 rounded-full shrink-0" style={{ background: g.color, opacity: 0.6 }} />
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* FAQ */}
        <div className="mb-20">
          <div className="mb-8">
            <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>FAQ</p>
            <h2 className="text-2xl font-bold text-white tracking-tight">Common questions</h2>
          </div>
          <div className="space-y-2">
            {faqs.map((faq, i) => (
              <div key={i} className="rounded-lg border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
                <button
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  className="w-full flex items-center justify-between px-6 py-4 text-left gap-4"
                >
                  <span className="text-sm font-medium text-white">{faq.q}</span>
                  <svg
                    className="w-4 h-4 shrink-0 transition-transform duration-200"
                    style={{ color: "#475569", transform: openFaq === i ? "rotate(180deg)" : "rotate(0deg)" }}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {openFaq === i && (
                  <div className="px-6 pb-5 border-t border-white/5 pt-4">
                    <p className="text-sm text-slate-500 leading-relaxed">{faq.a}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Bottom CTA */}
        <div className="rounded-lg p-10 border border-white/5 relative overflow-hidden" style={{ background: "#0d1426" }}>
          <div className="absolute top-0 left-0 right-0 h-px" style={{ background: "linear-gradient(90deg, #14B8A6 0%, transparent 50%)" }} />
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
            <div>
              <h2 className="text-xl font-bold text-white tracking-tight mb-2">Not sure which plan fits?</h2>
              <p className="text-sm text-slate-500 leading-relaxed">
                Start free — no credit card, no time limit. Upgrade when you&apos;re ready, or talk to us for enterprise needs.
              </p>
            </div>
            <div className="flex gap-3 shrink-0">
              <Link
                href="/register"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded font-medium text-sm transition-opacity hover:opacity-90"
                style={{ background: "#14B8A6", color: "#0A0F1F" }}
              >
                Start free →
              </Link>
              <a
                href="mailto:sales@project73.ai"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded font-medium text-sm border border-white/10 text-slate-300 hover:border-white/20 hover:text-white transition-colors"
              >
                Contact sales
              </a>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
