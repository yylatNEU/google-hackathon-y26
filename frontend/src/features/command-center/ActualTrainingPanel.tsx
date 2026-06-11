"use client";

type ActualTraining = {
  status?: string;
  mode?: string;
  uses_generated_data?: boolean;
  source?: string;
  sample_count?: number;
  min_sample_count?: number;
  model?: {
    type?: string;
    update_rule?: string;
    best_policy_id?: string | null;
    ranked_policies?: Array<{ policy_id?: string; sample_count?: number; average_reward?: number; best_reward?: number; latest_reward?: number }>;
    context_values?: Array<{ context?: string; ranked_policies?: Array<{ policy_id?: string; q_value?: number; sample_count?: number }> }>;
    authority?: string;
  };
  gcp_ml?: {
    online_improvement?: { ready?: boolean; mode?: string; readiness_issues?: string[] };
    bigquery?: { ready?: boolean; project?: string; dataset?: string; readiness_issues?: string[] };
    bigquery_ml_training?: {
      status?: string;
      enabled?: boolean;
      tool?: string;
      model_id?: string | null;
      job_id?: string | null;
      start_condition?: string;
      readiness_issues?: string[];
    };
  };
  episode_fitness?: {
    status?: string;
    mode?: string;
    uses_generated_data?: boolean;
    sample_count?: number;
    average_reward_delta?: number;
    average_pressure_reduction?: number;
    improvement_rate?: number;
    latest_episode?: {
      id?: string;
      source?: string;
      scenario_key?: string;
      action?: { target?: string; action?: string };
      scores?: { actual?: number; baseline?: number; reward_delta?: number; fitness?: number };
      pressure?: { reduction_vs_baseline?: number; reduced_pressure?: boolean };
      active_random_incidents?: Array<{ kind?: string; intensity?: number }>;
    } | null;
  };
  debug?: {
    readiness_issues?: string[];
    memory_rows_available?: number;
    bigquery_rows_available?: number;
  };
};

export function ActualTrainingPanel({
  training,
  isLoading,
  isStartingGcpTraining,
  onRefresh,
  onStartGcpTraining,
  canStartTraining,
}: {
  training: ActualTraining | null;
  isLoading: boolean;
  isStartingGcpTraining: boolean;
  onRefresh: () => void;
  onStartGcpTraining: () => void;
  canStartTraining: boolean;
}) {
  const policies = training?.model?.ranked_policies ?? [];
  const topPolicy = policies[0];
  const episodeFitness = training?.episode_fitness;
  const latestEpisode = episodeFitness?.latest_episode;
  const latestAction = [latestEpisode?.action?.target, latestEpisode?.action?.action].filter(Boolean).join("/");
  const latestIncidents = latestEpisode?.active_random_incidents ?? [];
  const issues = training?.debug?.readiness_issues ?? training?.gcp_ml?.bigquery_ml_training?.readiness_issues ?? [];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Outcome learning</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Observed outcome learning model</h2>
          <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
            Outcome learning reads eval, dispatch, and observed result rows produced by the operating loop. It does not create generated cases in the app path.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="w-fit rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-emerald-300 hover:text-emerald-100 disabled:opacity-50"
          >
            {isLoading && !isStartingGcpTraining ? "Refreshing" : "Refresh learning"}
          </button>
          <button
            type="button"
            onClick={onStartGcpTraining}
            disabled={isLoading || training?.gcp_ml?.bigquery?.ready === false || !canStartTraining}
            className="w-fit rounded border border-emerald-300 bg-emerald-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isStartingGcpTraining ? "Starting BQML" : "Start BigQuery ML"}
          </button>
        </div>
      </div>
      {!canStartTraining && (
        <div className="mt-3 rounded border border-slate-700 bg-slate-900 p-3 text-xs font-bold text-slate-300">
          Signed ML / Ops Admin role is required to start offline learning jobs.
        </div>
      )}

      <div className="mt-4 grid gap-2 md:grid-cols-6">
        {[
          ["Status", training?.status ?? "--"],
          ["Source", training?.source ?? "--"],
          ["Rows", `${training?.sample_count ?? 0}/${training?.min_sample_count ?? "--"}`],
          ["Generated data", training?.uses_generated_data === false ? "no" : "--"],
          ["Best policy", topPolicy?.policy_id ?? "--"],
          ["BQML", training?.gcp_ml?.bigquery_ml_training?.status ?? "--"],
        ].map(([label, value]) => (
          <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
            <div className="mt-1 truncate text-sm font-black text-emerald-100">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr]">
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Policy rewards</div>
          <div className="mt-3 grid gap-2">
            {policies.length ? (
              policies.slice(0, 4).map((policy) => (
                <div key={policy.policy_id} className="grid grid-cols-[1fr_auto_auto] gap-2 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                  <div className="truncate font-black text-slate-100">{policy.policy_id}</div>
                  <div className="font-bold text-slate-400">{policy.sample_count ?? 0} rows</div>
                  <div className="font-black text-emerald-200">{policy.average_reward ?? "--"}</div>
                </div>
              ))
            ) : (
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No observed reward rows available yet.</div>
            )}
          </div>
        </div>

        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Live episode fitness</div>
          <div className="mt-3 grid gap-2 text-xs">
            {[
              ["Status", episodeFitness?.status ?? "waiting"],
              ["Episodes", `${episodeFitness?.sample_count ?? 0}`],
              ["Avg reward delta", `${episodeFitness?.average_reward_delta ?? 0}`],
              ["Avg pressure relief", `${episodeFitness?.average_pressure_reduction ?? 0}`],
              ["Improvement rate", episodeFitness?.improvement_rate != null ? `${Math.round(episodeFitness.improvement_rate * 100)}%` : "--"],
            ].map(([label, value]) => (
              <div key={label} className="grid grid-cols-[8rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 px-3 py-2">
                <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className="truncate font-bold text-slate-100">{value}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-300">
            {latestEpisode ? (
              <>
                Latest {latestAction || "runtime action"} fitness {latestEpisode.scores?.fitness ?? "--"}; reward delta{" "}
                {latestEpisode.scores?.reward_delta ?? "--"} vs no action. Random incidents:{" "}
                {latestIncidents.length ? latestIncidents.map((item) => `${item.kind} ${item.intensity ?? "--"}%`).join(", ") : "none active"}.
              </>
            ) : (
              "Waiting for a live action episode. Random chaos can occur without adding seed rows."
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 rounded border border-slate-800 bg-slate-900 p-3">
        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">GCP ML path</div>
        <div className="mt-3 grid gap-2 text-xs lg:grid-cols-2">
          {[
            ["BigQuery", training?.gcp_ml?.bigquery?.ready ? "ready" : "not ready"],
            ["Dataset", training?.gcp_ml?.bigquery?.dataset ?? "--"],
            ["Online improvement", training?.gcp_ml?.online_improvement?.mode ?? "--"],
            ["Model", training?.gcp_ml?.bigquery_ml_training?.model_id ?? "--"],
            ["Job", training?.gcp_ml?.bigquery_ml_training?.job_id ?? training?.gcp_ml?.bigquery_ml_training?.start_condition ?? "--"],
          ].map(([label, value]) => (
            <div key={label} className="grid grid-cols-[8rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 px-3 py-2">
              <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="truncate font-bold text-slate-100">{value}</div>
            </div>
          ))}
        </div>
      </div>

      {issues.length > 0 && (
        <div className="mt-3 rounded border border-amber-400/30 bg-amber-950/15 p-3 text-xs leading-relaxed text-amber-100">
          Runtime debug: {issues.slice(0, 3).join(" / ")}
        </div>
      )}

      <div className="mt-3 rounded border border-slate-800 bg-slate-900 p-3 text-xs leading-relaxed text-slate-400">
        {training?.model?.authority ?? "The reward model ranks policies only. Dispatch still requires policy, eval, and human-review gates."}
      </div>
    </section>
  );
}
