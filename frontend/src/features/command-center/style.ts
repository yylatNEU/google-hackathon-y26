export function toneClass(tone?: "risk" | "watch" | "ok" | string) {
  if (tone === "risk" || tone === "critical" || tone === "HIGH") return "border-rose-500/40 bg-rose-950/25 text-rose-100";
  if (tone === "watch" || tone === "warning" || tone === "MEDIUM") return "border-amber-500/40 bg-amber-950/20 text-amber-100";
  return "border-emerald-500/40 bg-emerald-950/20 text-emerald-100";
}

export function gateClass(gate?: string) {
  const normalized = String(gate ?? "").toLowerCase();
  if (normalized.includes("block")) return "border-rose-400 bg-rose-500 text-slate-950";
  if (normalized.includes("review") || normalized.includes("pending")) return "border-amber-300 bg-amber-300 text-slate-950";
  return "border-emerald-300 bg-emerald-300 text-slate-950";
}

export function compactNumber(value: number | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en", { notation: value >= 10000 ? "compact" : "standard" }).format(Math.round(value));
}

export function percent(value: number | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return `${Math.round(value)}%`;
}

export function humanize(value?: string) {
  return value ? value.replaceAll("_", " ") : "--";
}

