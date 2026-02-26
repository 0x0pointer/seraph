"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { api } from "@/lib/api";
import { format } from "date-fns";

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlanInfo {
  plan: string;
  is_org_plan: boolean;
  scan_limit: number | null;
  scans_used: number;
  scans_remaining: number | null;
  scan_pct: number;
  audit_days: number | null;
  connection_limit: number | null;
  user_limit: number | null;
  member_count: number | null;
  allowed_input_scanners: string[] | null;
  allowed_output_scanners: string[] | null;
}

interface PaymentMethod {
  id: number;
  cardholder_name: string;
  card_brand: string;
  card_last4: string;
  card_exp_month: number;
  card_exp_year: number;
  is_default: boolean;
  created_at: string;
}

interface Invoice {
  id: number;
  invoice_number: string;
  amount: number;
  currency: string;
  status: string;
  description: string | null;
  period_start: string;
  period_end: string;
  paid_at: string | null;
  created_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const PLAN_META: Record<string, { label: string; color: string; bg: string }> = {
  free:       { label: "Free",       color: "#94a3b8", bg: "rgba(148,163,184,0.1)" },
  pro:        { label: "Pro",        color: "#14B8A6", bg: "rgba(20,184,166,0.1)"  },
  enterprise: { label: "Enterprise", color: "#a78bfa", bg: "rgba(167,139,250,0.1)" },
};

const INVOICE_STATUS: Record<string, { label: string; color: string; bg: string }> = {
  open:   { label: "Open",   color: "#fbbf24", bg: "rgba(251,191,36,0.1)"  },
  paid:   { label: "Paid",   color: "#14B8A6", bg: "rgba(20,184,166,0.1)"  },
  failed: { label: "Failed", color: "#f87171", bg: "rgba(248,113,113,0.1)" },
  void:   { label: "Void",   color: "#64748b", bg: "rgba(100,116,139,0.1)" },
};

const BRAND_ICONS: Record<string, string> = {
  visa:       "VISA",
  mastercard: "MC",
  amex:       "AMEX",
  discover:   "DISC",
  card:       "CARD",
};

const BRAND_COLORS: Record<string, { color: string; bg: string }> = {
  visa:       { color: "#60a5fa", bg: "rgba(96,165,250,0.1)"   },
  mastercard: { color: "#f87171", bg: "rgba(248,113,113,0.1)"  },
  amex:       { color: "#34d399", bg: "rgba(52,211,153,0.1)"   },
  discover:   { color: "#fbbf24", bg: "rgba(251,191,36,0.1)"   },
  card:       { color: "#94a3b8", bg: "rgba(148,163,184,0.1)"  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function detectBrand(number: string): string {
  const n = number.replace(/\s/g, "");
  if (/^4/.test(n)) return "visa";
  if (/^5[1-5]/.test(n)) return "mastercard";
  if (/^3[47]/.test(n)) return "amex";
  if (/^6/.test(n)) return "discover";
  return "card";
}

function formatCardNumber(value: string): string {
  const digits = value.replace(/\D/g, "").slice(0, 16);
  return digits.replace(/(.{4})/g, "$1 ").trim();
}

function formatExpiry(value: string): string {
  const digits = value.replace(/\D/g, "").slice(0, 4);
  if (digits.length >= 3) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return digits;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function UsageBar({ pct, limit }: { pct: number; limit: number | null }) {
  const capped = Math.min(pct, 100);
  const color = capped >= 100 ? "#f87171" : capped >= 80 ? "#fbbf24" : "#14B8A6";
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-slate-500">{Math.round(capped)}% used</span>
        {limit === null && <span className="text-xs text-slate-600">Unlimited</span>}
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${capped}%`, background: color }} />
      </div>
    </div>
  );
}

function CardBadge({ brand }: { brand: string }) {
  const style = BRAND_COLORS[brand] ?? BRAND_COLORS.card;
  return (
    <span className="text-xs font-mono font-bold px-1.5 py-0.5 rounded"
      style={{ background: style.bg, color: style.color }}>
      {BRAND_ICONS[brand] ?? "CARD"}
    </span>
  );
}

// ── Add Payment Method Form ───────────────────────────────────────────────────

function AddCardForm({ onSaved, onCancel }: { onSaved: () => void; onCancel: () => void }) {
  const [cardNumber, setCardNumber] = useState("");
  const [expiry, setExpiry] = useState("");
  const [cvv, setCvv] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const brand = detectBrand(cardNumber);
  const digits = cardNumber.replace(/\s/g, "");
  const last4 = digits.slice(-4);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (digits.length < 13 || digits.length > 16) { setError("Enter a valid card number."); return; }
    const [mm, yy] = expiry.split("/");
    const month = parseInt(mm, 10);
    const year = 2000 + parseInt(yy ?? "0", 10);
    if (!month || !year || month < 1 || month > 12) { setError("Enter a valid expiry (MM/YY)."); return; }
    if (!name.trim()) { setError("Enter the cardholder name."); return; }

    setSaving(true);
    try {
      await api.post("/billing/payment-methods", {
        cardholder_name: name.trim(),
        card_brand: brand,
        card_last4: last4,
        card_exp_month: month,
        card_exp_year: year,
      });
      onSaved();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to add card.";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  const inputStyle = {
    background: "#0A0F1F",
    border: "1px solid rgba(255,255,255,0.08)",
    color: "#e2e8f0",
    borderRadius: "6px",
    padding: "8px 12px",
    fontSize: "13px",
    width: "100%",
    outline: "none",
  };

  return (
    <form onSubmit={handleSubmit} className="mt-4 rounded border border-white/5 p-5 space-y-4"
      style={{ background: "#080d1a" }}>
      <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">New payment method</p>

      <div className="space-y-1">
        <label className="text-xs text-slate-500">Cardholder name</label>
        <input style={inputStyle} placeholder="Jane Smith"
          value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-slate-500">Card number</label>
        <div className="relative">
          <input style={{ ...inputStyle, paddingRight: "56px" }}
            placeholder="1234 5678 9012 3456"
            value={cardNumber}
            onChange={(e) => setCardNumber(formatCardNumber(e.target.value))}
            maxLength={19}
            inputMode="numeric" />
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <CardBadge brand={brand} />
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <div className="flex-1 space-y-1">
          <label className="text-xs text-slate-500">Expiry</label>
          <input style={inputStyle} placeholder="MM/YY"
            value={expiry}
            onChange={(e) => setExpiry(formatExpiry(e.target.value))}
            maxLength={5}
            inputMode="numeric" />
        </div>
        <div className="flex-1 space-y-1">
          <label className="text-xs text-slate-500">CVV</label>
          <input style={inputStyle} placeholder="•••"
            value={cvv}
            onChange={(e) => setCvv(e.target.value.replace(/\D/g, "").slice(0, 4))}
            maxLength={4}
            inputMode="numeric"
            type="password" />
        </div>
      </div>

      <p className="text-xs text-slate-600 flex items-center gap-1.5">
        <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
        </svg>
        Your payment info is encrypted and stored securely. CVV is never saved.
      </p>

      {error && (
        <p className="text-xs px-3 py-2 rounded"
          style={{ background: "rgba(248,113,113,0.07)", color: "#f87171", border: "1px solid rgba(248,113,113,0.2)" }}>
          {error}
        </p>
      )}

      <div className="flex gap-2 pt-1">
        <button type="submit" disabled={saving}
          className="text-xs font-medium px-4 py-2 rounded transition-opacity disabled:opacity-50"
          style={{ background: "#14B8A6", color: "#0A0F1F" }}>
          {saving ? "Saving…" : "Add card"}
        </button>
        <button type="button" onClick={onCancel}
          className="text-xs px-4 py-2 rounded border text-slate-400 hover:text-white transition-colors"
          style={{ borderColor: "rgba(255,255,255,0.08)" }}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Payment Methods Section ───────────────────────────────────────────────────

function PaymentMethodsSection() {
  const { data: methods, mutate } = useSWR<PaymentMethod[]>(
    "/billing/payment-methods",
    () => api.get<PaymentMethod[]>("/billing/payment-methods"),
    { revalidateOnFocus: false },
  );
  const [showForm, setShowForm] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [settingDefaultId, setSettingDefaultId] = useState<number | null>(null);

  async function handleDelete(id: number) {
    setDeletingId(id);
    try { await api.delete(`/billing/payment-methods/${id}`); await mutate(); }
    finally { setDeletingId(null); }
  }

  async function handleSetDefault(id: number) {
    setSettingDefaultId(id);
    try { await api.patch(`/billing/payment-methods/${id}/default`, {}); await mutate(); }
    finally { setSettingDefaultId(null); }
  }

  return (
    <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
      <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
        <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">Payment methods</p>
        {!showForm && (
          <button onClick={() => setShowForm(true)}
            className="text-xs font-medium px-3 py-1.5 rounded transition-colors"
            style={{ background: "rgba(20,184,166,0.1)", color: "#14B8A6", border: "1px solid rgba(20,184,166,0.2)" }}>
            + Add card
          </button>
        )}
      </div>

      <div className="px-6 py-4">
        {methods === undefined ? (
          <div className="space-y-3">
            {[1, 2].map((i) => (
              <div key={i} className="h-14 rounded animate-pulse" style={{ background: "#0A0F1F" }} />
            ))}
          </div>
        ) : methods.length === 0 && !showForm ? (
          <div className="py-6 text-center">
            <p className="text-xs text-slate-600 font-mono mb-3">No payment methods on file.</p>
            <button onClick={() => setShowForm(true)}
              className="text-xs font-medium px-4 py-2 rounded transition-opacity hover:opacity-80"
              style={{ background: "#14B8A6", color: "#0A0F1F" }}>
              Add your first card
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {methods.map((m) => (
              <div key={m.id} className="flex items-center justify-between rounded px-4 py-3 gap-4"
                style={{ background: "#0A0F1F", border: m.is_default ? "1px solid rgba(20,184,166,0.2)" : "1px solid rgba(255,255,255,0.04)" }}>
                <div className="flex items-center gap-3 min-w-0">
                  <CardBadge brand={m.card_brand} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-white font-mono">•••• {m.card_last4}</span>
                      {m.is_default && (
                        <span className="text-xs font-mono px-1.5 py-0.5 rounded"
                          style={{ background: "rgba(20,184,166,0.1)", color: "#14B8A6" }}>
                          default
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-600 truncate">
                      {m.cardholder_name} · expires {String(m.card_exp_month).padStart(2, "0")}/{m.card_exp_year}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {!m.is_default && (
                    <button onClick={() => handleSetDefault(m.id)}
                      disabled={settingDefaultId === m.id}
                      className="text-xs text-slate-600 hover:text-slate-300 transition-colors disabled:opacity-40">
                      {settingDefaultId === m.id ? "…" : "Set default"}
                    </button>
                  )}
                  <button onClick={() => handleDelete(m.id)}
                    disabled={deletingId === m.id}
                    className="text-xs transition-colors disabled:opacity-40"
                    style={{ color: "#f87171" }}>
                    {deletingId === m.id ? "…" : "Remove"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {showForm && (
          <AddCardForm
            onSaved={async () => { await mutate(); setShowForm(false); }}
            onCancel={() => setShowForm(false)}
          />
        )}
      </div>
    </div>
  );
}

// ── Invoice PDF printer ───────────────────────────────────────────────────────

function printInvoice(inv: Invoice, plan: string) {
  const statusMeta = INVOICE_STATUS[inv.status] ?? INVOICE_STATUS.open;
  const periodStr = `${format(new Date(inv.period_start), "MMM d, yyyy")} – ${format(new Date(inv.period_end), "MMM d, yyyy")}`;
  const issuedStr  = format(new Date(inv.created_at), "MMMM d, yyyy");
  const paidStr    = inv.paid_at ? format(new Date(inv.paid_at), "MMMM d, yyyy") : "—";

  const statusColor =
    inv.status === "paid"   ? "#10b981" :
    inv.status === "open"   ? "#f59e0b" :
    inv.status === "failed" ? "#ef4444" : "#64748b";

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Invoice ${inv.invoice_number}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { font-size: 14px; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f8fafc;
      color: #1e293b;
      padding: 48px 0;
      min-height: 100vh;
    }
    .page {
      background: #ffffff;
      width: 720px;
      margin: 0 auto;
      border-radius: 12px;
      box-shadow: 0 4px 32px rgba(0,0,0,0.10);
      overflow: hidden;
    }

    /* Header band */
    .header {
      background: #0d1426;
      padding: 36px 48px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }
    .logo {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .logo-mark {
      width: 22px; height: 22px;
      background: #14B8A6;
      border-radius: 4px;
    }
    .logo-name {
      font-size: 16px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: -0.3px;
    }
    .logo-tagline {
      font-size: 11px;
      color: #475569;
      margin-top: 2px;
    }
    .header-right { text-align: right; }
    .invoice-label {
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: #475569;
      margin-bottom: 6px;
    }
    .invoice-number {
      font-size: 22px;
      font-weight: 700;
      color: #ffffff;
      font-family: "SF Mono", "Fira Code", monospace;
      letter-spacing: -0.5px;
    }

    /* Status pill */
    .status-badge {
      display: inline-block;
      margin-top: 10px;
      padding: 4px 12px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      color: ${statusColor};
      background: ${statusColor}18;
      border: 1px solid ${statusColor}44;
    }

    /* Body padding */
    .body { padding: 40px 48px; }

    /* From / To */
    .parties {
      display: flex;
      justify-content: space-between;
      gap: 32px;
      margin-bottom: 36px;
    }
    .party { flex: 1; }
    .party-label {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 10px;
    }
    .party-name {
      font-size: 15px;
      font-weight: 700;
      color: #0f172a;
      margin-bottom: 4px;
    }
    .party-detail {
      font-size: 12px;
      color: #64748b;
      line-height: 1.7;
    }

    /* Meta grid */
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1px;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 36px;
    }
    .meta-cell {
      background: #ffffff;
      padding: 16px 20px;
    }
    .meta-key {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 5px;
    }
    .meta-value {
      font-size: 13px;
      font-weight: 600;
      color: #1e293b;
    }

    /* Line items */
    .items-header {
      display: flex;
      padding: 10px 16px;
      background: #f8fafc;
      border-radius: 6px 6px 0 0;
      border: 1px solid #e2e8f0;
      border-bottom: none;
    }
    .items-header span {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #94a3b8;
    }
    .col-desc  { flex: 1; }
    .col-period { width: 200px; }
    .col-amount { width: 100px; text-align: right; }

    .items-body {
      border: 1px solid #e2e8f0;
      border-radius: 0 0 6px 6px;
      overflow: hidden;
    }
    .item-row {
      display: flex;
      align-items: center;
      padding: 16px 16px;
      border-bottom: 1px solid #f1f5f9;
    }
    .item-row:last-child { border-bottom: none; }
    .item-name {
      font-size: 13px;
      font-weight: 600;
      color: #1e293b;
      margin-bottom: 3px;
    }
    .item-sub {
      font-size: 11px;
      color: #94a3b8;
    }
    .item-period {
      font-size: 12px;
      color: #64748b;
      font-family: "SF Mono", "Fira Code", monospace;
    }
    .item-amount {
      font-size: 14px;
      font-weight: 700;
      color: #1e293b;
      text-align: right;
      font-family: "SF Mono", "Fira Code", monospace;
    }

    /* Totals */
    .totals {
      margin-top: 0;
      display: flex;
      justify-content: flex-end;
    }
    .totals-box {
      width: 260px;
      border: 1px solid #e2e8f0;
      border-top: none;
      border-radius: 0 0 6px 6px;
      overflow: hidden;
    }
    .total-row {
      display: flex;
      justify-content: space-between;
      padding: 11px 16px;
      border-bottom: 1px solid #f1f5f9;
      font-size: 12px;
    }
    .total-row:last-child { border-bottom: none; }
    .total-row.grand {
      background: #0d1426;
      padding: 14px 16px;
    }
    .total-row .label { color: #64748b; }
    .total-row .value { font-weight: 600; color: #1e293b; font-family: monospace; }
    .total-row.grand .label { color: #94a3b8; font-size: 11px; letter-spacing: 0.5px; text-transform: uppercase; }
    .total-row.grand .value { color: #14B8A6; font-size: 16px; }

    /* Footer */
    .footer {
      margin-top: 40px;
      padding-top: 24px;
      border-top: 1px solid #f1f5f9;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
    }
    .footer-note { font-size: 11px; color: #94a3b8; line-height: 1.6; max-width: 340px; }
    .footer-brand { font-size: 11px; color: #cbd5e1; text-align: right; }
    .footer-brand strong { display: block; color: #64748b; font-size: 12px; }

    /* Print overrides */
    @media print {
      body { background: #fff; padding: 0; }
      .page { box-shadow: none; border-radius: 0; width: 100%; }
      .print-btn { display: none; }
    }
  </style>
</head>
<body>
  <div class="page">
    <!-- Header -->
    <div class="header">
      <div>
        <div class="logo">
          <div class="logo-mark"></div>
          <div>
            <div class="logo-name">Talix Shield</div>
            <div class="logo-tagline">AI Guardrails Platform</div>
          </div>
        </div>
      </div>
      <div class="header-right">
        <div class="invoice-label">Invoice</div>
        <div class="invoice-number">${inv.invoice_number}</div>
        <div class="status-badge">${statusMeta.label}</div>
      </div>
    </div>

    <!-- Body -->
    <div class="body">

      <!-- From / To -->
      <div class="parties">
        <div class="party">
          <div class="party-label">From</div>
          <div class="party-name">Talix Shield, Inc.</div>
          <div class="party-detail">
            billing@talixshield.com<br/>
            support@talixshield.com
          </div>
        </div>
        <div class="party">
          <div class="party-label">Bill To</div>
          <div class="party-name">Your Account</div>
          <div class="party-detail">
            ${plan.charAt(0).toUpperCase() + plan.slice(1)} Plan subscriber
          </div>
        </div>
      </div>

      <!-- Meta -->
      <div class="meta-grid">
        <div class="meta-cell">
          <div class="meta-key">Issue date</div>
          <div class="meta-value">${issuedStr}</div>
        </div>
        <div class="meta-cell">
          <div class="meta-key">Billing period</div>
          <div class="meta-value" style="font-size:11px">${periodStr}</div>
        </div>
        <div class="meta-cell">
          <div class="meta-key">${inv.status === "paid" ? "Paid on" : "Status"}</div>
          <div class="meta-value" style="color:${statusColor}">${inv.status === "paid" ? paidStr : statusMeta.label}</div>
        </div>
      </div>

      <!-- Line items -->
      <div class="items-header">
        <span class="col-desc">Description</span>
        <span class="col-period">Period</span>
        <span class="col-amount">Amount</span>
      </div>
      <div class="items-body">
        <div class="item-row">
          <div class="col-desc">
            <div class="item-name">${inv.description ?? (plan.charAt(0).toUpperCase() + plan.slice(1) + " Plan")}</div>
            <div class="item-sub">Talix Shield ${plan.charAt(0).toUpperCase() + plan.slice(1)} subscription</div>
          </div>
          <div class="col-period">
            <div class="item-period">${periodStr}</div>
          </div>
          <div class="col-amount">
            <div class="item-amount">$${inv.amount.toFixed(2)}</div>
          </div>
        </div>
      </div>

      <!-- Totals aligned right under items -->
      <div class="totals">
        <div class="totals-box">
          <div class="total-row">
            <span class="label">Subtotal</span>
            <span class="value">$${inv.amount.toFixed(2)}</span>
          </div>
          <div class="total-row">
            <span class="label">Tax (0%)</span>
            <span class="value">$0.00</span>
          </div>
          <div class="total-row grand">
            <span class="label">Total due</span>
            <span class="value">$${inv.amount.toFixed(2)}</span>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="footer">
        <div class="footer-note">
          Thank you for using Talix Shield. Questions about this invoice?<br/>
          Contact us at <strong style="color:#475569">billing@talixshield.com</strong>
        </div>
        <div class="footer-brand">
          <strong>Talix Shield</strong>
          AI Guardrails Platform<br/>
          talixshield.com
        </div>
      </div>

    </div>
  </div>

  <script>
    window.onload = function() { window.print(); }
  </script>
</body>
</html>`;

  const win = window.open("", "_blank");
  if (win) {
    win.document.write(html);
    win.document.close();
  }
}

// ── Invoices Section ──────────────────────────────────────────────────────────

function InvoicesSection({ plan }: { plan: string }) {
  const { data: invoices } = useSWR<Invoice[]>(
    "/billing/invoices",
    () => api.get<Invoice[]>("/billing/invoices"),
    { revalidateOnFocus: false },
  );

  return (
    <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
      <div className="px-6 py-4 border-b border-white/5">
        <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">Invoice history</p>
      </div>

      {invoices === undefined ? (
        <div className="p-6 space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-10 rounded animate-pulse" style={{ background: "#0A0F1F" }} />
          ))}
        </div>
      ) : invoices.length === 0 ? (
        <div className="px-6 py-10 text-center">
          <p className="text-xs text-slate-600 font-mono">No invoices yet.</p>
          <p className="text-xs text-slate-700 mt-1">Invoices will appear here once your subscription is active.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5">
                {["Invoice", "Date", "Period", "Amount", "Status", ""].map((h) => (
                  <th key={h} className="px-5 py-3 text-left text-xs text-slate-600 font-mono uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => {
                const status = INVOICE_STATUS[inv.status] ?? INVOICE_STATUS.open;
                return (
                  <tr key={inv.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.01] transition-colors">
                    <td className="px-5 py-3">
                      <div>
                        <p className="text-xs font-mono text-white">{inv.invoice_number}</p>
                        {inv.description && (
                          <p className="text-xs text-slate-600">{inv.description}</p>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
                      {format(new Date(inv.created_at), "MMM d, yyyy")}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-600 font-mono whitespace-nowrap">
                      {format(new Date(inv.period_start), "MMM d")} – {format(new Date(inv.period_end), "MMM d, yyyy")}
                    </td>
                    <td className="px-5 py-3 text-xs font-mono text-white whitespace-nowrap">
                      {inv.currency} ${inv.amount.toFixed(2)}
                    </td>
                    <td className="px-5 py-3">
                      <span className="text-xs font-mono px-2 py-0.5 rounded capitalize"
                        style={{ background: status.bg, color: status.color }}>
                        {status.label}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right">
                      <button
                        onClick={() => printInvoice(inv, plan)}
                        className="text-xs font-medium px-2.5 py-1 rounded transition-colors"
                        style={{ background: "rgba(20,184,166,0.08)", color: "#14B8A6", border: "1px solid rgba(20,184,166,0.15)" }}
                      >
                        ↓ PDF
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function BillingPage() {
  const { data: plan, isLoading } = useSWR<PlanInfo>(
    "/auth/plan",
    () => api.get<PlanInfo>("/auth/plan"),
    { revalidateOnFocus: false },
  );

  const meta = PLAN_META[plan?.plan ?? "free"] ?? PLAN_META.free;
  const isFree = !plan || plan.plan === "free";
  const isPro = plan?.plan === "pro";

  return (
    <div className="max-w-5xl space-y-6">

      {/* Current plan card */}
      <div className="rounded border border-white/5 p-6 relative overflow-hidden" style={{ background: "#0d1426" }}>
        <div className="absolute top-0 left-0 right-0 h-px"
          style={{ background: "linear-gradient(90deg, #14B8A6 0%, transparent 60%)" }} />

        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <p className="text-xs text-slate-500 uppercase tracking-widest font-mono mb-2">Current plan</p>
            {isLoading ? (
              <div className="h-7 w-24 rounded animate-pulse" style={{ background: "#0A0F1F" }} />
            ) : (
              <>
                <div className="flex items-center gap-3 mb-1">
                  <h2 className="text-2xl font-bold text-white tracking-tight">{meta.label}</h2>
                  <span className="text-xs font-mono px-2 py-0.5 rounded"
                    style={{ background: meta.bg, color: meta.color }}>
                    {plan?.plan ?? "free"}
                  </span>
                </div>
                {plan?.is_org_plan && (
                  <p className="text-xs text-slate-600 font-mono">
                    Plan managed at the organization level
                  </p>
                )}
              </>
            )}
          </div>
          {isFree && (
            <Link href="/pricing"
              className="shrink-0 text-xs font-medium px-4 py-2 rounded transition-opacity hover:opacity-90"
              style={{ background: "#14B8A6", color: "#0A0F1F" }}>
              Upgrade plan
            </Link>
          )}
          {isPro && (
            <a href="mailto:sales@talixshield.com"
              className="shrink-0 text-xs font-medium px-4 py-2 rounded border text-slate-400 hover:text-white hover:border-white/20 transition-colors"
              style={{ borderColor: "rgba(255,255,255,0.1)" }}>
              Talk to sales →
            </a>
          )}
        </div>

        {/* Scan usage */}
        {isLoading ? (
          <div className="h-12 rounded animate-pulse" style={{ background: "#0A0F1F" }} />
        ) : plan ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white font-medium">Monthly scans</span>
              <span className="text-sm font-mono" style={{ color: meta.color }}>
                {plan.scans_used.toLocaleString()}
                {plan.scan_limit !== null && (
                  <span className="text-slate-600"> / {plan.scan_limit.toLocaleString()}</span>
                )}
              </span>
            </div>
            <UsageBar pct={plan.scan_pct} limit={plan.scan_limit} />
            {plan.scan_pct >= 80 && plan.scan_limit !== null && (
              <div className="rounded px-3 py-2 text-xs flex items-center gap-2"
                style={{
                  background: plan.scan_pct >= 100 ? "rgba(248,113,113,0.07)" : "rgba(251,191,36,0.07)",
                  border: `1px solid ${plan.scan_pct >= 100 ? "rgba(248,113,113,0.2)" : "rgba(251,191,36,0.2)"}`,
                  color: plan.scan_pct >= 100 ? "#f87171" : "#fbbf24",
                }}>
                <span>{plan.scan_pct >= 100 ? "✗" : "▲"}</span>
                {plan.scan_pct >= 100
                  ? "Scan limit reached. Scans are blocked until the month resets or you upgrade."
                  : `Approaching limit — ${plan.scans_remaining?.toLocaleString()} scans remaining this month.`}
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* Entitlements table */}
      <div className="rounded border border-white/5 overflow-hidden" style={{ background: "#0d1426" }}>
        <div className="px-6 py-4 border-b border-white/5">
          <p className="text-xs text-slate-500 uppercase tracking-widest font-mono">Plan entitlements</p>
        </div>
        {isLoading ? (
          <div className="p-6 space-y-3">{Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-8 rounded animate-pulse" style={{ background: "#0A0F1F" }} />
          ))}</div>
        ) : plan ? (
          <div className="divide-y divide-white/5">
            {[
              { label: "Monthly scan limit", value: plan.scan_limit !== null ? `${plan.scan_limit.toLocaleString()} scans` : "Unlimited" },
              { label: "Audit log retention", value: plan.audit_days !== null ? `${plan.audit_days} days` : "Unlimited" },
              { label: "API connections",     value: plan.connection_limit !== null ? `${plan.connection_limit} connection${plan.connection_limit !== 1 ? "s" : ""}` : "Unlimited" },
              {
                label: "Org members",
                value: plan.user_limit !== null
                  ? `${plan.member_count ?? 1} / ${plan.user_limit} users`
                  : "Unlimited users",
              },
              { label: "Input scanners",      value: plan.allowed_input_scanners !== null ? plan.allowed_input_scanners.join(", ") : "All scanners" },
              { label: "Output scanners",     value: plan.allowed_output_scanners !== null ? plan.allowed_output_scanners.join(", ") : "All scanners" },
            ].map(({ label, value }) => (
              <div key={label} className="flex items-start justify-between px-6 py-3 gap-4">
                <span className="text-xs text-slate-500 shrink-0">{label}</span>
                <span className="text-xs text-right font-mono" style={{ color: "#e2e8f0" }}>{value}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {/* Payment methods */}
      <PaymentMethodsSection />

      {/* Invoice history */}
      <InvoicesSection plan={plan?.plan ?? "free"} />

      {/* Upgrade / downgrade info */}
      <div className="rounded border border-white/5 p-6" style={{ background: "#0d1426" }}>
        <p className="text-xs text-slate-500 uppercase tracking-widest font-mono mb-4">Change plan</p>
        <div className="space-y-4">
          {isFree && (
            <div>
              <p className="text-sm font-medium text-white mb-1">Upgrade to Pro</p>
              <p className="text-xs text-slate-500 leading-relaxed mb-3">
                Get 100,000 scans/month, all 40+ scanners, 90-day audit retention, and unlimited API connections for $49/month.
              </p>
              <Link href="/pricing" className="text-xs font-medium transition-colors hover:opacity-80"
                style={{ color: "#14B8A6" }}>
                View pricing →
              </Link>
            </div>
          )}
          {isPro && (
            <div>
              <p className="text-sm font-medium text-white mb-1">Upgrade to Enterprise</p>
              <p className="text-xs text-slate-500 leading-relaxed mb-3">
                Unlimited scans, on-premise deployment, SSO/SAML, custom scanner development, and a dedicated support engineer.
              </p>
              <a href="mailto:sales@talixshield.com" className="text-xs font-medium transition-colors hover:opacity-80"
                style={{ color: "#14B8A6" }}>
                Contact sales →
              </a>
            </div>
          )}
          <div className="border-t border-white/5 pt-4">
            <p className="text-xs text-slate-600 leading-relaxed">
              Need to downgrade or cancel? Email{" "}
              <a href="mailto:support@talixshield.com" className="text-slate-400 hover:text-white transition-colors">
                support@talixshield.com
              </a>
              {" "}and we&apos;ll handle it within one business day. Downgrades take effect at the end of your current billing cycle.
            </p>
          </div>
        </div>
      </div>

    </div>
  );
}
