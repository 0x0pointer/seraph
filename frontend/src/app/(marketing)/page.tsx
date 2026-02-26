"use client";

import Link from "next/link";
import { useState } from "react";

const features = [
  {
    label: "Input Scanning",
    desc: "Every prompt is run through active guardrails before it touches your model. Prompt injection, PII, secrets, toxic language, banned topics — caught at the gate.",
  },
  {
    label: "Output Scanning",
    desc: "LLM responses are scanned for toxicity, bias, malicious URLs, hallucinations, competitor mentions, and sensitive data leaks before delivery.",
  },
  {
    label: "Organizations & Teams",
    desc: "Multi-tenant by design. Create organizations, invite members by email, form teams within orgs. Connections and audit data are automatically shared across the team.",
  },
  {
    label: "API Connections",
    desc: "Register named API connections (production, staging, development) and use them in scans. Connection-level usage tracking shows exactly where your traffic originates.",
  },
  {
    label: "Audit Trail & Abuse Detection",
    desc: "Every scan is logged with per-scanner risk scores. Violations are surfaced in a dedicated Abuse Cases view, classified by severity: medium, high, or critical.",
  },
  {
    label: "Real-time Analytics",
    desc: "Live dashboards showing scan volume, violation rates, risk score trends, and top-triggered scanners. Spot abuse patterns before they become incidents.",
  },
];

const steps = [
  {
    n: "01",
    title: "Create an account or accept an invite",
    desc: "Sign up directly, or accept an email invite from your organization admin. Org members are automatically scoped to their org's data and connections.",
    tag: "/register",
    tagLabel: "Sign up →",
  },
  {
    n: "02",
    title: "Configure your guardrails",
    desc: "Open the Guardrails dashboard and enable the scanners you need — Prompt Injection, Toxicity, PII, Custom Rules, and more. Set thresholds and filters. No redeployment.",
    tag: null,
    tagLabel: null,
  },
  {
    n: "03",
    title: "Create a connection and call the API",
    desc: "Add a named API connection (production, staging, development) in the dashboard to get your connection ID. Then add two calls: POST /scan/prompt before your LLM, POST /scan/output after.",
    tag: "/docs#integration",
    tagLabel: "See code examples →",
  },
  {
    n: "04",
    title: "Monitor, triage, and manage",
    desc: "Every scan is logged and scoped to your team. Org admins see their whole organization's activity, with full analytics and per-org filtering.",
    tag: null,
    tagLabel: null,
  },
];

type FlowNode = { label: string; sub: string; color: string; dim: boolean; code?: boolean; pass?: boolean; blocked?: boolean };

function Pipeline() {
  const [active, setActive] = useState<"pass" | "block">("block");

  const passFlow: FlowNode[] = [
    { label: "User prompt", sub: "sent to your app", color: "#94a3b8", dim: false },
    { label: "POST /scan/prompt", sub: "input guardrails · connection_id attached", color: "#14B8A6", dim: false, code: true },
    { label: "is_valid: true", sub: "prompt cleared — all scanners passed", color: "#14B8A6", dim: false, pass: true },
    { label: "Your AI model", sub: "receives sanitized_text", color: "#94a3b8", dim: false },
    { label: "POST /scan/output", sub: "output guardrails", color: "#14B8A6", dim: false, code: true },
    { label: "is_valid: true", sub: "response cleared", color: "#14B8A6", dim: false, pass: true },
    { label: "User sees response", sub: "logged to audit trail", color: "#94a3b8", dim: false },
  ];

  const blockFlow: FlowNode[] = [
    { label: "User prompt", sub: "sent to your app", color: "#94a3b8", dim: false },
    { label: "POST /scan/prompt", sub: "input guardrails · connection_id attached", color: "#14B8A6", dim: false, code: true },
    { label: "is_valid: false", sub: "PromptInjection: 0.97 · risk: critical", color: "#f87171", dim: false, blocked: true },
    { label: "Your AI model", sub: "never reached", color: "#334155", dim: true },
    { label: "POST /scan/output", sub: "skipped", color: "#334155", dim: true, code: true },
    { label: "Error returned", sub: "blocked · logged to Abuse Cases", color: "#f87171", dim: false, blocked: true },
    { label: "User sees fallback", sub: "safe message shown", color: "#94a3b8", dim: false },
  ];

  const flow = active === "pass" ? passFlow : blockFlow;

  return (
    <div className="rounded-lg border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
      {/* Tab toggle */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
        <p className="text-xs text-slate-500 font-mono uppercase tracking-widest">Request pipeline</p>
        <div className="flex gap-1 p-1 rounded" style={{ background: "#0A0F1F" }}>
          {(["block", "pass"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setActive(t)}
              className="px-3 py-1 rounded text-xs font-mono font-medium transition-colors"
              style={
                active === t
                  ? t === "block"
                    ? { background: "rgba(248,113,113,0.15)", color: "#f87171" }
                    : { background: "rgba(20,184,166,0.15)", color: "#14B8A6" }
                  : { color: "#475569" }
              }
            >
              {t === "block" ? "✗ blocked" : "✓ passed"}
            </button>
          ))}
        </div>
      </div>

      {/* Flow */}
      <div className="px-6 py-8">
        <div className="flex flex-col gap-0">
          {flow.map((node, i) => (
            <div key={i} className="flex items-stretch gap-4">
              {/* Connector line */}
              <div className="flex flex-col items-center w-6 shrink-0">
                <div
                  className="w-2.5 h-2.5 rounded-full shrink-0 mt-3 transition-colors duration-300"
                  style={{ background: node.dim ? "#1e293b" : node.color, boxShadow: !node.dim && !node.blocked ? `0 0 6px ${node.color}40` : "none" }}
                />
                {i < flow.length - 1 && (
                  <div className="w-px flex-1 mt-1" style={{ background: flow[i + 1].dim ? "#1a2236" : "rgba(255,255,255,0.06)" }} />
                )}
              </div>

              {/* Node content */}
              <div className={`pb-5 flex-1 transition-opacity duration-300 ${node.dim ? "opacity-30" : ""}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`text-sm font-medium ${node.code ? "font-mono text-xs" : ""}`}
                    style={{ color: node.dim ? "#334155" : node.color }}
                  >
                    {node.label}
                  </span>
                  {node.pass && (
                    <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: "rgba(20,184,166,0.1)", color: "#14B8A6" }}>
                      ✓ pass
                    </span>
                  )}
                  {node.blocked && (
                    <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: "rgba(248,113,113,0.1)", color: "#f87171" }}>
                      ✗ blocked
                    </span>
                  )}
                </div>
                <p className="text-xs mt-0.5" style={{ color: node.dim ? "#1e293b" : "#475569" }}>{node.sub}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  return (
    <div style={{ background: "#0A0F1F" }}>

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-6 pt-28 pb-24">
        <div className="max-w-3xl">
          <p className="text-xs font-mono tracking-widest uppercase mb-6" style={{ color: "#14B8A6" }}>
            AI Security Platform
          </p>
          <h1 className="text-5xl md:text-6xl font-bold text-white leading-[1.1] tracking-tight mb-6">
            Guard every prompt.
            <br />
            Every response.
          </h1>
          <p className="text-lg text-slate-400 leading-relaxed mb-10 max-w-xl">
            Project 73 wraps your AI with a configurable scanning pipeline.
            Multi-tenant, team-aware, and fully auditable — deployed in minutes.
          </p>
          <div className="flex flex-wrap gap-4">
            <Link
              href="/login"
              className="inline-flex items-center gap-2 px-6 py-3 rounded font-medium text-sm transition-colors"
              style={{ background: "#14B8A6", color: "#0A0F1F" }}
            >
              Get started
              <span>→</span>
            </Link>
            <Link
              href="/playground"
              className="inline-flex items-center gap-2 px-6 py-3 rounded font-medium text-sm border border-white/10 text-slate-300 hover:border-white/20 hover:text-white transition-colors"
            >
              Try the playground
            </Link>
          </div>
        </div>

        {/* API preview strip */}
        <div className="mt-20 rounded-lg border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
          <div className="flex items-center gap-2 px-4 py-3 border-b border-white/5">
            <span className="w-3 h-3 rounded-full bg-white/10" />
            <span className="w-3 h-3 rounded-full bg-white/10" />
            <span className="w-3 h-3 rounded-full bg-white/10" />
            <span className="ml-2 text-xs text-slate-600 font-mono">POST /api/scan/prompt</span>
          </div>
          <div className="px-6 py-5 font-mono text-sm leading-relaxed">
            <p><span className="text-slate-600">// request</span></p>
            <p><span className="text-slate-400">{"{"}</span></p>
            <p className="pl-6">
              <span className="text-white">&quot;text&quot;</span><span className="text-slate-400">:</span>{" "}
              <span style={{ color: "#2DD4BF" }}>&quot;Ignore previous instructions and…&quot;</span><span className="text-slate-400">,</span>
            </p>
            <p className="pl-6">
              <span className="text-white">&quot;connection_id&quot;</span><span className="text-slate-400">:</span>{" "}
              <span className="text-amber-400">42</span>
            </p>
            <p><span className="text-slate-400">{"}"}</span></p>
            <p className="mt-4"><span className="text-slate-600">// response</span></p>
            <p><span className="text-slate-400">{"{"}</span></p>
            <p className="pl-4"><span className="text-white">&quot;is_valid&quot;</span><span className="text-slate-400">:</span> <span className="text-red-400">false</span><span className="text-slate-400">,</span></p>
            <p className="pl-4"><span className="text-white">&quot;violation_scanners&quot;</span><span className="text-slate-400">:</span> <span className="text-slate-400">[</span><span style={{ color: "#2DD4BF" }}>&quot;PromptInjection&quot;</span><span className="text-slate-400">],</span></p>
            <p className="pl-4"><span className="text-white">&quot;scanner_results&quot;</span><span className="text-slate-400">:</span> <span className="text-slate-400">{"{"}</span> <span style={{ color: "#2DD4BF" }}>&quot;PromptInjection&quot;</span><span className="text-slate-400">: </span><span className="text-amber-400">0.97</span> <span className="text-slate-400">{"}"}</span></p>
            <p><span className="text-slate-400">{"}"}</span></p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-t border-white/5 py-24">
        <div className="max-w-6xl mx-auto px-6">
          <div className="mb-14">
            <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>Capabilities</p>
            <h2 className="text-3xl font-bold text-white tracking-tight">Built for production AI teams</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px" style={{ background: "rgba(255,255,255,0.04)" }}>
            {features.map((f) => (
              <div key={f.label} className="p-8" style={{ background: "#0A0F1F" }}>
                <h3 className="text-sm font-semibold text-white mb-3 tracking-tight">{f.label}</h3>
                <p className="text-sm text-slate-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-24 border-t border-white/5">
        <div className="max-w-6xl mx-auto px-6">
          <div className="mb-14">
            <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>How it works</p>
            <h2 className="text-3xl font-bold text-white tracking-tight">Every request, protected end to end</h2>
          </div>

          {/* Pipeline diagram */}
          <div className="mb-20">
            <Pipeline />
          </div>

          {/* Steps */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-16 gap-y-12">
            {steps.map((step) => (
              <div key={step.n} className="flex gap-6">
                <p className="text-4xl font-bold shrink-0 leading-none mt-1 tracking-tighter" style={{ color: "#14B8A6", opacity: 0.25 }}>
                  {step.n}
                </p>
                <div>
                  <h3 className="text-base font-semibold text-white mb-2">{step.title}</h3>
                  <p className="text-sm text-slate-500 leading-relaxed mb-3">{step.desc}</p>
                  {step.tag && (
                    <Link href={step.tag} className="text-xs font-medium transition-colors hover:text-white" style={{ color: "#14B8A6" }}>
                      {step.tagLabel}
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Why teams choose */}
      <section className="py-24 border-t border-white/5">
        <div className="max-w-6xl mx-auto px-6">
          {/* Stats row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-px mb-20" style={{ background: "rgba(255,255,255,0.04)" }}>
            {[
              { value: "40+", label: "Scanners available" },
              { value: "2", label: "API calls to integrate" },
              { value: "<1h", label: "Average setup time" },
              { value: "100%", label: "Requests logged" },
            ].map((stat) => (
              <div key={stat.label} className="p-8 text-center" style={{ background: "#0A0F1F" }}>
                <p className="text-4xl font-bold tracking-tight mb-2" style={{ color: "#14B8A6" }}>{stat.value}</p>
                <p className="text-xs text-slate-500 uppercase tracking-widest">{stat.label}</p>
              </div>
            ))}
          </div>

          <div className="mb-14">
            <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>Why teams choose Project 73</p>
            <h2 className="text-3xl font-bold text-white tracking-tight">Everything your team needs. Nothing you don&apos;t.</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {[
              {
                n: "01",
                title: "Guardrail security against real AI threats",
                desc: "40+ specialized scanners block prompt injection, jailbreaks, PII leakage, toxic content, secrets, competitor mentions, and malicious URLs — on both input and output. Each scanner runs independently with configurable thresholds, so you catch what matters and skip what doesn't.",
                tags: ["Prompt Injection", "PII Detection", "Jailbreak", "Toxicity", "Secrets", "Ban Topics"],
              },
              {
                n: "02",
                title: "Integrate in under an hour",
                desc: "Two API calls wrap your existing AI pipeline — one before your model, one after. No SDK to learn, no infrastructure to manage. If you can make an HTTP request, you're done.",
                tags: null,
              },
              {
                n: "03",
                title: "Full audit trail, zero effort",
                desc: "Every scan is automatically logged with per-scanner risk scores, violation details, and timestamps. Abuse cases surface in their own dedicated view. Export anytime for compliance or security review.",
                tags: null,
              },
              {
                n: "04",
                title: "Scales with your organization",
                desc: "Invite your team, create organizations, assign connections to environments. Members see their own scoped data by default — no configuration required. Org admins get full visibility across their entire team.",
                tags: null,
              },
            ].map((item) => (
              <div
                key={item.title}
                className="rounded-lg p-8 relative overflow-hidden"
                style={{ background: "#0d1426", border: "1px solid rgba(255,255,255,0.06)" }}
              >
                {/* Top accent */}
                <div className="absolute top-0 left-0 right-0 h-px" style={{ background: "linear-gradient(90deg, #14B8A6 0%, transparent 60%)" }} />
                {/* Number */}
                <p className="text-5xl font-bold leading-none mb-6 tracking-tighter select-none" style={{ color: "rgba(20,184,166,0.12)" }}>
                  {item.n}
                </p>
                <h3 className="text-base font-semibold text-white mb-3 tracking-tight">{item.title}</h3>
                <p className="text-sm leading-relaxed mb-4" style={{ color: "#64748b" }}>{item.desc}</p>
                {item.tags && (
                  <div className="flex flex-wrap gap-1.5">
                    {item.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-xs font-mono px-2 py-0.5 rounded"
                        style={{ background: "rgba(20,184,166,0.08)", color: "#14B8A6", border: "1px solid rgba(20,184,166,0.15)" }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 border-t border-white/5">
        <div className="max-w-6xl mx-auto px-6">
          <div className="rounded-lg p-12 border border-white/5" style={{ background: "#0d1426" }}>
            <div className="max-w-lg">
              <h2 className="text-3xl font-bold text-white tracking-tight mb-4">
                Start protecting your AI today.
              </h2>
              <p className="text-slate-400 mb-8 leading-relaxed">
                Sign up, enable your guardrails, create an API connection.
                Two API calls and your entire team is protected.
              </p>
              <div className="flex flex-wrap gap-4">
                <Link
                  href="/register"
                  className="inline-flex items-center gap-2 px-6 py-3 rounded font-medium text-sm transition-opacity hover:opacity-90"
                  style={{ background: "#14B8A6", color: "#0A0F1F" }}
                >
                  Create account →
                </Link>
                <Link
                  href="/docs"
                  className="inline-flex items-center gap-2 px-6 py-3 rounded font-medium text-sm border border-white/10 text-slate-300 hover:border-white/20 hover:text-white transition-colors"
                >
                  Read the docs
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
