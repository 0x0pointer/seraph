export default function TermsPage() {
  const sections = [
    {
      title: "1. Acceptance of Terms",
      body: `By accessing or using Project 73 Security (the "Service"), you agree to be bound by these Terms of Service ("Terms"). If you do not agree to these Terms, do not use the Service. These Terms apply to all users, including individuals, organizations, and API integrators.`,
    },
    {
      title: "2. Description of Service",
      body: `Project 73 Security provides an AI guardrails platform that allows users to scan prompts and LLM outputs for safety, compliance, and security violations. The Service includes a REST API, a web dashboard, audit logging, organization management, and related features.`,
    },
    {
      title: "3. Account Registration",
      body: `You must create an account to access the Service. You are responsible for maintaining the confidentiality of your credentials and for all activity that occurs under your account. You agree to provide accurate, current, and complete information and to update it as necessary. You must be at least 18 years old to create an account.`,
    },
    {
      title: "4. Acceptable Use",
      body: `You agree not to use the Service to: (a) violate any applicable law or regulation; (b) infringe the intellectual property rights of any third party; (c) transmit harmful, unlawful, or abusive content; (d) attempt to gain unauthorized access to any system or network; (e) reverse engineer, decompile, or disassemble the Service; (f) use the Service to train competing AI models or products without prior written consent; or (g) resell or sublicense the Service without authorization.`,
    },
    {
      title: "5. API Usage",
      body: `Access to the Project 73 Security API is subject to rate limits and fair use policies. We reserve the right to throttle or suspend API access for accounts that exceed usage limits or abuse the Service. API keys and connection credentials must be kept confidential and must not be shared or embedded in publicly accessible code.`,
    },
    {
      title: "6. Organizations and Teams",
      body: `When you create or join an organization, you agree that organization administrators may access, manage, and export data associated with your account within that organization. Organization admins are responsible for ensuring their members comply with these Terms.`,
    },
    {
      title: "7. Intellectual Property",
      body: `The Service, including all software, design, documentation, and content, is owned by Project 73 Security and protected by intellectual property laws. You retain ownership of any content you submit through the Service. By using the Service, you grant us a limited, non-exclusive license to process your content solely to provide the Service.`,
    },
    {
      title: "8. Data and Privacy",
      body: `Our collection and use of personal data is governed by our Privacy Policy, which is incorporated into these Terms by reference. By using the Service, you consent to such collection and use.`,
    },
    {
      title: "9. Disclaimer of Warranties",
      body: `THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED. WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE, OR FREE OF HARMFUL COMPONENTS. YOUR USE OF THE SERVICE IS AT YOUR SOLE RISK.`,
    },
    {
      title: "10. Limitation of Liability",
      body: `TO THE FULLEST EXTENT PERMITTED BY LAW, PROJECT 73 SECURITY SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS, DATA, OR GOODWILL, ARISING FROM YOUR USE OF OR INABILITY TO USE THE SERVICE. OUR TOTAL LIABILITY SHALL NOT EXCEED THE AMOUNT PAID BY YOU IN THE TWELVE MONTHS PRECEDING THE CLAIM.`,
    },
    {
      title: "11. Termination",
      body: `We may suspend or terminate your access to the Service at any time, with or without cause or notice, including for breach of these Terms. Upon termination, your right to use the Service ceases immediately. Provisions that by their nature should survive termination will survive.`,
    },
    {
      title: "12. Changes to Terms",
      body: `We reserve the right to modify these Terms at any time. We will notify you of material changes by posting the updated Terms on our website with a revised effective date. Your continued use of the Service after such changes constitutes acceptance of the new Terms.`,
    },
    {
      title: "13. Governing Law",
      body: `These Terms are governed by and construed in accordance with applicable law. Any disputes arising under these Terms shall be resolved through binding arbitration or in a court of competent jurisdiction, as determined by Project 73 Security.`,
    },
    {
      title: "14. Contact",
      body: `If you have questions about these Terms, contact us at legal@project73.ai.`,
    },
  ];

  return (
    <div style={{ background: "#0A0F1F" }}>
      <div className="max-w-3xl mx-auto px-6 py-20">
        {/* Header */}
        <div className="mb-14">
          <p className="text-xs font-mono tracking-widest uppercase mb-3" style={{ color: "#14B8A6" }}>Legal</p>
          <h1 className="text-4xl font-bold text-white tracking-tight mb-4">Terms of Service</h1>
          <p className="text-sm text-slate-500">Effective date: January 1, 2026 · Last updated: February 24, 2026</p>
        </div>

        {/* Intro */}
        <p className="text-slate-400 leading-relaxed mb-12 text-sm">
          Please read these Terms of Service carefully before using the Project 73 Security platform. These Terms form a legally binding agreement between you and Project 73 Security.
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
