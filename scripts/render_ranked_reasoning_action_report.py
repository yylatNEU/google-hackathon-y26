#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_REPORT = (
    REPO_ROOT
    / "output"
    / "qa"
    / "frozen-timelapse-benchmark-20260608T012017Z"
    / "frozen-benchmark-report.json"
)
DEFAULT_EXPANDED_REPORT = (
    REPO_ROOT
    / "output"
    / "qa"
    / "frozen-timelapse-benchmark-20260608T015016Z"
    / "frozen-benchmark-report.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "qa"

METRICS = [
    ("average_satisfaction_delta", "Guest satisfaction", True, "points"),
    ("average_wait_delta", "Slowest ride wait", False, "minutes"),
    ("average_food_delta", "Food backlog", False, "orders"),
    ("average_eta_delta", "Food pickup ETA", False, "minutes"),
    ("total_unresolved_tradeoffs", "Unresolved tradeoffs", False, "count"),
    ("total_gemini_errors", "Gemini errors", False, "count"),
]

CASE_METRICS = [
    ("satisfaction_delta", "Satisfaction", True),
    ("wait_delta", "Wait", False),
    ("food_delta", "Food backlog", False),
    ("eta_delta", "Food ETA", False),
    ("unresolved_tradeoff_count", "Tradeoffs", False),
]


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return parsed


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    value = report.get("summary", {})
    return value if isinstance(value, dict) else {}


def _cases_by_scenario(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = report.get("cases", [])
    if not isinstance(cases, list):
        return {}
    return {
        str(case.get("scenario")): case
        for case in cases
        if isinstance(case, dict) and case.get("scenario")
    }


def _calls_path(case: dict[str, Any]) -> Path | None:
    run_dir = Path(str(case.get("candidate_run") or ""))
    direct = run_dir / "gemini-operation-calls.jsonl"
    if direct.exists():
        return direct
    matches = list(run_dir.glob("**/gemini-operation-calls.jsonl"))
    return matches[0] if matches else None


def _get(row: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = row
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return default
    return current


def _action_key(row: dict[str, Any]) -> str:
    action = row.get("allowed_action")
    if not isinstance(action, dict):
        action = row.get("model_allowed_action")
    if not isinstance(action, dict):
        return "none"
    return f"{action.get('target')}/{action.get('action')}"


def _memory_status(row: dict[str, Any]) -> str:
    memory = row.get("memory_context")
    if not isinstance(memory, dict):
        return "none"
    return str(memory.get("status") or "none")


def _memory_role(row: dict[str, Any]) -> str:
    memory = row.get("memory_context")
    if not isinstance(memory, dict):
        return "none"
    examples = memory.get("examples") if isinstance(memory.get("examples"), list) else []
    cautionary = memory.get("cautionary_examples") if isinstance(memory.get("cautionary_examples"), list) else []
    if examples:
        return "direct memory"
    if cautionary:
        return "cautionary memory"
    status = str(memory.get("status") or "none")
    if status.startswith("abstained"):
        return "memory abstained"
    return status


def _truncate(text: Any, limit: int = 220) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _status_kind(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"passed", "success", "ok", "ready", "go_with_conditions"}:
        return "ok"
    if "override" in text or "tradeoff" in text or "condition" in text or "abstained" in text:
        return "warn"
    if "error" in text or "blocked" in text or "fail" in text or "regress" in text:
        return "bad"
    return "neutral"


def _badge(value: Any, kind: str | None = None) -> str:
    style = kind or _status_kind(value)
    return f"<span class='badge {style}'>{_e(value)}</span>"


def _metric_card(label: str, value: Any, note: str, kind: str = "neutral") -> str:
    return (
        f"<section class='metric {kind}'>"
        f"<span>{_e(label)}</span>"
        f"<strong>{_e(_fmt(value))}</strong>"
        f"<small>{_e(note)}</small>"
        "</section>"
    )


def _metric_benefit(value: float, higher_is_better: bool) -> float:
    return value if higher_is_better else -value


def _metric_verdict(expanded: float, baseline: float, higher_is_better: bool) -> str:
    delta = expanded - baseline
    if not higher_is_better:
        delta = -delta
    if delta > 0.01:
        return "expanded better"
    if delta < -0.01:
        return "baseline better"
    return "tie"


def _comparison_svg(rows: list[dict[str, Any]]) -> str:
    row_h = 42
    width = 920
    left = 210
    center = 520
    max_bar = 240
    height = 44 + row_h * len(rows)
    benefits = []
    for row in rows:
        benefits.append(abs(_metric_benefit(row["baseline"], row["higher_is_better"])))
        benefits.append(abs(_metric_benefit(row["expanded"], row["higher_is_better"])))
    scale = max(benefits) or 1
    parts = [
        f"<svg class='chart' viewBox='0 0 {width} {height}' role='img' aria-label='Baseline comparison chart'>",
        f"<line x1='{center}' x2='{center}' y1='24' y2='{height - 16}' class='axis'/>",
        f"<text x='{center - max_bar}' y='18' class='legend baseline'>Baseline</text>",
        f"<text x='{center + 92}' y='18' class='legend expanded'>Expanded memory</text>",
    ]
    for idx, row in enumerate(rows):
        y = 42 + idx * row_h
        base_benefit = _metric_benefit(row["baseline"], row["higher_is_better"])
        exp_benefit = _metric_benefit(row["expanded"], row["higher_is_better"])
        base_w = max(2, abs(base_benefit) / scale * max_bar)
        exp_w = max(2, abs(exp_benefit) / scale * max_bar)
        base_class = "bar baseline" if base_benefit >= 0 else "bar baseline negative"
        exp_class = "bar expanded" if exp_benefit >= 0 else "bar expanded negative"
        parts.extend(
            [
                f"<text x='18' y='{y + 9}' class='label'>{_e(row['label'])}</text>",
                f"<rect x='{center - base_w}' y='{y - 10}' width='{base_w}' height='12' class='{base_class}'/>",
                f"<rect x='{center}' y='{y + 5}' width='{exp_w}' height='12' class='{exp_class}'/>",
                f"<text x='{center - base_w - 10}' y='{y}' text-anchor='end' class='value'>{_e(_fmt(row['baseline']))}</text>",
                f"<text x='{center + exp_w + 10}' y='{y + 15}' class='value'>{_e(_fmt(row['expanded']))}</text>",
                f"<text x='{width - 18}' y='{y + 9}' text-anchor='end' class='verdict'>{_e(row['verdict'])}</text>",
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _case_table(expanded_cases: dict[str, dict[str, Any]], baseline_cases: dict[str, dict[str, Any]]) -> str:
    headers = [
        "Scenario",
        "Satisfaction",
        "Wait",
        "Food backlog",
        "Food ETA",
        "Tradeoffs",
        "Scenario verdict",
    ]
    rows = []
    for scenario, expanded in expanded_cases.items():
        baseline = baseline_cases.get(scenario, {})
        cells = [f"<td>{_e(scenario)}</td>"]
        better_count = 0
        worse_count = 0
        for key, _label, higher in CASE_METRICS:
            ev = _num(expanded.get(key))
            bv = _num(baseline.get(key))
            verdict = _metric_verdict(ev, bv, higher)
            if verdict == "expanded better":
                better_count += 1
            elif verdict == "baseline better":
                worse_count += 1
            cells.append(
                "<td>"
                f"<b>{_e(_fmt(ev))}</b>"
                f"<small>baseline {_e(_fmt(bv))}</small>"
                f"{_badge(verdict)}"
                "</td>"
            )
        if scenario == "storm_response":
            decision = "human review required"
            kind = "bad"
        elif worse_count > better_count:
            decision = "supervised only"
            kind = "warn"
        else:
            decision = "pilot candidate"
            kind = "ok"
        cells.append(f"<td>{_badge(decision, kind)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f"<table class='dense'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _collect_action_data(expanded_report: dict[str, Any]) -> dict[str, Any]:
    action_mix: Counter[str] = Counter()
    action_mix_by_scenario: dict[str, Counter[str]] = defaultdict(Counter)
    memory_statuses: Counter[str] = Counter()
    selection_statuses: Counter[str] = Counter()
    gate_statuses: Counter[str] = Counter()
    sample_rows: list[dict[str, Any]] = []
    scenario_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for case in expanded_report.get("cases", []):
        if not isinstance(case, dict):
            continue
        scenario = str(case.get("scenario") or "unknown")
        path = _calls_path(case)
        rows = _load_jsonl(path) if path else []
        for row in rows:
            action = _action_key(row)
            action_mix[action] += 1
            action_mix_by_scenario[scenario][action] += 1
            memory_statuses[_memory_status(row)] += 1
            selection_statuses[str(_get(row, "candidate_selection.status", "unknown"))] += 1
            gate_statuses[str(_get(row, "policy_gate.status", "unknown"))] += 1
            scenario_rows[scenario].append(row)

    for scenario, rows in scenario_rows.items():
        if not rows:
            continue
        chosen: list[dict[str, Any]] = []
        # Pick a few records that show memory, overrides, and normal passes.
        for predicate in (
            lambda r: _memory_role(r) == "direct memory",
            lambda r: _memory_role(r) == "cautionary memory",
            lambda r: "override" in str(_get(r, "candidate_selection.status", "")).lower(),
            lambda r: True,
        ):
            for row in rows:
                if row in chosen:
                    continue
                if predicate(row):
                    chosen.append(row)
                    break
            if len(chosen) >= 3:
                break
        for row in chosen[:3]:
            sample_rows.append(
                {
                    "scenario": scenario,
                    "minute": row.get("sim_minute"),
                    "sim_time": row.get("sim_time"),
                    "memory_role": _memory_role(row),
                    "memory_status": _memory_status(row),
                    "selected_candidate": _get(row, "candidate_selection.selected_candidate_id"),
                    "selected_score": _get(row, "candidate_selection.selected_candidate_score"),
                    "action": _action_key(row),
                    "candidate_status": _get(row, "candidate_selection.status"),
                    "policy_gate": _get(row, "policy_gate.status"),
                    "execution_status": _get(row, "execution.status", row.get("status")),
                    "primary_risk": _get(row, "parsed_response.risk_classification.primary_risk"),
                    "operator_explanation": _truncate(_get(row, "parsed_response.operator_explanation"), 260),
                }
            )

    return {
        "action_mix": dict(action_mix),
        "action_mix_by_scenario": {key: dict(value) for key, value in action_mix_by_scenario.items()},
        "memory_statuses": dict(memory_statuses),
        "selection_statuses": dict(selection_statuses),
        "gate_statuses": dict(gate_statuses),
        "sample_action_records": sample_rows,
    }


def _counter_table(counter: dict[str, int], first_header: str, second_header: str = "Count") -> str:
    rows = []
    for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        rows.append(f"<tr><td>{_e(key)}</td><td>{_e(value)}</td></tr>")
    if not rows:
        rows.append("<tr><td colspan='2'>No records</td></tr>")
    return (
        "<table><thead><tr>"
        f"<th>{_e(first_header)}</th><th>{_e(second_header)}</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _action_log_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "Scenario",
        "Minute",
        "Memory",
        "Selected candidate",
        "Action",
        "Gate",
        "Reasoning",
    ]
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{_e(row.get('scenario'))}</td>"
            f"<td>{_e(row.get('minute'))}</td>"
            f"<td>{_badge(row.get('memory_role'))}<small>{_e(row.get('memory_status'))}</small></td>"
            f"<td>{_e(row.get('selected_candidate'))}<small>score {_e(row.get('selected_score'))}; {_e(row.get('candidate_status'))}</small></td>"
            f"<td>{_e(row.get('action'))}</td>"
            f"<td>{_badge(row.get('policy_gate'))}</td>"
            f"<td>{_e(row.get('operator_explanation'))}</td>"
            "</tr>"
        )
    if not body:
        body.append("<tr><td colspan='7'>No Gemini action records were found.</td></tr>")
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f"<table class='dense'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _negotiation_log(expanded_cases: dict[str, dict[str, Any]], baseline_cases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    log = []
    for scenario, expanded in expanded_cases.items():
        baseline = baseline_cases.get(scenario, {})
        sat_gain = _num(expanded.get("satisfaction_delta")) - _num(baseline.get("satisfaction_delta"))
        wait_gain = _num(baseline.get("wait_delta")) - _num(expanded.get("wait_delta"))
        food_loss = _num(expanded.get("food_delta")) - _num(baseline.get("food_delta"))
        eta_loss = _num(expanded.get("eta_delta")) - _num(baseline.get("eta_delta"))
        if scenario == "storm_response":
            verdict = "reject autonomous release for this scenario"
            reason = "Expanded memory improved satisfaction and wait, but produced a large food backlog and ETA regression that needs human escalation."
        elif food_loss > 20 or eta_loss > 2:
            verdict = "approve only with food-service guardrails"
            reason = "Guest-flow gains are real, but food recovery is weaker than the no-memory control."
        else:
            verdict = "approve for supervised pilot"
            reason = "Expanded memory improves the main guest-flow metrics without a severe scenario-specific regression."
        log.append(
            {
                "scenario": scenario,
                "operator_position": f"Use ranked candidate selection because satisfaction changed by {sat_gain:.3f} and wait benefit changed by {wait_gain:.3f} versus no-memory baseline.",
                "risk_reviewer_position": f"Food backlog delta versus baseline is {food_loss:.3f}; ETA delta versus baseline is {eta_loss:.3f}.",
                "executive_verdict": verdict,
                "reason": reason,
            }
        )
    return log


def _negotiation_table(rows: list[dict[str, Any]]) -> str:
    headers = ["Scenario", "Operations argument", "Risk review", "Executive verdict"]
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{_e(row.get('scenario'))}</td>"
            f"<td>{_e(row.get('operator_position'))}</td>"
            f"<td>{_e(row.get('risk_reviewer_position'))}</td>"
            f"<td>{_badge(row.get('executive_verdict'), _status_kind(row.get('executive_verdict')))}<p>{_e(row.get('reason'))}</p></td>"
            "</tr>"
        )
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f"<table class='dense'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _build_multi_agent_collaboration(report: dict[str, Any], action_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_answer": {
            "decision": "Do not present ranked_reasoning_expanded_memory_v1 as the final live-park operating model.",
            "why": "The run proves ranked LLM candidate selection with memory, but it does not prove the real LLM advantage: multi-agent negotiation, full policy/regulatory judgment, and executive resolution over messy cross-department tradeoffs.",
            "operating_rule": "Use this artifact as evidence of an incomplete ranked-reasoning baseline. The corrected model must route every action through explicit agent negotiation, policy/regulatory judging, executive approval, signed receipt, and outcome memory.",
        },
        "agents": [
            {
                "agent": "Scan agent",
                "role": "Read-only sensing layer",
                "reasoning_output": "Turns noisy ride, food, staff, crowd, weather, and guest-care signals into a current risk picture.",
                "decision_power": "Can escalate to React or Proact; cannot dispatch.",
            },
            {
                "agent": "Memory agent",
                "role": "MongoDB retrieval and cautionary recall",
                "reasoning_output": f"Supplied direct memory {report['memory_receipt']['direct_memory_calls']} times and cautionary memory {report['memory_receipt']['cautionary_memory_calls']} times.",
                "decision_power": "Can influence ranking context; cannot override current state or policy gates.",
            },
            {
                "agent": "Proact agent",
                "role": "Preventive planning",
                "reasoning_output": "Looks for weak signals and chooses reversible nudges such as rerouting, pickup expansion, or demand redirection.",
                "decision_power": "Can propose bounded preventive actions after simulation and policy validation.",
            },
            {
                "agent": "React agent",
                "role": "Confirmed-incident response",
                "reasoning_output": "Handles ride-down, food-spike, staff-shortage, and storm-response incidents with specific candidate actions.",
                "decision_power": "Can propose bounded action payloads; cannot reopen rides, clear maintenance, or bypass certifications.",
            },
            {
                "agent": "Gemini ranked reasoner",
                "role": "Candidate negotiation and explanation",
                "reasoning_output": f"Ranked {action_data['total_action_records']} operation calls and selected from policy-passed candidate IDs.",
                "decision_power": "Chooses among allowed candidates, explains alternatives, and exposes primary risk classification.",
            },
            {
                "agent": "Policy gate",
                "role": "Hard-rule enforcement",
                "reasoning_output": "Blocks unsafe or unauthorized actions regardless of model score.",
                "decision_power": "Final authority over policy eligibility before execution.",
            },
            {
                "agent": "Executive decision bridge",
                "role": "Tradeoff and release owner",
                "reasoning_output": "Accepts the guest-flow lift but refuses autonomous release because food/storm tradeoffs remain.",
                "decision_power": "Approves supervised pilot only; requires human approval for food-critical and storm-response regressions.",
            },
            {
                "agent": "Delivery and eval agent",
                "role": "Receipt, outcome, and learning loop",
                "reasoning_output": "Records selected action, reasoning, policy result, execution status, and post-action metrics for future memory.",
                "decision_power": "Can write learning memory after receipts; cannot create authority for unsafe actions.",
            },
        ],
        "reasoning_rounds": [
            {
                "round": "1. Sense",
                "lead": "Scan agent",
                "question": "What is happening in the park right now?",
                "answer": "Identify current risk across ride wait, food backlog, ETA, density, staff callouts, and storm/access signals.",
            },
            {
                "round": "2. Recall",
                "lead": "Memory agent",
                "question": "Have we seen a similar case, and should it guide or warn us?",
                "answer": "Use MongoDB examples only when similarity is strong; otherwise use cautionary examples or abstain.",
            },
            {
                "round": "3. Propose",
                "lead": "React/Proact agents",
                "question": "Which bounded actions are worth considering?",
                "answer": "Create policy-eligible actions such as reroute, redirect food demand, open temporary pickup, pause mobile intake, or redeploy food-certified staff.",
            },
            {
                "round": "4. Rank",
                "lead": "Gemini ranked reasoner",
                "question": "Which action best fits the current risk and tradeoff?",
                "answer": "Rank candidate IDs, explain the primary risk, reject weaker alternatives, and select one policy-passed candidate.",
            },
            {
                "round": "5. Gate",
                "lead": "Policy gate",
                "question": "Is the selected action allowed under hard operational policy?",
                "answer": "Permit only bounded actions. Keep ride reopening, maintenance clearance, medical/security, certification, and emergency authority behind humans.",
            },
            {
                "round": "6. Decide",
                "lead": "Executive bridge",
                "question": "Can this model be trusted as the release model?",
                "answer": "Yes for supervised pilot and demo evidence; no for autonomous release until food and storm tradeoffs improve.",
            },
            {
                "round": "7. Learn",
                "lead": "Delivery/eval agent",
                "question": "What should become memory for the next run?",
                "answer": "Store action reasoning, policy result, selected candidate, rejected alternatives, outcome deltas, and human verdict.",
            },
        ],
    }


def _collaboration_figure(collaboration: dict[str, Any]) -> str:
    nodes = [
        ("Scan", "messy live signals", "#50627a"),
        ("Memory", "MongoDB recall", "#097969"),
        ("React/Proact", "candidate actions", "#2f6db3"),
        ("Gemini", "rank + explain", "#6b4bb4"),
        ("Policy Gate", "hard rules", "#9a5b00"),
        ("Executive", "final answer", "#b42318"),
        ("Delivery/Eval", "receipt + learning", "#4f6f52"),
    ]
    width = 1040
    height = 260
    x0 = 38
    gap = 145
    y = 86
    parts = [
        f"<svg class='collab-figure' viewBox='0 0 {width} {height}' role='img' aria-label='Multi-agent collaboration decision flow'>",
        "<defs><marker id='arrow' markerWidth='9' markerHeight='9' refX='7' refY='4.5' orient='auto'><path d='M0,0 L9,4.5 L0,9 z' fill='#6b7482'/></marker></defs>",
    ]
    for idx in range(len(nodes) - 1):
        x = x0 + idx * gap + 112
        parts.append(f"<line x1='{x}' y1='{y + 34}' x2='{x + 54}' y2='{y + 34}' class='flow-line' marker-end='url(#arrow)'/>")
    for idx, (name, note, color) in enumerate(nodes):
        x = x0 + idx * gap
        parts.extend(
            [
                f"<rect x='{x}' y='{y}' width='118' height='68' rx='4' fill='white' stroke='{color}' stroke-width='2'/>",
                f"<text x='{x + 59}' y='{y + 27}' text-anchor='middle' class='node-title'>{_e(name)}</text>",
                f"<text x='{x + 59}' y='{y + 49}' text-anchor='middle' class='node-note'>{_e(note)}</text>",
            ]
        )
    parts.extend(
        [
            "<path d='M910 170 C720 228 360 228 140 170' fill='none' stroke='#9aa5b5' stroke-width='2' stroke-dasharray='5 5' marker-end='url(#arrow)'/>",
            "<text x='520' y='238' text-anchor='middle' class='loop-note'>outcome receipts write back to memory for the next operating cycle</text>",
            "</svg>",
        ]
    )
    return "\n".join(parts)


def _collaboration_agent_table(collaboration: dict[str, Any]) -> str:
    headers = ["Agent", "Role", "Reasoning contribution", "Decision authority"]
    body = []
    for row in collaboration["agents"]:
        body.append(
            "<tr>"
            f"<td>{_e(row['agent'])}</td>"
            f"<td>{_e(row['role'])}</td>"
            f"<td>{_e(row['reasoning_output'])}</td>"
            f"<td>{_e(row['decision_power'])}</td>"
            "</tr>"
        )
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f"<table class='dense'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _collaboration_round_table(collaboration: dict[str, Any]) -> str:
    headers = ["Round", "Lead agent", "Question", "Answer"]
    body = []
    for row in collaboration["reasoning_rounds"]:
        body.append(
            "<tr>"
            f"<td>{_e(row['round'])}</td>"
            f"<td>{_e(row['lead'])}</td>"
            f"<td>{_e(row['question'])}</td>"
            f"<td>{_e(row['answer'])}</td>"
            "</tr>"
        )
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f"<table class='dense'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _llm_advantage_audit_table(audit: dict[str, Any]) -> str:
    headers = ["LLM advantage", "Current evidence", "Verdict", "Correction"]
    body = []
    for row in audit["capabilities"]:
        body.append(
            "<tr>"
            f"<td>{_e(row['capability'])}</td>"
            f"<td>{_e(row['current_evidence'])}</td>"
            f"<td>{_badge(row['verdict'], _status_kind(row['verdict']))}</td>"
            f"<td>{_e(row['correction'])}</td>"
            "</tr>"
        )
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f"<table class='dense'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _corrective_path_table(audit: dict[str, Any]) -> str:
    headers = ["Step", "Backend owner", "Trace artifact", "Acceptance test"]
    body = []
    for row in audit["corrective_path"]:
        body.append(
            "<tr>"
            f"<td>{_e(row['step'])}</td>"
            f"<td>{_e(row['backend_owner'])}</td>"
            f"<td><code>{_e(row['trace_artifact'])}</code></td>"
            f"<td>{_e(row['acceptance_test'])}</td>"
            "</tr>"
        )
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f"<table class='dense'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _latest_corrective_smoke_artifact() -> dict[str, Any]:
    root = REPO_ROOT / "output" / "qa" / "corrected-negotiation-smoke"
    if not root.exists():
        return {"status": "not_run"}
    candidates = sorted(root.glob("timelapse-cost-probe-*/gemini-operation-calls.jsonl"))
    for path in reversed(candidates):
        rows = _load_jsonl(path)
        if not rows:
            continue
        first = rows[0]
        if first.get("negotiation_trace") and first.get("policy_regulation_judgment"):
            return {
                "status": "verified",
                "gemini_operation_calls": str(path.resolve()),
                "report": str((path.parent / "one-day-cost-report.json").resolve()),
                "negotiation_mode": first.get("negotiation_trace", {}).get("mode"),
                "policy_regulation_status": first.get("policy_regulation_judgment", {}).get("status"),
                "final_executive_status": first.get("negotiation_trace", {}).get("final_executive_decision", {}).get("status"),
            }
    return {"status": "not_verified"}


def _corrective_implementation_list(implementation: dict[str, Any]) -> str:
    items = [
        f"Runner patch status: {implementation.get('status')}",
        f"New trace fields: {', '.join(implementation.get('new_trace_fields', []))}",
        f"Verification status: {implementation.get('verification', {}).get('status')}",
    ]
    verification = implementation.get("verification", {}) if isinstance(implementation.get("verification"), dict) else {}
    if verification.get("gemini_operation_calls"):
        items.append(f"Smoke decision log: {verification.get('gemini_operation_calls')}")
    if verification.get("policy_regulation_status"):
        items.append(f"Smoke policy/regulation status: {verification.get('policy_regulation_status')}")
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"


def _render_html(report: dict[str, Any]) -> str:
    comparison_rows = report["baseline_comparison"]
    metrics = report["deployment_receipt"]["headline_metrics"]
    memory = report["memory_receipt"]
    chart = _comparison_svg(comparison_rows)
    expanded_cases = report["scenario_comparison"]["expanded_cases"]
    baseline_cases = report["scenario_comparison"]["baseline_cases"]
    action_data = report["action_recording"]
    decision = report["executive_decision"]
    collaboration = report["multi_agent_collaboration"]
    llm_audit = report["llm_advantage_audit"]

    metric_cards = "".join(
        [
            _metric_card("Avg satisfaction lift", metrics["expanded_average_satisfaction_delta"], "expanded memory vs no action", "ok"),
            _metric_card("Avg wait movement", metrics["expanded_average_wait_delta"], "lower is better", "ok"),
            _metric_card("Avg food backlog movement", metrics["expanded_average_food_delta"], "higher means worse", "bad"),
            _metric_card("Projected week cost", f"${metrics['expanded_projected_week_cost_usd']}", "Gemini calls only", "neutral"),
            _metric_card("Policy score", metrics["expanded_average_policy_score"], "limited hard gates only", "warn"),
            _metric_card("Release posture", decision["status"], decision["decision"], "warn"),
        ]
    )

    conditions = "".join(f"<li>{_e(item)}</li>" for item in decision["conditions"])
    evidence = "".join(f"<li>{_e(item)}</li>" for item in report["evidence_limits"])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(report["title"])}</title>
  <style>
    :root {{
      --ink: #18202f;
      --muted: #627084;
      --line: #d7dde7;
      --panel: #f7f9fc;
      --baseline: #5f6f8f;
      --expanded: #097969;
      --bad: #b42318;
      --warn: #9a5b00;
      --ok: #087443;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #ffffff;
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 34px 28px 56px; }}
    header {{ border-bottom: 2px solid var(--ink); padding-bottom: 18px; margin-bottom: 22px; }}
    h1 {{ font-size: 30px; line-height: 1.1; margin: 0 0 10px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 30px 0 12px; letter-spacing: 0; }}
    h3 {{ font-size: 15px; margin: 18px 0 8px; letter-spacing: 0; }}
    p {{ margin: 8px 0; max-width: 920px; }}
    .subhead {{ color: var(--muted); font-size: 15px; }}
    .notice {{
      border-left: 4px solid var(--warn);
      background: #fff8eb;
      padding: 12px 14px;
      margin: 18px 0;
    }}
    .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .metric {{
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 12px;
      min-height: 96px;
    }}
    .metric span, .metric small {{ display: block; color: var(--muted); }}
    .metric strong {{ display: block; font-size: 25px; margin: 7px 0; }}
    .metric.ok strong {{ color: var(--ok); }}
    .metric.warn strong {{ color: var(--warn); }}
    .metric.bad strong {{ color: var(--bad); }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 20px; }}
    th, td {{ border: 1px solid var(--line); padding: 9px 10px; vertical-align: top; text-align: left; }}
    th {{ background: #eef2f7; font-size: 12px; text-transform: uppercase; color: #3e4a5e; }}
    td small {{ display: block; color: var(--muted); margin-top: 4px; }}
    .dense td {{ font-size: 13px; }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--line);
      padding: 2px 7px;
      font-size: 12px;
      font-weight: 650;
      background: white;
      color: var(--muted);
    }}
    .badge.ok {{ border-color: #9fd5bc; color: var(--ok); background: #ecf8f1; }}
    .badge.warn {{ border-color: #e8c27b; color: var(--warn); background: #fff7e6; }}
    .badge.bad {{ border-color: #e2a29b; color: var(--bad); background: #fff1f0; }}
    .chart {{ width: 100%; max-width: 1000px; display: block; margin: 12px 0 20px; background: #fbfcfe; border: 1px solid var(--line); }}
    .collab-figure {{ width: 100%; display: block; margin: 12px 0 20px; background: #fbfcfe; border: 1px solid var(--line); }}
    .axis {{ stroke: #94a0b4; stroke-width: 1; }}
    .flow-line {{ stroke: #6b7482; stroke-width: 2; }}
    .node-title {{ font-size: 13px; font-weight: 750; fill: var(--ink); }}
    .node-note {{ font-size: 11px; fill: var(--muted); }}
    .loop-note {{ font-size: 12px; fill: var(--muted); }}
    .bar.baseline {{ fill: var(--baseline); }}
    .bar.expanded {{ fill: var(--expanded); }}
    .bar.negative {{ opacity: 0.35; }}
    .label {{ font-size: 13px; fill: var(--ink); }}
    .legend, .value, .verdict {{ font-size: 12px; fill: var(--muted); }}
    .legend.baseline {{ fill: var(--baseline); font-weight: 700; }}
    .legend.expanded {{ fill: var(--expanded); font-weight: 700; }}
    ul {{ margin: 8px 0 18px 22px; padding: 0; }}
    li {{ margin: 6px 0; }}
    code {{ background: #f1f4f8; padding: 1px 4px; }}
    @media (max-width: 760px) {{
      main {{ padding: 22px 14px 40px; }}
      .grid {{ grid-template-columns: 1fr; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>{_e(report["title"])}</h1>
    <p class="subhead">Generated {_e(report["created_at"])} from frozen one-day sim-time artifacts. Model: <code>{_e(report["model"]["id"])}</code>.</p>
  </header>

  <section class="notice">
    <b>Deployment status:</b> {_e(report["deployment_receipt"]["status_note"])}
  </section>

  <section class="grid">
    {metric_cards}
  </section>

  <h2>Executive Decision</h2>
  <p><b>{_e(decision["decision"])}</b>: {_e(decision["summary"])}</p>
  <ul>{conditions}</ul>

  <h2>Final Answer</h2>
  <p><b>{_e(collaboration["final_answer"]["decision"])}</b></p>
  <p>{_e(collaboration["final_answer"]["why"])}</p>
  <p>{_e(collaboration["final_answer"]["operating_rule"])}</p>

  <h2>Corrected LLM Advantage Audit</h2>
  <p>{_e(llm_audit["summary"])}</p>
  {_llm_advantage_audit_table(llm_audit)}

  <h3>Correction Path</h3>
  {_corrective_path_table(llm_audit)}

  <h3>Correction Implemented In Runner</h3>
  {_corrective_implementation_list(report["corrective_implementation"])}

  <h2>Multi-Agent Collaboration Reasoning</h2>
  <p>This is the decision path the app must implement before claiming the LLM advantage was used correctly. The current timelapse run did not execute this full path; it only produced ranked candidate reasoning with limited gates.</p>
  {_collaboration_figure(collaboration)}
  {_collaboration_round_table(collaboration)}

  <h3>Agent Responsibilities</h3>
  {_collaboration_agent_table(collaboration)}

  <h2>Baseline Comparison Graph</h2>
  <p>The graph compares the no-memory ranked Gemini baseline with the ranked reasoning model using expanded MongoDB memory. For wait, backlog, ETA, tradeoffs, and errors, lower raw values are better.</p>
  {chart}

  <h2>Scenario Comparison</h2>
  {_case_table(expanded_cases, baseline_cases)}

  <h2>Action Recording</h2>
  <p>The expanded-memory run recorded {_e(report["action_recording"]["total_action_records"])} Gemini operation calls across four scenarios. Each call includes the ranked candidates, policy gate status, selected action, memory context, and operator explanation.</p>
  <div class="grid">
    <section>
      <h3>Action Mix</h3>
      {_counter_table(action_data["action_mix"], "Action")}
    </section>
    <section>
      <h3>Memory Status</h3>
      {_counter_table(action_data["memory_statuses"], "Memory status")}
    </section>
    <section>
      <h3>Candidate Selection</h3>
      {_counter_table(action_data["selection_statuses"], "Selection status")}
    </section>
  </div>

  <h3>Representative Reasoning Records</h3>
  {_action_log_table(action_data["sample_action_records"])}

  <h2>Negotiation And Final Review</h2>
  <p>This section is reconstructed from ranked decisions and outcome metrics. It is not a real recorded multi-agent negotiation transcript. The corrected backend must persist explicit challenge/response turns before final executive approval.</p>
  {_negotiation_table(report["negotiation_log"])}

  <h2>Memory Utilization</h2>
  <p>MongoDB memory was connected for all four scenarios. It provided direct ready memory {_e(memory["direct_memory_calls"])} times, cautionary memory {_e(memory["cautionary_memory_calls"])} times, and abstained or supplied no accepted example when similarity was weak.</p>
  <ul>
    <li>Memory method: {_e(memory["method"])}</li>
    <li>Memory guidance calls: {_e(memory["guidance_calls"])}</li>
    <li>Memory-connected cases: {_e(memory["connected_cases"])}</li>
  </ul>

  <h2>Evidence Limits</h2>
  <ul>{evidence}</ul>

  <h2>Artifact Sources</h2>
  <ul>
    <li>Expanded memory benchmark: <code>{_e(report["artifacts"]["expanded_report"])}</code></li>
    <li>No-memory baseline benchmark: <code>{_e(report["artifacts"]["baseline_report"])}</code></li>
    <li>JSON support artifact: <code>{_e(report["artifacts"]["json_report"])}</code></li>
  </ul>
</main>
</body>
</html>
"""


def build_report(baseline_path: Path, expanded_path: Path, output_root: Path) -> tuple[dict[str, Any], Path, Path]:
    baseline_report = _load_json(baseline_path)
    expanded_report = _load_json(expanded_path)
    baseline_summary = _summary(baseline_report)
    expanded_summary = _summary(expanded_report)
    baseline_cases = _cases_by_scenario(baseline_report)
    expanded_cases = _cases_by_scenario(expanded_report)
    action_data = _collect_action_data(expanded_report)
    total_action_records = sum(action_data["action_mix"].values())
    comparison = []
    for key, label, higher, unit in METRICS:
        baseline_value = _num(baseline_summary.get(key))
        expanded_value = _num(expanded_summary.get(key))
        comparison.append(
            {
                "metric": key,
                "label": label,
                "unit": unit,
                "higher_is_better": higher,
                "baseline": baseline_value,
                "expanded": expanded_value,
                "difference": expanded_value - baseline_value,
                "verdict": _metric_verdict(expanded_value, baseline_value, higher),
            }
        )

    memory_receipt = {
        "method": next(iter(expanded_summary.get("memory_methods", {"mongodb_text_search": 0}).keys()), "mongodb_text_search")
        if isinstance(expanded_summary.get("memory_methods"), dict)
        else "mongodb_text_search",
        "connected_cases": expanded_summary.get("memory_connected_cases", 0),
        "direct_memory_calls": expanded_summary.get("total_memory_calls", 0),
        "guidance_calls": expanded_summary.get("total_memory_guidance_calls", 0),
        "cautionary_memory_calls": expanded_summary.get("total_cautionary_memory_calls", 0),
        "statuses": expanded_summary.get("memory_statuses", {}),
    }
    collaboration_seed = {"memory_receipt": memory_receipt}
    collaboration_action_data = {**action_data, "total_action_records": total_action_records}
    corrective_smoke = _latest_corrective_smoke_artifact()

    output_dir = output_root / f"ranked-reasoning-expanded-memory-action-report-{_now_id()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "action-report.json"
    html_path = output_dir / "action-report.html"

    report: dict[str, Any] = {
        "title": "ParkPulse Corrected LLM Advantage Readiness Report",
        "created_at": datetime.now(UTC).isoformat(),
        "model": {
            "id": "ranked_reasoning_expanded_memory_v1",
            "description": "Gemini candidate ranking over limited hard-gated actions with MongoDB direct and cautionary memory context.",
            "release_basis": "Frozen one-day sim-time benchmark used as evidence of an incomplete ranked-reasoning baseline, not a release-ready operating model.",
        },
        "deployment_receipt": {
            "status": "deployment_package_generated",
            "status_note": "Corrected assessment: this report packages evidence from the ranked-memory benchmark, but it is not a live-park deployment approval. It does not prove physical dispatch, full policy/regulatory compliance, or real multi-agent negotiation.",
            "headline_metrics": {
                "baseline_average_satisfaction_delta": baseline_summary.get("average_satisfaction_delta"),
                "expanded_average_satisfaction_delta": expanded_summary.get("average_satisfaction_delta"),
                "expanded_average_wait_delta": expanded_summary.get("average_wait_delta"),
                "expanded_average_food_delta": expanded_summary.get("average_food_delta"),
                "expanded_average_eta_delta": expanded_summary.get("average_eta_delta"),
                "expanded_projected_week_cost_usd": expanded_summary.get("total_projected_week_cost_usd"),
                "expanded_average_policy_score": expanded_summary.get("average_policy_score"),
            },
        },
        "executive_decision": {
            "decision": "NO_GO_FOR_LIVE_PILOT_EVIDENCE_ONLY",
            "status": "NO GO",
            "summary": "Do not claim the ranked reasoning + expanded memory model is the corrected LLM operating model. It improved satisfaction and wait metrics, but it skipped real multi-agent negotiation and full policy/regulatory judging, and it regressed food backlog and ETA.",
            "conditions": [
                "Treat the existing benchmark as a ranked-reasoning baseline, not as a release candidate.",
                "Wire the ranked model through the backend role-agent negotiation layer before any live-pilot claim.",
                "Add a full policy/regulatory judge that cites policy refs, required approvals, blocked authorities, and human-review boundaries per decision.",
                "Persist a signed negotiation and executive-decision receipt for every action.",
                "Rerun the frozen benchmark and compare against the current expanded-memory result before promoting any model.",
            ],
        },
        "llm_advantage_audit": {
            "summary": "The LLM advantage was only partially exercised. The benchmark used Gemini to rank candidate IDs and explain local tradeoffs, but did not use LLMs for the higher-value work: interpreting messy multi-party inputs, negotiating department conflicts, citing full policy/regulatory constraints, or producing an executive-grade final decision trace.",
            "capabilities": [
                {
                    "capability": "Messy input interpretation",
                    "current_evidence": "Timelapse used structured simulation digests, not unstructured operator/guest/staff/vendor notes.",
                    "verdict": "incomplete",
                    "correction": "Route noisy live-feed and operator text through Scan/React/Proact agents before ranking actions.",
                },
                {
                    "capability": "Multi-agent negotiation",
                    "current_evidence": "Report negotiation is reconstructed from metrics; no challenge/response transcript exists in gemini-operation-calls.jsonl.",
                    "verdict": "missing",
                    "correction": "Call the backend role-agent proposal layer and persist negotiation_rounds, negotiation_turns, conflicts, and executive_tradeoff per decision.",
                },
                {
                    "capability": "Full policy/regulatory reasoning",
                    "current_evidence": "Policy score covers limited hard gates, not full policy-book retrieval, citations, labor/safety/privacy/accessibility/emergency authority, or regulatory compliance.",
                    "verdict": "missing",
                    "correction": "Add a policy/regulation judge after ranking and before execution; require policy refs, blocked authorities, human-review gates, and approval owners.",
                },
                {
                    "capability": "Executive decision quality",
                    "current_evidence": "The selected action is a single ranked candidate; release decision is made post hoc in the report.",
                    "verdict": "incomplete",
                    "correction": "Executive bridge must compare agent positions, risk objections, metric tradeoffs, and policy findings before the action is approved.",
                },
                {
                    "capability": "Learning memory",
                    "current_evidence": "MongoDB memory influenced rankings, but the timelapse result did not write a full negotiation/eval/executive receipt back into memory.",
                    "verdict": "partial",
                    "correction": "Write the complete final receipt to MongoDB: inputs, agent positions, policy findings, selected/rejected options, outcome deltas, and human verdict.",
                },
            ],
            "corrective_path": [
                {
                    "step": "1. Interpret messy state",
                    "backend_owner": "scan/react/proact agents",
                    "trace_artifact": "signal_trace",
                    "acceptance_test": "Each decision cites live feed IDs or operator text spans, not only structured sim digests.",
                },
                {
                    "step": "2. Generate department proposals",
                    "backend_owner": "park_multi_agent.build_role_agent_proposals",
                    "trace_artifact": "role_agent_proposals.proposals",
                    "acceptance_test": "Ride, food, staffing, guest experience, safety, finance, and executive positions are present.",
                },
                {
                    "step": "3. Negotiate conflicts",
                    "backend_owner": "park_multi_agent._build_live_feed_negotiation_rounds",
                    "trace_artifact": "negotiation_rounds",
                    "acceptance_test": "At least one cross-department challenge and one concession/resolution are recorded for conflicted cases.",
                },
                {
                    "step": "4. Judge policy/regulation",
                    "backend_owner": "policy/regulation judge",
                    "trace_artifact": "policy_regulation_judgment",
                    "acceptance_test": "Every action has policy refs, allowed/review_required/blocked status, approval owner, and blocked authority list.",
                },
                {
                    "step": "5. Executive final answer",
                    "backend_owner": "decision_bridge_agent",
                    "trace_artifact": "executive_tradeoff",
                    "acceptance_test": "Final answer explains why the selected action won over rejected alternatives and what conditions apply.",
                },
                {
                    "step": "6. Receipt and learning write",
                    "backend_owner": "delivery/eval/memory agents",
                    "trace_artifact": "unified_receipt + memory_write",
                    "acceptance_test": "MongoDB stores action reasoning, negotiation, policy judgment, outcome deltas, and final verdict.",
                },
            ],
        },
        "corrective_implementation": {
            "status": "implemented_for_future_timelapse_runs_not_retroactive_to_legacy_benchmark",
            "runner": str((REPO_ROOT / "scripts" / "run_one_day_timelapse_cost_probe.py").resolve()),
            "new_trace_fields": ["policy_regulation_judgment", "negotiation_trace"],
            "verification": corrective_smoke,
            "important_limit": "The original expanded-memory benchmark artifacts were not rewritten. Rerun the frozen benchmark after this patch to compare the corrected model against the old ranked-memory baseline.",
        },
        "baseline_comparison": comparison,
        "scenario_comparison": {
            "baseline_cases": baseline_cases,
            "expanded_cases": expanded_cases,
        },
        "action_recording": {
            **collaboration_action_data,
        },
        "negotiation_log": _negotiation_log(expanded_cases, baseline_cases),
        "memory_receipt": memory_receipt,
        "multi_agent_collaboration": _build_multi_agent_collaboration(collaboration_seed, collaboration_action_data),
        "evidence_limits": [
            "The run is one week of simulated park time represented by the existing one-day sim-time benchmark artifacts, not seven new physical operating days.",
            "The source data is frozen simulation output; no external guest, worker, ride, food, or equipment system was dispatched by this renderer.",
            "The model's strongest measured result is guest-flow optimization, but that is not enough to prove LLM operating advantage.",
            "The run did not execute the backend multi-agent negotiation layer; negotiation in this report is reconstructed.",
            "The run did not execute a full policy/regulatory compliance judge; the policy score reflects limited hard gates only.",
            "Food-service recovery needs a stricter release gate before any live-pilot claim.",
            "The no-memory baseline is a ranked Gemini control without MongoDB memory context, not a no-action park baseline.",
        ],
        "artifacts": {
            "baseline_report": str(baseline_path.resolve()),
            "expanded_report": str(expanded_path.resolve()),
            "html_report": str(html_path.resolve()),
            "json_report": str(json_path.resolve()),
        },
    }

    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    html_path.write_text(_render_html(report), encoding="utf-8")
    return report, html_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--expanded-report", type=Path, default=DEFAULT_EXPANDED_REPORT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, html_path, json_path = build_report(
        baseline_path=args.baseline_report,
        expanded_path=args.expanded_report,
        output_root=args.output_root,
    )
    print(json.dumps({"status": "ok", "html": str(html_path), "json": str(json_path), "decision": report["executive_decision"]["decision"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
