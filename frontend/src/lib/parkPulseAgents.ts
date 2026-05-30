import type { ParkState } from "@/types/park";
import type { AgentBrief, RuntimeAgentFinding } from "@/types/platform";

function pct(value?: number) {
  if (typeof value !== "number") return "--";
  return `${Math.round(value)}%`;
}

export function sortedByRisk<T>(items: T[], score: (item: T) => number, limit: number) {
  return [...items].sort((a, b) => score(b) - score(a)).slice(0, limit);
}

export function buildAgentBriefs(state: ParkState): AgentBrief[] {
  const rides = state.guestFlow.rides;
  const outdoorClosureRisk = state.weather.stormRisk;
  const mostConstrainedRide = sortedByRisk(rides, (ride) => ride.waitMins + ride.throughputGap / 20, 1)[0];
  const crowdedZone = sortedByRisk(state.guestFlow.zones, (zone) => zone.density, 1)[0];
  const staffGap = Math.max(0, state.staffing.scheduled - state.staffing.checkedIn);
  const foodZone = state.guestFlow.zones.find((zone) => zone.processType === "food");

  return [
    {
      name: "Weather Agent",
      signal: `${outdoorClosureRisk}% storm risk`,
      finding: "Outdoor queue intake should taper before guests are exposed in the closure window.",
      source: "live",
      tone: outdoorClosureRisk >= 55 ? "risk" : "watch",
    },
    {
      name: "Ride Ops Agent",
      signal: mostConstrainedRide ? `${mostConstrainedRide.name} ${mostConstrainedRide.waitMins}m` : "ride feeds stable",
      finding: "Shift demand toward high-throughput indoor attractions and hold low-capacity ride promos.",
      source: "live",
      tone: mostConstrainedRide && mostConstrainedRide.waitMins >= 35 ? "risk" : "watch",
    },
    {
      name: "Guest Flow Agent",
      signal: crowdedZone ? `${crowdedZone.name} ${pct(crowdedZone.density)}` : "paths stable",
      finding: "Use app routing and signs to split shelter demand across indoor zones.",
      source: "live",
      tone: crowdedZone && crowdedZone.density >= 80 ? "risk" : "watch",
    },
    {
      name: "Staffing Agent",
      signal: `${staffGap} open shifts`,
      finding: "Move two cross-trained staff to food and one to indoor queue control.",
      source: "live",
      tone: staffGap >= 20 ? "risk" : "watch",
    },
    {
      name: "Energy Agent",
      signal: `${pct(state.energy.gridLoadPercent)} grid load`,
      finding: "Reduce noncritical lighting, but preserve HVAC in shelter zones.",
      source: "live",
      tone: state.energy.gridLoadPercent >= 95 ? "risk" : "watch",
    },
    {
      name: "Food Agent",
      signal: foodZone ? `${foodZone.waitMins}m food wait` : "food demand normal",
      finding: "Pre-stage mobile pickup inventory before indoor demand spikes.",
      source: "live",
      tone: foodZone && foodZone.waitMins >= 25 ? "risk" : "ok",
    },
  ];
}

export function agentBriefsFromRuntime(findings?: RuntimeAgentFinding[]): AgentBrief[] {
  if (!findings?.length) return [];
  return findings.slice(0, 10).map((item) => ({
    name: item.name ?? "ParkPulse Agent",
    role: item.role,
    signal: item.input_signals?.[0] ?? item.mode ?? "runtime",
    finding: item.finding ?? "Runtime finding recorded.",
    recommendation: item.recommendation,
    confidence: item.confidence,
    policyRefs: item.policy_refs,
    traceSpan: item.trace_span,
    source: "runtime",
    tone: item.urgency ?? "watch",
  }));
}
