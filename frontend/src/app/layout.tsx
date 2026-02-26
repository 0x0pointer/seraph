import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Project 73 — LLM Security Platform",
  description:
    "Protect your AI applications with production-ready LLM guardrails. Input/output scanning, audit logs, real-time dashboard.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
