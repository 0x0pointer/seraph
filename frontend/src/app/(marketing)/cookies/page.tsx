export default function CookiesPage() {
  const cookieTable = [
    {
      name: "token",
      type: "Essential",
      purpose: "Stores your authentication JWT to keep you logged in across page navigations.",
      duration: "Session (expires on logout or after 1 hour of inactivity)",
      provider: "Project 73 Security",
    },
    {
      name: "cookie_consent",
      type: "Essential",
      purpose: "Remembers your cookie consent preference so we don't show the banner on every visit.",
      duration: "1 year",
      provider: "Project 73 Security",
    },
  ];

  const sections = [
    {
      title: "1. What Are Cookies?",
      body: `Cookies are small text files placed on your device by websites you visit. They are widely used to make websites work efficiently and to provide information to site owners. Cookies do not harm your device and do not contain personally identifiable information on their own.`,
    },
    {
      title: "2. How We Use Cookies",
      body: `Project 73 Security uses cookies strictly for essential operational purposes: to keep you authenticated while using the dashboard and to remember your privacy preferences. We do not use advertising cookies, cross-site tracking cookies, or third-party analytics cookies.`,
    },
    {
      title: "3. Types of Cookies We Use",
      body: `We only use Essential cookies — cookies that are strictly necessary for the Service to function. Without these cookies, features like staying logged in would not work. Because these cookies are essential, they do not require your consent under most privacy regulations; however, we disclose them here for transparency.`,
    },
    {
      title: "4. Third-Party Cookies",
      body: `We do not currently use any third-party cookies (e.g., from analytics providers, social media platforms, or advertising networks). If this changes, we will update this policy and seek your consent where required.`,
    },
    {
      title: "5. Managing Cookies",
      body: `You can control and delete cookies through your browser settings. Please note that disabling essential cookies will prevent you from logging in and using the dashboard. Most browsers allow you to: view cookies stored on your device; delete cookies individually or all at once; block cookies from specific websites; block all third-party cookies. Refer to your browser's help documentation for instructions.`,
    },
    {
      title: "6. Your Consent",
      body: `When you first visit our website, we show a cookie banner explaining our use of cookies. By clicking "Accept" you consent to our use of cookies as described in this policy. You may withdraw consent at any time by clearing your cookies and declining via the banner on your next visit. Withdrawing consent for essential cookies will affect your ability to use the Service.`,
    },
    {
      title: "7. Changes to This Policy",
      body: `We may update this Cookie Policy if we introduce new cookies or change how we use existing ones. We will notify you of significant changes by updating the effective date and, where appropriate, displaying a new consent banner.`,
    },
    {
      title: "8. Contact",
      body: `For questions about our use of cookies, contact us at privacy@project73.ai.`,
    },
  ];

  return (
    <div style={{ background: "#0A0F1F" }}>
      <div className="max-w-3xl mx-auto px-6 py-20">
        {/* Header */}
        <div className="mb-14">
          <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>Legal</p>
          <h1 className="text-4xl font-bold text-white tracking-tight mb-4">Cookie Policy</h1>
          <p className="text-sm text-slate-500">Effective date: January 1, 2026 · Last updated: February 24, 2026</p>
        </div>

        {/* Intro */}
        <p className="text-slate-400 leading-relaxed mb-12 text-sm">
          This Cookie Policy explains what cookies are, which cookies Project 73 Security uses, and how you can manage them.
        </p>

        {/* Cookie table */}
        <div className="mb-14">
          <h2 className="text-base font-semibold text-white mb-5">Cookies We Use</h2>
          <div className="rounded-lg overflow-hidden border border-white/5">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: "#0d1426" }}>
                  {["Name", "Type", "Purpose", "Duration", "Provider"].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-slate-400 font-medium border-b border-white/5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cookieTable.map((row, i) => (
                  <tr key={row.name} style={{ background: i % 2 === 0 ? "#0A0F1F" : "#0d1426" }}>
                    <td className="px-4 py-3 font-mono text-white">{row.name}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded text-xs font-mono" style={{ background: "rgba(20,184,166,0.1)", color: "#14B8A6" }}>
                        {row.type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-500 leading-relaxed">{row.purpose}</td>
                    <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{row.duration}</td>
                    <td className="px-4 py-3 text-slate-500">{row.provider}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Sections */}
        <div className="space-y-10">
          {sections.map((s) => (
            <div key={s.title} className="border-t border-white/5 pt-8">
              <h2 className="text-base font-semibold text-white mb-3">{s.title}</h2>
              <p className="text-sm text-slate-500 leading-relaxed">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
