export type ProductLoopStage = {
  id: string;
  label: string;
  owner: string;
  role: string;
  evidence: string[];
  tone: "signals" | "model" | "decision" | "gate" | "outcome" | "memory" | "llm";
};

export const PRODUCT_POSITIONING =
  "ParkPulse is an ML-operated park control loop. Live signals become features, predictors score the next state, an optimizer proposes bounded actions, policy and eval gates decide execute versus review, and outcomes feed memory plus training data. The LLM is a sidecar interpreter for messy notes and memory, not the controller.";

export const PRIMARY_OPERATING_STAGES: ProductLoopStage[] = [
  {
    id: "signals",
    label: "Live Park Signals",
    owner: "Telemetry",
    role: "Raw operating state from rides, queues, food, staff, weather, app, and equipment feeds.",
    evidence: ["ride state", "queue pressure", "staff coverage"],
    tone: "signals",
  },
  {
    id: "feature_pipeline",
    label: "Feature Pipeline",
    owner: "Feature pipeline",
    role: "Normalizes live feeds into model-ready features and freshness checks.",
    evidence: ["queue_wait", "zone_density", "food_eta", "staff_gap"],
    tone: "model",
  },
  {
    id: "predictors",
    label: "ML Predictors",
    owner: "Prediction models",
    role: "Forecasts pressure, risk, take-rate, worker load, and confidence over the next operating window.",
    evidence: ["pressure forecast", "risk score", "confidence"],
    tone: "model",
  },
  {
    id: "optimizer",
    label: "Optimizer",
    owner: "Tradeoff engine",
    role: "Ranks feasible interventions against guest flow, safety, staffing, revenue, and policy constraints.",
    evidence: ["ranked action", "tradeoffs", "constraints"],
    tone: "decision",
  },
  {
    id: "candidate_actions",
    label: "Candidate Actions",
    owner: "Action planner",
    role: "Produces bounded dispatch, review, and hold options before anything touches a receiver.",
    evidence: ["dispatch option", "review option", "hold option"],
    tone: "decision",
  },
  {
    id: "policy_gate",
    label: "Policy Gate",
    owner: "Deterministic rules",
    role: "Blocks unsafe, ungrounded, unfair, or unsupported actions before execution.",
    evidence: ["safety", "labor", "privacy"],
    tone: "gate",
  },
  {
    id: "eval_judges",
    label: "Eval Judges",
    owner: "Quality checks",
    role: "Scores groundedness, capacity awareness, staff impact, guest recovery, and actionability.",
    evidence: ["scorecard", "trace checks", "review reason"],
    tone: "gate",
  },
  {
    id: "outcome_tracker",
    label: "Outcome Tracker",
    owner: "Learning loop",
    role: "Records dispatch acknowledgements, observed impact, traces, evals, and training examples.",
    evidence: ["trace row", "eval row", "training label"],
    tone: "outcome",
  },
];

export const LLM_INTERPRETER_STAGES: ProductLoopStage[] = [
  {
    id: "mongodb_memory",
    label: "MongoDB Memory",
    owner: "Memory store",
    role: "Past incidents, playbooks, policy context, and outcome patterns.",
    evidence: ["playbooks", "incidents", "learnings"],
    tone: "memory",
  },
  {
    id: "messy_notes",
    label: "Messy Notes",
    owner: "Operator context",
    role: "Human text, ambiguous observations, guest-care notes, and partial context.",
    evidence: ["operator note", "care note", "field update"],
    tone: "llm",
  },
  {
    id: "llm_interpreter",
    label: "LLM Interpreter",
    owner: "Language sidecar",
    role: "Interprets messy context into structured scenario fields for the optimizer.",
    evidence: ["scenario", "constraints", "explanation"],
    tone: "llm",
  },
  {
    id: "structured_scenario",
    label: "Structured Scenario",
    owner: "Optimizer input",
    role: "Typed situation, constraints, candidate intent, and review reasons.",
    evidence: ["scenario key", "constraints", "review flag"],
    tone: "decision",
  },
];

export function productToneClass(tone: ProductLoopStage["tone"]) {
  if (tone === "signals") return "border-sky-400/30 bg-sky-950/20 text-sky-100";
  if (tone === "model") return "border-emerald-400/30 bg-emerald-950/20 text-emerald-100";
  if (tone === "decision") return "border-cyan-400/30 bg-cyan-950/20 text-cyan-100";
  if (tone === "gate") return "border-amber-400/30 bg-amber-950/20 text-amber-100";
  if (tone === "outcome") return "border-teal-400/30 bg-teal-950/20 text-teal-100";
  if (tone === "llm") return "border-cyan-400/30 bg-cyan-950/20 text-cyan-100";
  return "border-violet-400/30 bg-violet-950/20 text-violet-100";
}
