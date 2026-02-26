export default function PrivacyPage() {
  const sections = [
    {
      title: "1. Who We Are",
      body: `Project 73 Security ("we", "our", "us") operates the Project 73 Security AI guardrails platform. This Privacy Policy explains how we collect, use, store, and protect your personal data when you use our website, dashboard, or API.`,
    },
    {
      title: "2. Information We Collect",
      body: `We collect information you provide directly: account details (username, email, password hash), organization information, and content you submit through the API (prompts and LLM outputs processed for scanning). We also collect information automatically: IP addresses, browser type, pages visited, API request metadata, and session data. We do not sell your personal data.`,
    },
    {
      title: "3. How We Use Your Information",
      body: `We use your data to: (a) provide, operate, and improve the Service; (b) authenticate your identity and manage your account; (c) process API scan requests and return results; (d) maintain audit logs and analytics for you and your organization; (e) send transactional communications (e.g., invite emails, security alerts); (f) comply with legal obligations; and (g) detect and prevent fraud or abuse.`,
    },
    {
      title: "4. Scan Content",
      body: `Text submitted for scanning (prompts and LLM outputs) is processed in real time to run guardrail checks. This content is stored in audit logs for the duration of your data retention period and is accessible to you, your organization admins, and our platform administrators. We do not use your scan content to train our models or share it with third parties.`,
    },
    {
      title: "5. Data Retention",
      body: `We retain your account data for as long as your account is active. Audit log entries are retained for 90 days by default; this may be configurable depending on your plan. You may request deletion of your account and associated data at any time by contacting us. Some data may be retained for a limited period after deletion to comply with legal obligations.`,
    },
    {
      title: "6. Data Sharing",
      body: `We do not sell, rent, or trade your personal data. We may share data with: (a) service providers that help us operate the Service (hosting, email delivery), bound by confidentiality agreements; (b) law enforcement or government authorities when required by law; (c) a successor entity in the event of a merger, acquisition, or sale of assets. Organization admins within your organization can see data scoped to that organization.`,
    },
    {
      title: "7. Security",
      body: `We implement industry-standard security measures including encrypted storage, secure HTTPS connections, hashed passwords (bcrypt), and JWT-based authentication. Despite these measures, no system is completely secure. You are responsible for keeping your API keys and login credentials confidential.`,
    },
    {
      title: "8. Your Rights",
      body: `Depending on your jurisdiction, you may have the right to: access the personal data we hold about you; request correction of inaccurate data; request deletion of your data; restrict or object to certain processing; and data portability. To exercise these rights, contact us at privacy@project73.ai. We will respond within 30 days.`,
    },
    {
      title: "9. Cookies",
      body: `We use cookies to maintain your authenticated session (essential cookies). Please see our Cookie Policy for full details on the cookies we use and how to manage them.`,
    },
    {
      title: "10. International Transfers",
      body: `Your data may be processed in countries other than your own. Where required by law, we implement appropriate safeguards for international data transfers, such as standard contractual clauses.`,
    },
    {
      title: "11. Children's Privacy",
      body: `The Service is not directed at individuals under 18. We do not knowingly collect personal data from minors. If you believe a minor has provided us with personal data, contact us and we will delete it promptly.`,
    },
    {
      title: "12. Changes to This Policy",
      body: `We may update this Privacy Policy from time to time. We will notify you of significant changes by posting the updated policy with a revised effective date. Continued use of the Service after changes constitutes acceptance of the updated policy.`,
    },
    {
      title: "13. Contact Us",
      body: `For privacy-related questions or requests, contact our Data Protection contact at: privacy@project73.ai. For general inquiries: hello@project73.ai.`,
    },
  ];

  return (
    <div style={{ background: "#0A0F1F" }}>
      <div className="max-w-3xl mx-auto px-6 py-20">
        {/* Header */}
        <div className="mb-14">
          <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>Legal</p>
          <h1 className="text-4xl font-bold text-white tracking-tight mb-4">Privacy Policy</h1>
          <p className="text-sm text-slate-500">Effective date: January 1, 2026 · Last updated: February 24, 2026</p>
        </div>

        {/* Intro */}
        <p className="text-slate-400 leading-relaxed mb-12 text-sm">
          Your privacy matters to us. This policy describes what personal data Project 73 Security collects, why we collect it, and how you can exercise your rights.
        </p>

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
