const team = [
  {
    name: "Jorge Carvalho",
    role: "CEO & Founder",
    tags: ["AppSec", "AI Security", "AI Red Teaming"],
    bio: "Application security and AI security engineer with hands-on experience in AI red teaming. Built Project 73 to solve the gap between AI deployment speed and real-world safety requirements.",
    initials: "JC",
  },
];


export default function AboutPage() {
  return (
    <div style={{ background: "#0A0F1F" }} className="min-h-screen">
      <div className="max-w-6xl mx-auto px-6 py-28">

        {/* Mission */}
        <div className="max-w-2xl mb-24">
          <p className="text-xs font-mono tracking-widest uppercase mb-4" style={{ color: "#14B8A6" }}>Mission</p>
          <h1 className="text-4xl font-bold text-white tracking-tight mb-6 leading-tight">
            Every AI application deserves production-grade safety rails.
          </h1>
          <p className="text-slate-400 leading-relaxed">
            We built Project 73 Security because we kept seeing the same problem: teams shipping AI features
            without any guardrails, then scrambling when something went wrong. The tools existed — they
            just weren&apos;t wrapped in something you could actually deploy. So we built that wrapper.
          </p>
        </div>

        {/* Team */}
        <div className="mb-24">
          <p className="text-xs font-mono tracking-widest uppercase mb-10" style={{ color: "#14B8A6" }}>Team</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {team.map((member) => (
              <div key={member.name} className="rounded-lg border border-white/5 p-8 relative overflow-hidden" style={{ background: "#0d1426" }}>
                <div className="absolute top-0 left-0 right-0 h-px" style={{ background: "linear-gradient(90deg, #14B8A6 0%, transparent 60%)" }} />
                <div className="flex items-start gap-5">
                  <div
                    className="w-12 h-12 rounded-lg flex items-center justify-center text-sm font-bold shrink-0"
                    style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6" }}
                  >
                    {member.initials}
                  </div>
                  <div className="flex-1">
                    <h3 className="text-white font-semibold text-lg mb-0.5">{member.name}</h3>
                    <p className="text-sm mb-3" style={{ color: "#14B8A6" }}>{member.role}</p>
                    <div className="flex flex-wrap gap-2 mb-4">
                      {member.tags.map((tag) => (
                        <span key={tag} className="text-xs font-mono px-2 py-0.5 rounded"
                          style={{ background: "rgba(255,255,255,0.05)", color: "#94a3b8" }}>
                          {tag}
                        </span>
                      ))}
                    </div>
                    <p className="text-sm text-slate-500 leading-relaxed">{member.bio}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Values */}
        <div className="rounded-lg p-10 border border-white/5 mb-12" style={{ background: "#0d1426" }}>
          <p className="text-xs font-mono tracking-widest uppercase mb-4" style={{ color: "#14B8A6" }}>What we believe</p>
          <h2 className="text-2xl font-bold text-white tracking-tight mb-3">Security should ship with the feature, not after the incident.</h2>
          <p className="text-slate-400 leading-relaxed max-w-xl mb-6">
            AI moves fast. Safety tooling needs to move just as fast. Project 73 Security is designed to be
            dropped into any existing stack in minutes — no research required, no custom model training,
            no ops overhead. Configure, integrate, monitor.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-8">
            {[
              { label: "Simple by default", desc: "Sensible defaults out of the box. Advanced tuning when you need it." },
              { label: "Full transparency", desc: "Every scan is logged with scanner-level scores. No black boxes." },
              { label: "Built to extend", desc: "Custom rules, custom scanners, custom thresholds — all first-class." },
            ].map((v) => (
              <div key={v.label} className="border-t border-white/10 pt-5">
                <p className="text-sm font-semibold text-white mb-2">{v.label}</p>
                <p className="text-xs text-slate-500 leading-relaxed">{v.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Contact */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-white/5 p-7 flex items-start gap-4" style={{ background: "#0d1426" }}>
            <div className="w-9 h-9 rounded flex items-center justify-center shrink-0" style={{ background: "rgba(20,184,166,0.1)" }}>
              <svg className="w-4 h-4" style={{ color: "#14B8A6" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold text-white mb-1">General support</p>
              <p className="text-xs text-slate-500 mb-3 leading-relaxed">Questions about the product, your account, or integrations.</p>
              <a href="mailto:support@project73.ai" className="text-xs font-mono transition-colors hover:text-white" style={{ color: "#14B8A6" }}>
                support@project73.ai
              </a>
            </div>
          </div>
          <div className="rounded-lg border border-white/5 p-7 flex items-start gap-4" style={{ background: "#0d1426" }}>
            <div className="w-9 h-9 rounded flex items-center justify-center shrink-0" style={{ background: "rgba(248,113,113,0.1)" }}>
              <svg className="w-4 h-4" style={{ color: "#f87171" }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold text-white mb-1">Security disclosures</p>
              <p className="text-xs text-slate-500 mb-3 leading-relaxed">Found a vulnerability? Please reach out privately — we take security reports seriously.</p>
              <a href="mailto:security@project73.ai" className="text-xs font-mono transition-colors hover:text-white" style={{ color: "#f87171" }}>
                security@project73.ai
              </a>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
