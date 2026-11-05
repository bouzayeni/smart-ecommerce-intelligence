const brlFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const brlCents = new Intl.NumberFormat("en-US", { style: "currency", currency: "BRL", maximumFractionDigits: 2 });
const intFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export const brl = (v: unknown, cents = false) => (isNum(v) ? (cents ? brlCents : brlFmt).format(v) : "—");
export const num = (v: unknown, digits = 0) =>
  isNum(v) ? (digits ? v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits }) : intFmt.format(v)) : "—";
export const pct = (v: unknown, digits = 1) => (isNum(v) ? `${(v * 100).toFixed(digits)}%` : "—");
export const signedPct = (v: unknown, digits = 1) => (isNum(v) ? `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%` : "—");

/** Compact axis labels: 1.2M, 450k. */
export const compact = (v: unknown) =>
  isNum(v) ? new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v) : "";

export const day = (v: unknown) => (typeof v === "string" ? v.slice(0, 10) : "—");
export const shortId = (id: string) => `${id.slice(0, 8)}…`;

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
