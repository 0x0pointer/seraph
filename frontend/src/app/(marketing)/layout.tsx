import Link from "next/link";
import CookieBanner from "@/components/marketing/CookieBanner";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col" style={{ background: "#0A0F1F" }}>
      <nav className="border-b border-white/5 sticky top-0 z-50" style={{ background: "rgba(10,15,31,0.92)", backdropFilter: "blur(12px)" }}>
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex justify-between items-center h-16">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="w-6 h-6 rounded" style={{ background: "#14B8A6" }} />
              <span className="text-white font-semibold tracking-tight">Project 73</span>
              <span className="text-xs font-mono font-bold tracking-widest px-1.5 py-0.5 rounded" style={{ background: "rgba(20,184,166,0.12)", color: "#14B8A6", fontSize: "0.6rem", letterSpacing: "0.12em" }}>BETA</span>
            </Link>
            <div className="hidden md:flex items-center gap-8">
              <Link href="/#features" className="text-sm text-slate-400 hover:text-white transition-colors">Features</Link>
              <Link href="/playground" className="text-sm text-slate-400 hover:text-white transition-colors">Playground</Link>
              <Link href="/pricing" className="text-sm text-slate-400 hover:text-white transition-colors">Pricing</Link>
              <Link href="/docs" className="text-sm text-slate-400 hover:text-white transition-colors">Docs</Link>
              <Link href="/about" className="text-sm text-slate-400 hover:text-white transition-colors">About</Link>
              <Link href="/login" className="nav-signin text-sm font-medium px-4 py-2 rounded">
                Sign in
              </Link>
            </div>
          </div>
        </div>
      </nav>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-white/5 py-10">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
            {/* Brand */}
            <div className="flex items-center gap-2.5">
              <span className="w-4 h-4 rounded-sm" style={{ background: "#14B8A6" }} />
              <span className="text-sm text-slate-500">Project 73</span>
            </div>

            {/* Nav links */}
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              <Link href="/docs" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Docs</Link>
              <Link href="/pricing" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Pricing</Link>
              <Link href="/about" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">About</Link>
              <span className="text-xs text-slate-700">·</span>
              <Link href="/terms" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Terms of Service</Link>
              <Link href="/privacy" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Privacy Policy</Link>
              <Link href="/cookies" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Cookie Policy</Link>
            </div>

            {/* Copyright */}
            <p className="text-xs text-slate-700">© 2026 Project 73 Security</p>
          </div>
        </div>
      </footer>

      <CookieBanner />
    </div>
  );
}
