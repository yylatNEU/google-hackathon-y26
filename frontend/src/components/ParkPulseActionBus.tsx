"use client";

import type { DecisionBridgeResolution, DeliveryDispatch, GcpDeliveryResult, OptimizationTelemetry, RoleAgentProposal, RoleQualityPrior, RunTelemetry } from "@/types/platform";
import { dispatchBody, dispatchLabel, dispatchTone, ratePct, toneFill } from "@/lib/parkPulseDemoContent";

export function PlanTournament({ optimization }: { optimization?: OptimizationTelemetry }) {
  const candidates = optimization?.candidates ?? [];
  if (!candidates.length) return null;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Plan tournament</div>
          <div className="mt-1 text-sm font-black text-slate-100">{optimization?.decision_summary ?? "Candidate plans scored against current park constraints."}</div>
        </div>
        <div className="rounded bg-slate-900 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-slate-400">
          {optimization?.candidate_source ?? optimization?.mode ?? "optimizer"}
        </div>
      </div>
      <div className="mt-4 grid gap-3 xl:grid-cols-3">
        {candidates.map((candidate) => {
          const selected = candidate.id === optimization?.selected_plan_id;
          const score = candidate.scorecard?.overall ?? 0;
          const mix = candidate.action_mix?.guest_reroute?.target_mix ?? [];
          return (
            <article key={candidate.id ?? candidate.name} className={`rounded-lg border p-3 ${selected ? "border-emerald-400 bg-emerald-950/20" : "border-slate-800 bg-slate-900"}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className={selected ? "text-[10px] font-black uppercase tracking-widest text-emerald-300" : "text-[10px] font-black uppercase tracking-widest text-slate-500"}>
                    {selected ? "Selected mix" : candidate.source === "gemini_custom_mix" ? "Gemini mix" : "Rejected mix"}
                  </div>
                  <div className="mt-1 text-sm font-black text-slate-100">{candidate.name}</div>
                </div>
                <div className={score >= 80 ? "text-xl font-black text-emerald-300" : score >= 65 ? "text-xl font-black text-amber-300" : "text-xl font-black text-red-300"}>{score}</div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-[10px] font-black">
                <div className="rounded bg-slate-950 px-2 py-2">
                  <div className="text-slate-500">Capacity</div>
                  <div className="mt-1 text-xs text-slate-100">{candidate.scorecard?.capacity_fit ?? 0}</div>
                </div>
                <div className="rounded bg-slate-950 px-2 py-2">
                  <div className="text-slate-500">Take</div>
                  <div className="mt-1 text-xs text-slate-100">{candidate.scorecard?.take_rate_likelihood ?? 0}%</div>
                </div>
                <div className="rounded bg-slate-950 px-2 py-2">
                  <div className="text-slate-500">Staff</div>
                  <div className="mt-1 text-xs text-slate-100">{candidate.scorecard?.staff_burden ?? 0}</div>
                </div>
              </div>
              <div className="mt-3 space-y-1">
                {mix.slice(0, 4).map((target) => (
                  <div key={`${candidate.id}-${target.destination}`} className="flex justify-between gap-2 text-xs">
                    <span className="text-slate-400">{target.destination}</span>
                    <span className="font-black text-slate-200">{Math.round((target.share ?? 0) * 100)}%</span>
                  </div>
                ))}
                <div className="flex justify-between gap-2 text-xs">
                  <span className="text-slate-400">Hold/recovery</span>
                  <span className="font-black text-slate-200">{Math.round((candidate.action_mix?.guest_reroute?.holdShare ?? 0) * 100)}%</span>
                </div>
              </div>
              <div className="mt-3 rounded bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-500">
                {selected
                  ? `Projected ${candidate.projected_impact?.densityDeltaPct ?? 0}% density change, ${candidate.projected_impact?.avgWaitDeltaMinutes ?? 0}m wait change.`
                  : candidate.rejected_reasons?.[0] ?? "Lower optimizer score."}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

export type ProgressStage = {
  label: string;
  detail: string;
  status: ProgressStatus;
  metric?: string | number;
};

export type ProgressStatus = "done" | "active" | "pending" | "watch";

export function progressStageClass(status: ProgressStatus) {
  if (status === "done") return "border-emerald-400/40 bg-emerald-950/20 text-emerald-100";
  if (status === "active") return "border-cyan-400/50 bg-cyan-950/30 text-cyan-100";
  if (status === "watch") return "border-amber-400/40 bg-amber-950/20 text-amber-100";
  return "border-slate-800 bg-slate-950 text-slate-400";
}

export function progressDotClass(status: ProgressStatus) {
  if (status === "done") return "bg-emerald-300";
  if (status === "active") return "bg-cyan-300 park-node-pulse";
  if (status === "watch") return "bg-amber-300";
  return "bg-slate-600";
}

function gcpDeliveryRows(dispatch: DeliveryDispatch): Array<[string, GcpDeliveryResult]> {
  const delivery = dispatch.gcpDelivery;
  if (!delivery) return [];
  const rows: Array<[string, GcpDeliveryResult | undefined]> = [
    ["Pub/Sub", delivery.pubsub],
    ["FCM", delivery.fcm],
    ["Workflow", delivery.workflow],
  ];
  return rows.filter((row): row is [string, GcpDeliveryResult] => Boolean(row[1]));
}

function gcpResultTone(status?: string) {
  if (status === "published" || status === "sent" || status === "started") return "text-emerald-300";
  if (status === "skipped") return "text-slate-400";
  return "text-amber-300";
}

export function ProgressRail({ title, stages }: { title: string; stages: ProgressStage[] }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">{title}</div>
        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">
          {stages.filter((stage) => stage.status === "done").length}/{stages.length} complete
        </div>
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-6">
        {stages.map((stage, index) => (
          <div key={`${stage.label}-${index}`} className={`rounded-lg border p-3 ${progressStageClass(stage.status)}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${progressDotClass(stage.status)}`} />
                <div className="truncate text-xs font-black">{stage.label}</div>
              </div>
              {stage.metric !== undefined && <div className="shrink-0 rounded bg-slate-950/70 px-2 py-1 text-[10px] font-black">{stage.metric}</div>}
            </div>
            <div className="mt-2 min-h-8 text-[11px] leading-snug opacity-75">{stage.detail}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function humanizeId(value?: string) {
  return (value || "unknown").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function roleProposalStatus(proposal: RoleAgentProposal, resolution?: DecisionBridgeResolution) {
  const agentId = proposal.agent_id;
  if (agentId && resolution?.accepted_role_proposal?.agent_id === agentId) return "accepted";
  if (agentId && (resolution?.rejected_role_proposals ?? []).some((item) => item.agent_id === agentId)) return "rejected";
  if (["context", "gate", "bridge"].includes(proposal.proposal_type ?? "")) return "context";
  return "scored";
}

function roleProposalTone(status: string) {
  if (status === "accepted") return "border-emerald-400/45 bg-emerald-950/20";
  if (status === "rejected") return "border-amber-400/35 bg-amber-950/15";
  if (status === "context") return "border-cyan-400/30 bg-cyan-950/15";
  return "border-slate-800 bg-slate-900";
}

function roleStatusLabel(status: string) {
  if (status === "accepted") return "Accepted";
  if (status === "rejected") return "Rejected";
  if (status === "context") return "Context";
  return "Scored";
}

function priorLabel(prior?: RoleQualityPrior) {
  if (!prior) return "No prior";
  const adjustment = Number(prior.prior_adjustment ?? 0);
  return `${adjustment >= 0 ? "+" : ""}${adjustment} ${prior.confidence ?? "prior"}`;
}

export function RoleCollaborationPanel({ telemetry }: { telemetry: RunTelemetry }) {
  const roleArtifact = telemetry.role_agent_proposals;
  const proposals = roleArtifact?.proposals ?? [];
  const resolution = telemetry.optimization?.decision_bridge_resolution ?? telemetry.role_outcome_attribution?.decision_bridge_resolution;
  const rolePriors = telemetry.optimization?.memory_used?.role_quality_priors?.by_agent ?? {};
  const selectedPlan = telemetry.optimization?.selected_plan;
  const selectedRole = selectedPlan?.role_proposal;
  const selectedPrior = selectedRole?.memory_prior ?? (selectedRole?.agent_id ? rolePriors[selectedRole.agent_id] : undefined);
  const selectedAdjustment = selectedPlan?.scorecard?.role_memory_prior_adjustment ?? selectedPrior?.prior_adjustment;
  const conflicts = resolution?.conflicts ?? roleArtifact?.conflicts ?? [];
  const outcomeSummary = telemetry.role_outcome_attribution?.summary;
  const roleMemory = telemetry.role_proposal_memory;

  if (!proposals.length && !resolution) return null;

  return (
    <div className="rounded-lg border border-cyan-400/30 bg-cyan-950/10 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Role collaboration</div>
          <div className="mt-2 text-sm font-black text-slate-100">
            {roleArtifact?.mediator_summary ?? resolution?.summary ?? "Specialist role agents proposed bounded actions before the optimizer selected the executable plan."}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center text-[10px] font-black">
          <div className="rounded bg-slate-950 px-3 py-2">
            <div className="text-slate-500">Roles</div>
            <div className="mt-1 text-xs text-cyan-200">{roleArtifact?.active_roles?.length ?? proposals.length}</div>
          </div>
          <div className="rounded bg-slate-950 px-3 py-2">
            <div className="text-slate-500">Proposals</div>
            <div className="mt-1 text-xs text-cyan-200">{roleArtifact?.proposal_count ?? proposals.length}</div>
          </div>
          <div className="rounded bg-slate-950 px-3 py-2">
            <div className="text-slate-500">Conflicts</div>
            <div className="mt-1 text-xs text-cyan-200">{conflicts.length}</div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-[1.3fr_0.7fr]">
        <div className="grid gap-3 md:grid-cols-2">
          {proposals.slice(0, 6).map((proposal) => {
            const status = roleProposalStatus(proposal, resolution);
            const prior = proposal.agent_id ? rolePriors[proposal.agent_id] : undefined;
            const rejected = proposal.agent_id ? resolution?.rejected_role_proposals?.find((item) => item.agent_id === proposal.agent_id) : undefined;
            return (
              <article key={`${proposal.agent_id}-${proposal.proposal_type}`} className={`rounded-lg border p-3 ${roleProposalTone(status)}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-xs font-black text-slate-100">{proposal.role ?? humanizeId(proposal.agent_id)}</div>
                    <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                      {roleStatusLabel(status)} / {proposal.proposal_type ?? "proposal"} / {Math.round(Number(proposal.confidence ?? 0) * 100)}%
                    </div>
                  </div>
                  <div className="shrink-0 rounded bg-slate-950 px-2 py-1 text-[10px] font-black text-cyan-200">{priorLabel(prior)}</div>
                </div>
                <div className="mt-3 text-xs leading-relaxed text-slate-300">{proposal.recommendation}</div>
                <div className="mt-3 flex flex-wrap gap-1">
                  {(proposal.evidence ?? []).slice(0, 2).map((item) => (
                    <span key={item} className="rounded bg-slate-950 px-2 py-1 text-[10px] font-bold text-slate-400">{item}</span>
                  ))}
                </div>
                {rejected?.reason && <div className="mt-3 text-[11px] leading-relaxed text-amber-200/80">{rejected.reason}</div>}
              </article>
            );
          })}
        </div>

        <div className="grid gap-3">
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Decision bridge</div>
            <div className="mt-2 text-sm font-black text-slate-100">{selectedRole?.role ?? humanizeId(resolution?.selected_source)}</div>
            <div className="mt-2 text-xs leading-relaxed text-slate-400">{resolution?.summary ?? telemetry.optimization?.decision_summary ?? "Optimizer scored role proposals against deterministic alternatives."}</div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] font-black">
              <div className="rounded bg-slate-900 px-2 py-2">
                <div className="text-slate-500">Selected source</div>
                <div className="mt-1 truncate text-cyan-200">{humanizeId(resolution?.selected_source ?? telemetry.optimization?.candidate_source)}</div>
              </div>
              <div className="rounded bg-slate-900 px-2 py-2">
                <div className="text-slate-500">Memory shift</div>
                <div className="mt-1 text-cyan-200">{typeof selectedAdjustment === "number" ? `${selectedAdjustment >= 0 ? "+" : ""}${selectedAdjustment}` : "none"}</div>
              </div>
            </div>
          </div>

          {!!conflicts.length && (
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Resolved conflicts</div>
              <div className="mt-2 grid gap-2">
                {conflicts.slice(0, 3).map((conflict, index) => (
                  <div key={`${conflict.kind ?? "conflict"}-${index}`} className="rounded bg-slate-900 px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-[11px] font-black text-amber-200">{humanizeId(conflict.kind ?? conflict.severity)}</div>
                      <div className="shrink-0 text-[10px] font-black uppercase text-slate-500">{conflict.severity ?? "watch"}</div>
                    </div>
                    <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{conflict.resolution ?? conflict.summary ?? (conflict.agents ?? []).join(" vs ")}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {selectedPrior && (
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Role memory prior</div>
              <div className="mt-2 text-xs leading-relaxed text-slate-300">{selectedPrior.rationale ?? "Prior role outcomes are adjusting the candidate score."}</div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-[10px] font-black">
                <div className="rounded bg-slate-900 px-2 py-2">
                  <div className="text-slate-500">Samples</div>
                  <div className="mt-1 text-slate-100">{selectedPrior.sample_count ?? 0}</div>
                </div>
                <div className="rounded bg-slate-900 px-2 py-2">
                  <div className="text-slate-500">Accepted</div>
                  <div className="mt-1 text-slate-100">{selectedPrior.accepted_count ?? 0}</div>
                </div>
                <div className="rounded bg-slate-900 px-2 py-2">
                  <div className="text-slate-500">Avg take</div>
                  <div className="mt-1 text-slate-100">{ratePct(selectedPrior.avg_take_rate)}</div>
                </div>
              </div>
            </div>
          )}

          {(outcomeSummary || roleMemory) && (
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
              Outcome attribution: {outcomeSummary?.accepted_count ?? 0} accepted / {outcomeSummary?.rejected_count ?? 0} rejected / {outcomeSummary?.context_only_count ?? 0} context.{" "}
              {roleMemory?.stored_count !== undefined ? `${roleMemory.stored_count} role outcome rows stored.` : "Role memory write pending."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ActionBusPanel({ telemetry, isRunning }: { telemetry: RunTelemetry | null; isRunning: boolean }) {
  const selected = telemetry?.planner?.selected_action;
  const dispatches = telemetry?.delivery?.dispatches ?? [];
  const response = telemetry?.delivery?.response;
  const summary = telemetry?.delivery?.summary;
  const learningRules = telemetry?.optimization?.memory_used?.learning_rules ?? [];
  const learningEffect = telemetry?.optimization?.memory_used?.learning_effect;
  const outcome = telemetry?.outcome;
  const guestDispatches = dispatches.filter((dispatch) => dispatch.channel === "guest_app");
  const workerDispatches = dispatches.filter((dispatch) => dispatch.channel === "worker_device");
  const equipmentDispatches = dispatches.filter((dispatch) => dispatch.channel === "equipment_controller");
  const workerAckCount = workerDispatches.reduce((sum, dispatch) => sum + (dispatch.response?.acknowledgedCount ?? (dispatch.response?.state === "acknowledged" ? 1 : 0)), 0);
  const equipmentAppliedCount = equipmentDispatches.reduce((sum, dispatch) => sum + (dispatch.response?.applied ? 1 : 0), 0);
  const completeStages: ProgressStage[] = [
    {
      label: "Detect",
      detail: telemetry ? "Incident and live park pressure pulled from the park model plus MongoDB state." : "Waiting for a scenario or injected failure.",
      status: telemetry ? "done" : "pending",
      metric: telemetry?.scenario_key ?? "idle",
    },
    {
      label: "Plan",
      detail: telemetry ? selected?.label ?? "Gemini selected a custom operational response." : "Gemini has not selected a plan yet.",
      status: telemetry ? "done" : "pending",
      metric: telemetry?.planner?.runtime ?? "--",
    },
    {
      label: "Guest app",
      detail: telemetry ? "Promotion and routing messages emitted to affected guests." : "Guest notification pending.",
      status: guestDispatches.length ? "done" : telemetry ? "watch" : "pending",
      metric: guestDispatches.length || "--",
    },
    {
      label: "Workers",
      detail: telemetry ? "Redeployment tasks sent to worker devices with acknowledgement telemetry." : "Worker notification pending.",
      status: workerDispatches.length ? "done" : telemetry ? "watch" : "pending",
      metric: workerAckCount || workerDispatches.length || "--",
    },
    {
      label: "Controls",
      detail: telemetry ? "Equipment and facility commands emitted through REST action bus." : "Hardware control pending.",
      status: equipmentDispatches.length ? "done" : telemetry ? "watch" : "pending",
      metric: equipmentAppliedCount || equipmentDispatches.length || "--",
    },
    {
      label: "React",
      detail: telemetry ? "Observed take rate, sentiment, and follow-through used to judge the plan." : "Outcome telemetry pending.",
      status: response ? (Number(response.takeRate ?? 0) >= 0.45 ? "done" : "watch") : "pending",
      metric: response ? ratePct(response.takeRate) : "--",
    },
  ];

  if (isRunning) {
    return (
      <ProgressRail
        title="Live action progress"
        stages={[
          { label: "Detect", detail: "Reading incident, queue, staff, food, weather, and energy state.", status: "done", metric: "live" },
          { label: "Plan", detail: "Gemini is selecting a custom response instead of a fixed rule.", status: "active", metric: "LLM" },
          { label: "Guest app", detail: "Routing and promotion messages will emit after the plan is selected.", status: "pending" },
          { label: "Workers", detail: "Redeployment notifications are queued for compatible staff only.", status: "pending" },
          { label: "Controls", detail: "HVAC, signage, and queue-control commands are waiting for dispatch.", status: "pending" },
          { label: "React", detail: "Take rate and follow-through will appear after delivery.", status: "pending" },
        ]}
      />
    );
  }

  if (!telemetry) {
    return (
      <ProgressRail title="Live action progress" stages={completeStages} />
    );
  }

  return (
    <div className="grid gap-4">
      <ProgressRail title="Live action progress" stages={completeStages} />

      <RoleCollaborationPanel telemetry={telemetry} />

      <div className="rounded-lg border border-violet-400/30 bg-violet-950/10 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Learning loop</div>
            <div className="mt-2 text-sm font-black text-slate-100">
              {learningRules.length ? "Prior outcome rules influenced this plan" : "This run will create or refresh a learning rule"}
            </div>
          </div>
          <div className="rounded bg-slate-950 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-slate-400">
            {telemetry?.memory?.retrieved_learnings?.length ?? 0} retrieved
          </div>
        </div>
        {learningRules.length ? (
          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            {learningRules.slice(0, 4).map((rule) => (
              <div key={rule._id ?? rule.lesson} className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-black text-violet-100">{rule.lesson}</div>
                  <div className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black text-violet-300">{rule.confidence ?? "--"}</div>
                </div>
                <div className="mt-2 text-[11px] leading-relaxed text-slate-400">{rule.rule}</div>
                <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-slate-500">used {rule.useCount ?? 1}x / {rule._id}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
            After this run, the outcome loop will store a reusable lesson from take rate, worker acknowledgments, equipment application, and park-state movement.
          </div>
        )}
        {learningEffect && (
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            {[
              ["Take-rate multiplier", learningEffect.take_rate_multiplier ?? 1],
              ["Promotion bias", learningEffect.promotion_bias ?? "none"],
              ["Comfort guardrail", learningEffect.prefer_comfort_protection ? "on" : "off"],
              ["Require control", learningEffect.require_equipment_or_staff_action ? "yes" : "no"],
            ].map(([label, value]) => (
              <div key={label} className="rounded bg-slate-950 px-3 py-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className="mt-1 text-xs font-black text-violet-200">{value}</div>
              </div>
            ))}
          </div>
        )}
        {outcome?.learning && (
          <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-300">
            Learned from this run: {outcome.learning.take_rate_signal ?? "outcome stored"} / {outcome.scorecard?.status ?? "memory updated"} / {telemetry.outcome_id ?? "outcome recorded"}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-emerald-400/40 bg-emerald-950/20 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Selected executable action</div>
            <div className="mt-2 text-lg font-black text-emerald-50">{selected?.label ?? "Action selected"}</div>
            <div className="mt-1 text-xs leading-relaxed text-emerald-100/75">{selected?.expected_effect ?? telemetry.execution?.message ?? "Execution result returned."}</div>
          </div>
          <div className="rounded bg-slate-950 px-3 py-2 text-right">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Runtime</div>
            <div className="mt-1 text-xs font-black text-cyan-300">{telemetry.planner?.runtime ?? "fallback"}</div>
          </div>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          {[
            ["Total emits", summary?.total ?? dispatches.length],
            ["Guest app", summary?.guest_app ?? 0],
            ["Worker", summary?.worker_device ?? 0],
            ["Equipment", summary?.equipment_controller ?? 0],
          ].map(([label, value]) => (
            <div key={label} className="rounded bg-slate-950 px-3 py-2">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 text-xl font-black text-slate-100">{value}</div>
            </div>
          ))}
        </div>
      </div>

      <PlanTournament optimization={telemetry.optimization} />

      {telemetry.revision && (
        <div className="rounded-lg border border-amber-400/40 bg-amber-950/20 p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">GCP eval-triggered revision</div>
          <div className="mt-2 text-sm font-black text-amber-50">{telemetry.revision.selected_action?.label ?? telemetry.revision.name}</div>
          <div className="mt-2 text-xs leading-relaxed text-amber-100/75">{telemetry.revision.revision_reason}</div>
          <div className="mt-3 grid gap-2 md:grid-cols-4">
            {(telemetry.revision.action_mix?.guest_reroute?.target_mix ?? []).slice(0, 4).map((target) => (
              <div key={`revision-${target.destination}`} className="rounded bg-slate-950 px-3 py-2 text-xs">
                <div className="font-black text-slate-100">{target.destination}</div>
                <div className="mt-1 text-slate-500">{Math.round((target.share ?? 0) * 100)}% revised share</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-3 xl:grid-cols-3">
        {dispatches.length ? (
          dispatches.map((dispatch) => (
            <article key={dispatch.id ?? `${dispatch.channel}-${dispatch.endpoint}`} className={`rounded-lg border p-4 ${dispatchTone(dispatch.channel)}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest opacity-80">
                    {dispatch.revision ? "Revision " : ""}
                    REST action sent: {dispatchLabel(dispatch.channel)}
                  </div>
                  <div className="mt-1 text-sm font-black">{dispatch.targetSystem ?? "target system"}</div>
                  <div className="mt-1 text-[10px] font-bold opacity-70">{dispatch.endpoint ?? "delivery endpoint"}</div>
                </div>
                <span className="rounded bg-slate-950/70 px-2 py-1 text-[10px] font-black uppercase">{dispatch.status ?? "sent"}</span>
              </div>
              <div className="mt-3 text-xs leading-relaxed opacity-85">{dispatchBody(dispatch)}</div>
              <div className="mt-3 rounded bg-slate-950/70 p-3 text-[11px] leading-relaxed opacity-85">
                {dispatch.response?.signal ?? "Reaction telemetry pending."}
              </div>
              {gcpDeliveryRows(dispatch).length ? (
                <div className="mt-3 rounded bg-slate-950/70 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest opacity-70">GCP delivery</div>
                  <div className="mt-2 grid gap-1.5">
                    {gcpDeliveryRows(dispatch).map(([label, result]) => (
                      <div key={`${dispatch.id}-${label}`} className="grid grid-cols-[4.5rem_5rem_1fr] items-center gap-2 text-[11px]">
                        <span className="font-black opacity-70">{label}</span>
                        <span className={`font-black uppercase ${gcpResultTone(result.status)}`}>{result.status ?? "unknown"}</span>
                        <span className="truncate opacity-65">{result.message_id ?? result.name ?? result.execution ?? result.reason ?? result.topic ?? "configured"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {dispatch.response && (
                <div className="mt-3 grid grid-cols-3 gap-2 text-center text-[10px] font-black">
                  <div className="rounded bg-slate-950/70 px-2 py-2">
                    <div className="text-slate-500">Take</div>
                    <div className="mt-1 text-xs">{ratePct(dispatch.response.takeRate)}</div>
                  </div>
                  <div className="rounded bg-slate-950/70 px-2 py-2">
                    <div className="text-slate-500">React</div>
                    <div className="mt-1 text-xs">{ratePct(dispatch.response.reactiveFollowThroughRate)}</div>
                  </div>
                  <div className="rounded bg-slate-950/70 px-2 py-2">
                    <div className="text-slate-500">Sample</div>
                    <div className="mt-1 text-xs">{dispatch.response.sampleSize ?? 0}</div>
                  </div>
                </div>
              )}
              {dispatch.payload?.targetMix?.length ? (
                <div className="mt-3 rounded bg-slate-950/70 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest opacity-70">Custom routing mix</div>
                  <div className="mt-2 space-y-1">
                    {dispatch.payload.targetMix.slice(0, 4).map((target) => (
                      <div key={`${dispatch.id}-${target.destination}`} className="flex justify-between gap-2 text-[11px]">
                        <span>{target.destination}</span>
                        <span className="font-black">{Math.round((target.share ?? 0) * 100)}%</span>
                      </div>
                    ))}
                    <div className="flex justify-between gap-2 text-[11px]">
                      <span>Hold/recovery</span>
                      <span className="font-black">{Math.round((dispatch.payload.holdShare ?? 0) * 100)}%</span>
                    </div>
                  </div>
                </div>
              ) : null}
            </article>
          ))
        ) : (
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400 xl:col-span-3">No dispatch records returned.</div>
        )}
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Observed reaction</div>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          {[
            ["Take rate", ratePct(response?.takeRate), response?.takeRate ?? 0],
            ["Positive", ratePct(response?.positiveResponseRate), response?.positiveResponseRate ?? 0],
            ["Follow-through", ratePct(response?.reactiveFollowThroughRate), response?.reactiveFollowThroughRate ?? 0],
            ["Response score", `${response?.score ?? telemetry.eval?.scorecard?.response_score ?? 0}/100`, (response?.score ?? 0) / 100],
          ].map(([label, value, raw]) => {
            const tone = Number(raw) >= 0.75 ? "ok" : Number(raw) >= 0.45 ? "watch" : "risk";
            return (
              <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className={tone === "ok" ? "mt-1 text-2xl font-black text-emerald-300" : tone === "watch" ? "mt-1 text-2xl font-black text-amber-300" : "mt-1 text-2xl font-black text-red-300"}>{value}</div>
                <div className="mt-2 h-1.5 rounded bg-slate-800">
                  <div className={`h-1.5 rounded ${toneFill(tone)}`} style={{ width: `${Math.min(100, Math.round(Number(raw) * 100))}%` }} />
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 text-xs text-slate-500">
          Sample size: {response?.sampleSize ?? 0} / Status: {response?.status ?? telemetry.eval?.scorecard?.response_status ?? "unknown"} / Decision: {telemetry.decision_id ?? "recorded"}
        </div>
      </div>
    </div>
  );
}
