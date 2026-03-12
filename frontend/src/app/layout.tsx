import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SKF Guard — LLM Security Platform",
  description:
    "Protect your AI applications with production-ready LLM guardrails. Input/output scanning, audit logs, real-time dashboard.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      {/* Apply saved theme before paint to prevent flash */}
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('theme')||'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
