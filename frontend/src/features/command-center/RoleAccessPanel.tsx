"use client";

import type { RoleAccessContracts } from "./useCommandCenter";

function fmt(value: unknown) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value).replaceAll("_", " ");
}

function RoleList({ title, items, tone = "slate" }: { title: string; items?: string[]; tone?: "slate" | "emerald" | "amber" }) {
  const color = tone === "emerald" ? "text-emerald-100" : tone === "amber" ? "text-amber-100" : "text-slate-300";
  return (
    <div>
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{title}</div>
      <div className={`mt-2 flex flex-wrap gap-1.5 text-[11px] font-bold ${color}`}>
        {items?.length ? (
          items.slice(0, 6).map((item) => (
            <span key={item} className="rounded border border-slate-700 bg-slate-950 px-2 py-1">
              {fmt(item)}
            </span>
          ))
        ) : (
          <span className="text-slate-500">--</span>
        )}
      </div>
    </div>
  );
}

export function RoleAccessPanel({
  contracts,
  isLoading,
  onRefresh,
}: {
  contracts: RoleAccessContracts | null;
  isLoading: boolean;
  onRefresh: () => void;
}) {
  const roles = contracts?.roles ?? [];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">OOD access layers</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Role authority contracts</h2>
          <div className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
            {contracts?.principle ?? "Rigid authority boundaries with role-specific surfaces."}
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="min-h-10 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? "Reading" : "Refresh"}
        </button>
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-4">
        {!roles.length && <div className="rounded border border-slate-800 bg-slate-900 p-3 text-sm text-slate-500">No role contract is available.</div>}
        {roles.map((role) => (
          <article key={role.id ?? role.label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="flex min-h-14 flex-col justify-between gap-1">
              <div className="text-sm font-black text-slate-100">{fmt(role.label)}</div>
              <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-200">{fmt(role.surface)}</div>
            </div>
            <div className="mt-3 grid gap-3">
              <RoleList title="Can read" items={role.can_read} tone="emerald" />
              <RoleList title="Can do" items={role.can_do} />
              <RoleList title="Blocked" items={role.cannot_do} tone="amber" />
            </div>
            <div className="mt-3 border-t border-slate-800 pt-3 text-xs leading-relaxed text-slate-400">{fmt(role.llm_contract)}</div>
          </article>
        ))}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Global boundaries</div>
          <div className="mt-2 grid gap-1 text-xs leading-relaxed text-slate-300">
            {(contracts?.global_boundaries ?? []).map((boundary) => (
              <div key={boundary}>{boundary}</div>
            ))}
          </div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Runtime flags</div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-xs font-black text-slate-100">
            <div className="rounded border border-slate-800 bg-slate-950 px-2 py-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Seed data</div>
              <div>{fmt(contracts?.uses_seed_data)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 px-2 py-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">BQ per tick</div>
              <div>{fmt(contracts?.loads_bigquery_per_tick)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 px-2 py-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">LLM control</div>
              <div>{fmt(contracts?.llm_control_authority)}</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
