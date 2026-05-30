"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fetchParkPulseApi } from "@/lib/api";

type TwinPoint = {
  minute: number;
  label: string;
  weatherRisk: number;
  indoorQueuePressure: number;
  foodWaitMinutes: number;
  staffStress: number;
  guestSatisfaction: number;
  outdoorClosureRisk: number;
  outdoorRidesClosed: boolean;
};

type TwinPolicyRun = {
  policyId: string;
  policyLabel: string;
  analystReadout: string;
  interventions: Array<{ minute: number; label: string; effect: string }>;
  series: TwinPoint[];
  summary: {
    peakIndoorQueuePressure: number;
    peakFoodWaitMinutes: number;
    peakStaffStress: number;
    finalGuestSatisfaction: number;
    finalIndoorQueuePressure: number;
    finalFoodWaitMinutes: number;
  };
};

type TwinPayload = {
  status: string;
  scenario: {
    title: string;
    totalGuests: number;
    tickMinutes: number;
    horizonMinutes: number;
  };
  engines: string[];
  policies: TwinPolicyRun[];
  comparison: {
    headline: string;
    lowestIndoorPressurePolicy: string;
    highestSatisfactionPolicy: string;
  };
};

type ChartSpec = {
  key: keyof TwinPoint;
  title: string;
  unit: string;
};

const chartSpecs: ChartSpec[] = [
  { key: "indoorQueuePressure", title: "Indoor Queue Pressure", unit: "%" },
  { key: "foodWaitMinutes", title: "Food Wait Time", unit: "min" },
  { key: "staffStress", title: "Staff Stress", unit: "x" },
  { key: "guestSatisfaction", title: "Guest Satisfaction", unit: "" },
  { key: "outdoorClosureRisk", title: "Outdoor Closure Risk", unit: "%" },
];

const policyColors: Record<string, string> = {
  do_nothing: "#f97316",
  notify: "#22d3ee",
  full_intervention: "#34d399",
};

function mergeSeries(policies: TwinPolicyRun[]) {
  const labels = policies[0]?.series.map((point) => ({ minute: point.minute, label: point.label })) ?? [];
  return labels.map((base, index) => {
    const row: Record<string, string | number | boolean> = { ...base };
    for (const policy of policies) {
      const point = policy.series[index];
      if (!point) continue;
      row[`${policy.policyId}_indoorQueuePressure`] = point.indoorQueuePressure;
      row[`${policy.policyId}_foodWaitMinutes`] = point.foodWaitMinutes;
      row[`${policy.policyId}_staffStress`] = point.staffStress;
      row[`${policy.policyId}_guestSatisfaction`] = point.guestSatisfaction;
      row[`${policy.policyId}_outdoorClosureRisk`] = point.outdoorClosureRisk;
    }
    return row;
  });
}

function policyShortLabel(policyId: string) {
  if (policyId === "do_nothing") return "A";
  if (policyId === "notify") return "B";
  return "C";
}

export function DynamicTwinMvpPanel() {
  const [payload, setPayload] = useState<TwinPayload | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadTwin = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/dynamic-twin-demo", { timeoutMs: 8000 });
      const nextPayload = (await response.json()) as TwinPayload;
      if (nextPayload.status !== "success") {
        throw new Error("Dynamic twin demo returned an unavailable response.");
      }
      setPayload(nextPayload);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to load the dynamic twin demo.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTwin();
  }, [loadTwin]);

  const chartRows = useMemo(() => mergeSeries(payload?.policies ?? []), [payload?.policies]);
  const fullPolicy = payload?.policies.find((policy) => policy.policyId === "full_intervention");

  return (
    <section className="rounded-lg border border-emerald-400/25 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Dynamic operational twin MVP</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Thunderstorm policy simulation</h2>
          <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
            {payload?.comparison.headline ?? "Simulates five-minute park-state ticks across guest flow, queues, capacity, staff movement, weather, and intervention effects."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadTwin()}
          disabled={isLoading}
          className="w-fit rounded border border-emerald-300 bg-emerald-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? "Simulating" : "Run simulation"}
        </button>
      </div>

      {errorMessage && <div className="mt-3 rounded border border-amber-400/40 bg-amber-950/40 p-3 text-sm font-bold text-amber-100">{errorMessage}</div>}

      {payload && (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {payload.policies.map((policy) => (
              <div key={policy.policyId} className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-black text-slate-100">{policy.policyLabel}</div>
                  <div className="rounded border border-slate-700 px-2 py-1 text-xs font-black text-slate-300">{policyShortLabel(policy.policyId)}</div>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <div className="text-slate-500">Peak queue</div>
                    <div className="mt-1 font-black text-slate-100">{policy.summary.peakIndoorQueuePressure}%</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Food wait</div>
                    <div className="mt-1 font-black text-slate-100">{policy.summary.peakFoodWaitMinutes}m</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Final sat.</div>
                    <div className="mt-1 font-black text-slate-100">{policy.summary.finalGuestSatisfaction}</div>
                  </div>
                </div>
                <p className="mt-3 text-xs leading-relaxed text-slate-400">{policy.analystReadout}</p>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            {chartSpecs.map((chart) => (
              <div key={chart.key} className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="text-sm font-black text-slate-100">{chart.title}</h3>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{chart.unit || "score"}</div>
                </div>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartRows} margin={{ top: 8, right: 10, left: -14, bottom: 0 }}>
                      <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                      <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} interval={5} minTickGap={12} />
                      <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} width={44} />
                      <Tooltip contentStyle={{ background: "#020617", border: "1px solid #334155", borderRadius: 6, color: "#e2e8f0" }} />
                      <Legend wrapperStyle={{ color: "#cbd5e1", fontSize: 11 }} />
                      {payload.policies.map((policy) => (
                        <Line
                          key={`${policy.policyId}-${chart.key}`}
                          type="monotone"
                          dataKey={`${policy.policyId}_${chart.key}`}
                          name={policyShortLabel(policy.policyId)}
                          stroke={policyColors[policy.policyId] ?? "#cbd5e1"}
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={false}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ))}
          </div>

          {fullPolicy && (
            <div className="mt-4 rounded border border-slate-800 bg-slate-900 p-4">
              <div className="text-sm font-black text-slate-100">Policy C delayed effects</div>
              <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                {fullPolicy.interventions.map((intervention) => (
                  <div key={`${intervention.minute}-${intervention.label}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="text-xs font-black text-emerald-200">+{intervention.minute} min</div>
                    <div className="mt-1 text-sm font-black text-slate-100">{intervention.label}</div>
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">{intervention.effect}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
