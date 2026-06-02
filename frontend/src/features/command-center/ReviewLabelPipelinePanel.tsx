"use client";

import { useMemo, useState } from "react";
import type { ReviewLabelCandidate, ReviewLabelDecision, ReviewLabelPipeline } from "./useCommandCenter";
import { humanize, toneClass } from "./style";

function fmt(value: unknown): string {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map((entry) => fmt(entry)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value).replaceAll("_", " ");
}

function priorityTone(priority?: string) {
  const value = String(priority ?? "").toLowerCase();
  if (value === "critical" || value === "high") return "risk";
  if (value === "medium" || value === "watch") return "watch";
  return "ok";
}

function evidencePreview(candidate: ReviewLabelCandidate) {
  const evidence = candidate.evidence ?? {};
  return Object.entries(evidence)
    .slice(0, 4)
    .map(([key, value]) => `${humanize(key)}: ${fmt(value)}`)
    .join(" / ");
}

export function ReviewLabelPipelinePanel({
  pipeline,
  isLoading,
  onRefresh,
  onAutoLabel,
  onDecision,
}: {
  pipeline: ReviewLabelPipeline | null;
  isLoading: boolean;
  onRefresh: () => void;
  onAutoLabel: () => void;
  onDecision: (candidate: ReviewLabelCandidate, decision: ReviewLabelDecision, finalLabel?: string) => void;
}) {
  const [labelOverrides, setLabelOverrides] = useState<Record<string, string>>({});
  const candidates = pipeline?.candidates ?? [];
  const decided = pipeline?.decided ?? [];
  const summary = pipeline?.summary;
  const readiness = pipeline?.readiness_issues ?? [];
  const grouped = useMemo(() => {
    return candidates.reduce<Record<string, ReviewLabelCandidate[]>>((acc, candidate) => {
      const key = candidate.agent_id ?? "unknown_agent";
      acc[key] = [...(acc[key] ?? []), candidate];
      return acc;
    }, {});
  }, [candidates]);

  const selectedLabel = (candidate: ReviewLabelCandidate) => {
    const id = candidate.id ?? "";
    return labelOverrides[id] ?? candidate.proposed_label ?? candidate.label_options?.[0] ?? "";
  };

  const approveDecision = (candidate: ReviewLabelCandidate) => {
    const finalLabel = selectedLabel(candidate);
    const decision: ReviewLabelDecision = finalLabel && finalLabel !== candidate.proposed_label ? "edit_label" : "approve_label";
    onDecision(candidate, decision, finalLabel);
  };

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Review labels</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Ops review label queue</h2>
          <div className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
            Candidate labels are built from live-feed review cases, weak feed health, and scan-agent training readiness. Approved rows become supervised evidence only; reward remains measured outcome data.
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onAutoLabel}
            disabled={isLoading}
            className="w-fit rounded border border-lime-300 bg-lime-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-lime-200 disabled:opacity-50"
          >
            Auto-label high confidence
          </button>
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="w-fit rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-lime-300 hover:text-lime-100 disabled:opacity-50"
          >
            {isLoading ? "Refreshing" : "Refresh labels"}
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-5">
        {[
          ["Status", pipeline?.status],
          ["Open", summary?.open_count ?? 0],
          ["Candidates", summary?.candidate_count ?? 0],
          ["Approved", summary?.approved_label_count ?? 0],
          ["Auto threshold", pipeline?.auto_label_rule?.confidence_threshold ?? 0.7],
          ["Reward eligible", pipeline?.labels_or_reward_changed ? "changed" : "no"],
        ].map(([label, value]) => (
          <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
            <div className="mt-1 truncate text-sm font-black text-lime-100">{fmt(value)}</div>
          </div>
        ))}
      </div>

      {pipeline?.training_rule && (
        <div className="mt-3 rounded border border-lime-500/30 bg-lime-950/10 p-3 text-xs font-bold leading-relaxed text-lime-100">{pipeline.training_rule}</div>
      )}

      {readiness.length ? <div className="mt-3 rounded border border-amber-500/30 bg-amber-950/20 p-3 text-xs font-bold text-amber-100">{readiness.slice(0, 3).join(" / ")}</div> : null}

      <div className="mt-4 space-y-4">
        {Object.entries(grouped).map(([agentId, rows]) => (
          <div key={agentId} className="overflow-hidden rounded border border-slate-800">
            <div className="flex items-center justify-between gap-3 bg-slate-900 px-3 py-2">
              <div className="text-xs font-black uppercase tracking-widest text-slate-300">{humanize(agentId)}</div>
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{rows.length} open</div>
            </div>
            <div className="divide-y divide-slate-800">
              {rows.map((candidate) => {
                const label = selectedLabel(candidate);
                return (
                  <div key={candidate.id} className="grid gap-3 bg-slate-950 p-3 text-xs leading-relaxed xl:grid-cols-[1fr_0.75fr_0.85fr]">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(priorityTone(candidate.priority))}`}>{fmt(candidate.priority)}</span>
                        <span className="font-black text-slate-100">{humanize(candidate.source)}</span>
                        <span className="text-slate-500">{humanize(candidate.training_scope)}</span>
                      </div>
                      <div className="mt-2 font-bold text-slate-200">{candidate.input_summary ?? "--"}</div>
                      <div className="mt-2 line-clamp-2 text-slate-500">{evidencePreview(candidate) || candidate.boundary || "--"}</div>
                      <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-lime-100">
                        Recommendation {fmt(candidate.recommendation?.confidence)} / {humanize(candidate.recommendation?.confidence_status)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Final label</div>
                      <select
                        value={label}
                        onChange={(event) => setLabelOverrides((current) => ({ ...current, [candidate.id ?? ""]: event.target.value }))}
                        className="mt-2 w-full rounded border border-slate-700 bg-slate-900 px-2 py-2 text-xs font-bold text-slate-100 outline-none focus:border-lime-300"
                      >
                        {(candidate.label_options?.length ? candidate.label_options : [candidate.proposed_label ?? "review_label"]).map((option) => (
                          <option key={option} value={option}>
                            {humanize(option)}
                          </option>
                        ))}
                      </select>
                      <div className="mt-2 text-slate-500">Proposed: {humanize(candidate.proposed_label)}</div>
                      {candidate.safety_notes?.length ? <div className="mt-2 line-clamp-2 text-amber-100">{candidate.safety_notes.slice(0, 2).join(" / ")}</div> : null}
                    </div>
                    <div className="flex flex-wrap items-start gap-2 xl:justify-end">
                      <button
                        type="button"
                        disabled={isLoading}
                        onClick={() => approveDecision(candidate)}
                        className="rounded border border-lime-300 bg-lime-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-lime-200 disabled:opacity-50"
                      >
                        {label !== candidate.proposed_label ? "Approve edit" : "Approve"}
                      </button>
                      <button
                        type="button"
                        disabled={isLoading}
                        onClick={() => onDecision(candidate, "needs_more_evidence")}
                        className="rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200 disabled:opacity-50"
                      >
                        Need evidence
                      </button>
                      <button
                        type="button"
                        disabled={isLoading}
                        onClick={() => onDecision(candidate, "reject_label")}
                        className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-rose-300 hover:text-rose-100 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {!candidates.length && <div className="rounded border border-slate-800 bg-slate-900 p-4 text-sm text-slate-500">No open review-label candidates are available.</div>}
      </div>

      {decided.length ? (
        <div className="mt-4 overflow-hidden rounded border border-slate-800">
          <div className="grid grid-cols-[1fr_0.8fr_0.8fr] bg-slate-900 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-slate-500">
            <div>Recent decision</div>
            <div>Label</div>
            <div>Training use</div>
          </div>
          <div className="divide-y divide-slate-800">
            {decided.slice(0, 5).map((candidate) => (
              <div key={candidate.id} className="grid grid-cols-[1fr_0.8fr_0.8fr] bg-slate-950 px-3 py-3 text-xs">
                <div className="min-w-0 pr-3">
                  <div className="truncate font-black text-slate-100">{humanize(candidate.decision?.decision)}</div>
                  <div className="mt-1 truncate text-slate-500">{humanize(candidate.source)}</div>
                </div>
                <div className="truncate pr-3 font-bold text-lime-100">{humanize(candidate.decision?.final_label)}</div>
                <div className="truncate font-bold text-slate-300">{candidate.decision?.eligible_for_supervised_training ? "supervised label" : "excluded"}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
