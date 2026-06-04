#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
QA_DIR = REPO_ROOT / "output" / "qa"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _badge(value: Any, *, kind: str = "neutral") -> str:
    return f"<span class='badge {kind}'>{_e(value)}</span>"


def _metric(label: str, value: Any, note: str, kind: str = "neutral") -> str:
    return (
        f"<section class='metric {kind}'>"
        f"<span>{_e(label)}</span><strong>{_e(value)}</strong><small>{_e(note)}</small>"
        f"</section>"
    )


def _proposal_rows(smoke: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = smoke.get("role_agent_proposals", {})
    rows = proposals.get("proposals", []) if isinstance(proposals, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _executor_by_agent(smoke: dict[str, Any]) -> dict[str, dict[str, Any]]:
    executor = smoke.get("tool_executor_live_test", {})
    receipts = executor.get("receipts", []) if isinstance(executor, dict) else []
    return {str(row.get("agent")): row for row in receipts if isinstance(row, dict) and row.get("agent")}


def _delivery_by_department(smoke: dict[str, Any]) -> dict[str, dict[str, Any]]:
    delivery = smoke.get("live_feed_receiver_delivery", {})
    receipts = delivery.get("receipts", []) if isinstance(delivery, dict) else []
    return {str(row.get("department")): row for row in receipts if isinstance(row, dict) and row.get("department")}


def _status_kind(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"passed", "pass", "complete", "recorded", "proven_controlled", "delivered_and_acknowledged", "executed", "executed_controlled", "acknowledged"}:
        return "ok"
    if "hold" in text or "approval" in text or "review" in text or "requires" in text or "blocked" in text:
        return "warn"
    if "fail" in text or "error" in text or "missing" in text:
        return "bad"
    return "neutral"


def _render_department_table(smoke: dict[str, Any]) -> str:
    executor = _executor_by_agent(smoke)
    delivery = _delivery_by_department(smoke)
    rows = []
    for proposal in _proposal_rows(smoke):
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
        receipt = executor.get(str(proposal.get("agent_id")), {})
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        delivery_receipt = delivery.get(str(proposal.get("department")), {})
        grounding = proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}
        event_count = len(grounding.get("event_ids", [])) if isinstance(grounding.get("event_ids"), list) else 0
        rows.append(
            "<tr>"
            f"<td>{_e(proposal.get('department'))}</td>"
            f"<td>{_e(proposal.get('agent_id'))}</td>"
            f"<td>{_e(envelope.get('requested_tool') or proposal.get('requested_tool'))}</td>"
            f"<td>{_badge(envelope.get('policy_check') or proposal.get('policy_check'), kind=_status_kind(policy.get('status')))}</td>"
            f"<td>{_badge(policy.get('status'), kind=_status_kind(policy.get('status')))}</td>"
            f"<td>{_badge(result.get('status') or 'held', kind=_status_kind(result.get('status') or 'held'))}</td>"
            f"<td>{_badge(delivery_receipt.get('status') or 'not_dispatched', kind=_status_kind(delivery_receipt.get('status') or 'not_dispatched'))}</td>"
            f"<td>{event_count}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_delivery_table(smoke: dict[str, Any]) -> str:
    delivery = smoke.get("live_feed_receiver_delivery", {})
    receipts = delivery.get("receipts", []) if isinstance(delivery, dict) else []
    rows = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_e(receipt.get('department'))}</td>"
            f"<td>{_e(receipt.get('source_tool'))}</td>"
            f"<td>{_e(receipt.get('receiver') or 'policy hold')}</td>"
            f"<td>{_badge(receipt.get('status'), kind=_status_kind(receipt.get('status')))}</td>"
            f"<td>{_e(receipt.get('dispatch_id'))}</td>"
            f"<td>{_e(receipt.get('acknowledged_by'))}</td>"
            f"<td>{_e(receipt.get('material_state_mutation'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_measurement_table(smoke: dict[str, Any]) -> str:
    measurement = smoke.get("live_feed_outcome_measurement", {})
    rows = measurement.get("measurement_rows", []) if isinstance(measurement, dict) else []
    rendered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics", []) if isinstance(row.get("metrics"), list) else []
        metric_text = "; ".join(
            f"{item.get('metric')}: {item.get('before')} -> {item.get('after')} ({item.get('impact')})"
            for item in metrics
            if isinstance(item, dict)
        )
        rendered.append(
            "<tr>"
            f"<td>{_e(row.get('source'))}</td>"
            f"<td>{_e(row.get('before_event_id'))}</td>"
            f"<td>{_e(row.get('after_event_id'))}</td>"
            f"<td>{_badge('captured' if row.get('post_action_snapshot_captured') else 'missing', kind='ok' if row.get('post_action_snapshot_captured') else 'bad')}</td>"
            f"<td>{_e(metric_text)}</td>"
            "</tr>"
        )
    return "\n".join(rendered)


def _render_evidence(smoke: dict[str, Any]) -> str:
    live_case = smoke.get("live_feed_case", {})
    evidence = live_case.get("evidence", []) if isinstance(live_case, dict) else []
    rows = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<li>"
            f"<b>{_e(item.get('source'))}</b>"
            f"<span>{_e(item.get('signal_type'))}</span>"
            f"<small>{_e(item.get('event_id'))} | confidence {_e(item.get('confidence'))} | age {_e(item.get('age_seconds'))}s</small>"
            f"<p>{_e(item.get('summary'))}</p>"
            "</li>"
        )
    return "\n".join(rows)


def _render_negotiation_rounds(smoke: dict[str, Any]) -> str:
    proposals = smoke.get("role_agent_proposals", {}) if isinstance(smoke.get("role_agent_proposals"), dict) else {}
    rounds = proposals.get("negotiation_rounds", []) if isinstance(proposals.get("negotiation_rounds"), list) else []
    rows = []
    for item in rounds:
        if not isinstance(item, dict):
            continue
        detail = ""
        if isinstance(item.get("claims"), list):
            detail = f"{len(item.get('claims', []))} local positions"
        elif isinstance(item.get("challenges"), list):
            detail = "; ".join(str(row.get("conflict")) for row in item.get("challenges", [])[:2] if isinstance(row, dict))
        elif isinstance(item.get("decisions"), list):
            detail = f"{len(item.get('decisions', []))} policy/eval decisions with next owners"
        elif isinstance(item.get("accepted"), list) or isinstance(item.get("blocked"), list):
            detail = f"{len(item.get('accepted', []))} memory accepted, {len(item.get('blocked', []))} blocked, {len(item.get('weak_context', []))} context only"
        elif isinstance(item.get("tradeoff_matrix"), list):
            detail = f"{len(item.get('selected', []))} selected, {len(item.get('rejected_or_held', []))} rejected or held"
        rows.append(
            "<tr>"
            f"<td>{_e(item.get('round'))}</td>"
            f"<td>{_e(item.get('name'))}</td>"
            f"<td>{_e(item.get('decision') or item.get('resolution') or detail)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_tradeoff_matrix(smoke: dict[str, Any]) -> str:
    proposals = smoke.get("role_agent_proposals", {}) if isinstance(smoke.get("role_agent_proposals"), dict) else {}
    matrix = proposals.get("tradeoff_matrix", []) if isinstance(proposals.get("tradeoff_matrix"), list) else []
    rows = []
    for row in matrix:
        if not isinstance(row, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_e(row.get('department'))}</td>"
            f"<td>{_e(row.get('requested_tool'))}</td>"
            f"<td>{_e(row.get('safety_risk_weight'))}</td>"
            f"<td>{_e(row.get('guest_value'))}</td>"
            f"<td>{_e(row.get('revenue_value'))}</td>"
            f"<td>{_e(row.get('labor_value'))}</td>"
            f"<td>{_e(row.get('profile_counterfactual_action'))} / {_e(row.get('profile_counterfactual_score'))}</td>"
            f"<td>{_badge(row.get('policy_status'), kind=_status_kind(row.get('policy_status')))}</td>"
            f"<td>{_badge(row.get('verdict'), kind=_status_kind(row.get('verdict')))}</td>"
            f"<td>{_e(row.get('rationale'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_memory_delta_table(smoke: dict[str, Any]) -> str:
    proposals = smoke.get("role_agent_proposals", {}) if isinstance(smoke.get("role_agent_proposals"), dict) else {}
    deltas = proposals.get("memory_decision_deltas", []) if isinstance(proposals.get("memory_decision_deltas"), list) else []
    rows = []
    for row in deltas:
        if not isinstance(row, dict):
            continue
        delta = row.get("decision_delta", {}) if isinstance(row.get("decision_delta"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{_e(row.get('department'))}</td>"
            f"<td>{_e(row.get('requested_tool'))}</td>"
            f"<td>{_e(row.get('prior_outcome_id'))}</td>"
            f"<td>{_badge(delta.get('effect') or row.get('status'), kind=_status_kind(delta.get('effect') or row.get('status')))}</td>"
            f"<td>{_e(delta.get('before'))}</td>"
            f"<td>{_e(delta.get('after'))}</td>"
            f"<td>{_e(delta.get('decision_boundary'))}</td>"
            "</tr>"
        )
    if not rows:
        return "<tr><td colspan='7'>No prior memory was available for this run, so no memory decision deltas were applied.</td></tr>"
    return "\n".join(rows)


def _render_held_disposition_table(smoke: dict[str, Any]) -> str:
    executor = smoke.get("tool_executor_live_test", {}) if isinstance(smoke.get("tool_executor_live_test"), dict) else {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    rows = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        if result.get("status") != "held":
            continue
        disposition = receipt.get("action_disposition", {}) if isinstance(receipt.get("action_disposition"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{_e(receipt.get('department'))}</td>"
            f"<td>{_e(receipt.get('source_tool'))}</td>"
            f"<td>{_badge(disposition.get('decision'), kind=_status_kind(disposition.get('decision')))}</td>"
            f"<td>{_e(disposition.get('next_owner'))}</td>"
            f"<td>{_e(disposition.get('exit_condition'))}</td>"
            f"<td>{_e(disposition.get('fallback'))}</td>"
            f"<td>{_e(disposition.get('why_not_undecided'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_follow_through_table(smoke: dict[str, Any]) -> str:
    follow = smoke.get("hard_decision_follow_through", {}) if isinstance(smoke.get("hard_decision_follow_through"), dict) else {}
    tasks = follow.get("tasks", []) if isinstance(follow.get("tasks"), list) else []
    rows = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_e(task.get('task_id'))}</td>"
            f"<td>{_e(task.get('department'))}</td>"
            f"<td>{_e(task.get('source_tool'))}</td>"
            f"<td>{_badge(task.get('status'), kind=_status_kind(task.get('status')))}</td>"
            f"<td>{_e(task.get('next_owner'))}</td>"
            f"<td>{_e(task.get('exit_condition'))}</td>"
            f"<td>{_e(task.get('active_follow_up_required'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_profile_context_table(smoke: dict[str, Any]) -> str:
    rows = []
    for proposal in _proposal_rows(smoke):
        context = proposal.get("park_profile_context", {}) if isinstance(proposal.get("park_profile_context"), dict) else {}
        if not context:
            continue
        zones = context.get("relevant_zones", []) if isinstance(context.get("relevant_zones"), list) else []
        locations = context.get("relevant_locations", []) if isinstance(context.get("relevant_locations"), list) else []
        constraints = context.get("profile_constraints", []) if isinstance(context.get("profile_constraints"), list) else []
        reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
        counterfactual = reasoning.get("profile_counterfactual_summary", {}) if isinstance(reasoning.get("profile_counterfactual_summary"), dict) else {}
        zone_text = ", ".join(str(zone.get("name") or zone.get("id")) for zone in zones[:3] if isinstance(zone, dict))
        location_text = ", ".join(str(item.get("name")) for item in locations[:3] if isinstance(item, dict))
        rows.append(
            "<tr>"
            f"<td>{_e(proposal.get('department'))}</td>"
            f"<td>{_badge(context.get('status'), kind=_status_kind(context.get('status')))}</td>"
            f"<td>{_e(zone_text)}</td>"
            f"<td>{_e(location_text)}</td>"
            f"<td>{_e('; '.join(str(item) for item in constraints[:3]))}</td>"
            f"<td>{_e(counterfactual.get('best_profile_adjusted_action'))} / {_e(counterfactual.get('best_profile_adjusted_score'))}</td>"
            f"<td>{_e(context.get('reasoning_effect'))}</td>"
            f"<td>{_e(context.get('precedence'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_report(smoke_path: Path, closure_path: Path, output_path: Path) -> Path:
    smoke = _read_json(smoke_path)
    closure = _read_json(closure_path)
    summary = smoke.get("summary", {}) if isinstance(smoke.get("summary"), dict) else {}
    executor = smoke.get("tool_executor_live_test", {}) if isinstance(smoke.get("tool_executor_live_test"), dict) else {}
    hard_follow = smoke.get("hard_decision_follow_through", {}) if isinstance(smoke.get("hard_decision_follow_through"), dict) else {}
    delivery = smoke.get("live_feed_receiver_delivery", {}) if isinstance(smoke.get("live_feed_receiver_delivery"), dict) else {}
    measurement = smoke.get("live_feed_outcome_measurement", {}) if isinstance(smoke.get("live_feed_outcome_measurement"), dict) else {}
    outcome_memory = smoke.get("live_feed_outcome_memory", {}) if isinstance(smoke.get("live_feed_outcome_memory"), dict) else {}
    closure_summary = closure.get("summary", {}) if isinstance(closure.get("summary"), dict) else {}
    graph = smoke.get("live_feed_cooperation", {}) if isinstance(smoke.get("live_feed_cooperation"), dict) else {}
    proposals = smoke.get("role_agent_proposals", {}) if isinstance(smoke.get("role_agent_proposals"), dict) else {}
    tradeoff = proposals.get("executive_tradeoff", {}) if isinstance(proposals.get("executive_tradeoff"), dict) else {}
    park_profile = smoke.get("park_profile_summary", {}) if isinstance(smoke.get("park_profile_summary"), dict) else {}
    active_departments = summary.get("active_departments", []) if isinstance(summary.get("active_departments"), list) else []
    generated_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    reward_count = int(closure_summary.get("reward_example_count") or 0)
    reward_title = "Reward candidate is available." if reward_count else "Reward is still blocked by post-action measurement."
    reward_note = (
        "Receiver delivery and post-action live-feed measurements satisfied the offline reward-candidate contract."
        if reward_count
        else "Receiver delivery is proven, but the post-action measurement contract did not pass."
    )
    reward_metric_note = "offline material only; training not started" if reward_count else "kept at zero until measured outcomes"
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Live-Feed Agent Report</title>
<style>
:root {{ color-scheme: dark; --bg:#091116; --panel:#101b22; --panel2:#0d171d; --line:#263740; --text:#eef8fb; --muted:#9bacb5; --ok:#76e6a6; --warn:#ffd166; --bad:#ff7b88; --blue:#8fc5ff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing:0; }}
main {{ width:min(1480px, calc(100vw - 32px)); margin:0 auto; padding:28px 0 44px; }}
.hero {{ display:grid; grid-template-columns:1.1fr .9fr; gap:16px; align-items:stretch; }}
.panel, .metric {{ border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:18px; }}
.hero-title {{ margin:0; max-width:980px; font-size:clamp(32px, 5vw, 70px); line-height:1; font-weight:950; }}
.kicker, .metric span {{ display:block; color:var(--blue); font-size:11px; text-transform:uppercase; font-weight:900; letter-spacing:.05em; }}
.subhead, small, p {{ color:var(--muted); line-height:1.55; }}
.grid {{ display:grid; gap:14px; margin-top:16px; }}
.metrics {{ grid-template-columns:repeat(5, minmax(0, 1fr)); }}
.two {{ grid-template-columns:1fr 1fr; }}
.metric strong {{ display:block; margin-top:8px; font-size:28px; line-height:1.1; overflow-wrap:anywhere; }}
.metric.ok {{ border-left:5px solid var(--ok); }} .metric.warn {{ border-left:5px solid var(--warn); }} .metric.bad {{ border-left:5px solid var(--bad); }}
.section-title {{ margin:6px 0 12px; font-size:20px; }}
.pills {{ display:flex; flex-wrap:wrap; gap:8px; }}
.pill, .badge {{ display:inline-block; border-radius:999px; padding:5px 8px; font-size:12px; font-weight:800; }}
.pill {{ background:#152b38; color:#bdefff; }}
.badge.ok {{ background:rgba(118,230,166,.15); color:var(--ok); }} .badge.warn {{ background:rgba(255,209,102,.14); color:var(--warn); }} .badge.bad {{ background:rgba(255,123,136,.14); color:var(--bad); }} .badge.neutral {{ background:#18242c; color:#c5d2d9; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ color:var(--muted); background:var(--panel2); font-size:11px; text-transform:uppercase; letter-spacing:.05em; }}
.flow {{ display:grid; grid-template-columns:repeat(7, minmax(0, 1fr)); gap:10px; }}
.step {{ min-height:118px; background:var(--panel2); border:1px solid var(--line); border-radius:8px; padding:12px; }}
.step b {{ display:block; margin-bottom:8px; }}
.evidence {{ list-style:none; padding:0; margin:0; display:grid; gap:10px; }}
.evidence li {{ border:1px solid var(--line); background:var(--panel2); border-radius:8px; padding:12px; }}
.evidence b {{ margin-right:8px; }} .evidence span, .evidence small {{ color:var(--muted); }}
.callout {{ border-left:5px solid var(--warn); }}
.code {{ font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap:anywhere; }}
footer {{ margin-top:20px; color:var(--muted); font-size:12px; }}
@media (max-width:1100px) {{ .hero, .metrics, .two, .flow {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main>
<section class="hero">
<div class="panel">
<div class="kicker">Generated {_e(generated_at)} from live-feed artifacts</div>
<h1 class="hero-title">ParkPulse multi-agent loop is now closed through measured outcome memory.</h1>
<p class="subhead">This report is generated from the live smoke JSON and training closure manifest. It shows department cooperation, policy-gated tool use, controlled executor receipts, receiver acknowledgements, post-action live-feed measurements, Mongo outcome memory, and offline next-term training material.</p>
</div>
<div class="panel callout">
<div class="kicker">Reward boundary</div>
<h2 class="section-title">{_e(reward_title)}</h2>
<p>{_e(reward_note)} Reward example count is {_e(closure_summary.get('reward_example_count'))}; training and promotion remain disabled.</p>
</div>
</section>
<section class="grid metrics">
{_metric("Smoke", summary.get("status"), "live-feed smoke gate", _status_kind(summary.get("status")))}
{_metric("Departments", len(active_departments), "active enterprise agents")}
{_metric("Proposals", summary.get("proposal_count"), "department tool proposals")}
{_metric("Deep reasoning", f"{summary.get('deep_reasoning_proposal_count')} / {summary.get('proposal_count')}", "diagnosis, options, forecast, failure modes")}
{_metric("Negotiation", summary.get("negotiation_round_count"), "rounds with challenge and resolution")}
{_metric("Tradeoff matrix", f"{summary.get('tradeoff_matrix_count')} / {summary.get('proposal_count')}", "Executive scoring rows")}
{_metric("Memory deltas", summary.get("memory_decision_delta_count"), "prior outcome effects")}
{_metric("Dispositions", f"{summary.get('action_disposition_count')} / {summary.get('proposal_count')}", "owner and exit condition")}
{_metric("Profile context", f"{summary.get('profile_context_proposal_count')} / {summary.get('proposal_count')}", park_profile.get("venue_name") or "park profile")}
{_metric("Follow-through", f"{hard_follow.get('task_count')} / {hard_follow.get('active_follow_up_count')}", "held tasks routed / active", _status_kind(hard_follow.get("status")))}
{_metric("Executed / Held", f"{executor.get('executed_count')} / {executor.get('held_count')}", "controlled executor decisions", "ok")}
{_metric("Receiver proof", delivery.get("status"), f"{delivery.get('acknowledged_count')} acknowledgements", _status_kind(delivery.get("status")))}
{_metric("Measurement", measurement.get("status"), f"confidence {measurement.get('attribution_confidence')}", _status_kind(measurement.get("status")))}
{_metric("Mongo outcome", outcome_memory.get("status"), outcome_memory.get("outcome_id"), _status_kind(outcome_memory.get("status")))}
{_metric("Training examples", closure_summary.get("example_count"), f"{closure_summary.get('supervised_example_count')} supervised, {closure_summary.get('eval_example_count')} eval")}
{_metric("Reward examples", closure_summary.get("reward_example_count"), reward_metric_note, "ok" if reward_count else "warn")}
{_metric("Graph", f"{len(graph.get('nodes', []))} nodes / {len(graph.get('edges', []))} edges", "cooperation graph")}
{_metric("Guest sends", delivery.get("public_guest_messages_sent"), "controlled run sent no public guest messages")}
</section>
<section class="panel grid">
<div class="kicker">Loop</div>
<h2 class="section-title">Closed Case Flow</h2>
<div class="flow">
<div class="step"><b>1. Observe</b><p>Live feed health produced {_e(summary.get('ready_feed_count'))} ready feeds and {_e(summary.get('persisted_event_count'))} persisted events.</p></div>
<div class="step"><b>2. Reason</b><p>{_e(summary.get('deep_reasoning_proposal_count'))} proposals diagnosed local state, compared candidate actions, forecasted impact, and named failure modes.</p></div>
<div class="step"><b>3. Judge</b><p>{_e(summary.get('concrete_policy_count'))} concrete policy checks, with sensitive actions held.</p></div>
<div class="step"><b>4. Tradeoff</b><p>Executive decision: {_e(tradeoff.get('decision'))}.</p></div>
<div class="step"><b>5. Execute</b><p>Only food, labor, and marketing controlled internal actions executed.</p></div>
<div class="step"><b>6. Deliver</b><p>{_e(delivery.get('delivered_count'))} dispatches delivered and {_e(delivery.get('acknowledged_count'))} acknowledged.</p></div>
<div class="step"><b>7. Measure</b><p>Post-action live-feed measurement status: {_e(measurement.get('status'))}, confidence {_e(measurement.get('attribution_confidence'))}.</p></div>
<div class="step"><b>8. Learn</b><p>Mongo outcome memory plus supervised/eval/reward candidate material created offline.</p></div>
</div>
</section>
<section class="grid two">
<div class="panel">
<div class="kicker">Departments</div>
<h2 class="section-title">Active Agents</h2>
<div class="pills">{"".join(f"<span class='pill'>{_e(dept)}</span>" for dept in active_departments)}</div>
</div>
<div class="panel">
<div class="kicker">Executive tradeoff</div>
<h2 class="section-title">Approved vs Held</h2>
<p><b>Approved:</b> {_e(', '.join(tradeoff.get('approved_departments', []) if isinstance(tradeoff.get('approved_departments'), list) else []))}</p>
<p><b>Held:</b> {_e(', '.join(tradeoff.get('held_departments', []) if isinstance(tradeoff.get('held_departments'), list) else []))}</p>
<p>{_e(tradeoff.get('reason'))}</p>
</div>
</section>
<section class="panel">
<div class="kicker">Park profile context</div>
<h2 class="section-title">Department Profile Slices</h2>
<p><b>Profile:</b> {_e(park_profile.get('venue_name'))} | <b>Version:</b> <span class="code">{_e(park_profile.get('profile_version'))}</span> | <b>Precedence:</b> {_e(park_profile.get('precedence'))}</p>
<table><thead><tr><th>Department</th><th>Status</th><th>Relevant zones</th><th>Relevant locations</th><th>Profile constraints</th><th>Best profile-adjusted candidate</th><th>Reasoning effect</th><th>Precedence</th></tr></thead><tbody>
{_render_profile_context_table(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Negotiation</div>
<h2 class="section-title">Agent Challenge and Resolution Rounds</h2>
<table><thead><tr><th>Round</th><th>Name</th><th>What changed</th></tr></thead><tbody>
{_render_negotiation_rounds(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Executive reasoning</div>
<h2 class="section-title">Tradeoff Matrix</h2>
<table><thead><tr><th>Department</th><th>Tool</th><th>Safety risk</th><th>Guest</th><th>Revenue</th><th>Labor</th><th>Profile counterfactual</th><th>Policy</th><th>Verdict</th><th>Rationale</th></tr></thead><tbody>
{_render_tradeoff_matrix(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Memory influence</div>
<h2 class="section-title">Decision Deltas from Prior Outcomes</h2>
<table><thead><tr><th>Department</th><th>Tool</th><th>Prior outcome</th><th>Effect</th><th>Before</th><th>After</th><th>Boundary</th></tr></thead><tbody>
{_render_memory_delta_table(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Hard decisions</div>
<h2 class="section-title">Held Actions Are Disposed, Not Left Undecided</h2>
<table><thead><tr><th>Department</th><th>Tool</th><th>Decision</th><th>Next owner</th><th>Exit condition</th><th>Fallback</th><th>Why not undecided</th></tr></thead><tbody>
{_render_held_disposition_table(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Follow-through</div>
<h2 class="section-title">Routed Review Tasks for Held Actions</h2>
<table><thead><tr><th>Task</th><th>Department</th><th>Tool</th><th>Status</th><th>Next owner</th><th>Exit condition</th><th>Active</th></tr></thead><tbody>
{_render_follow_through_table(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Judge and executor</div>
<h2 class="section-title">Department Tool Decisions</h2>
<table><thead><tr><th>Department</th><th>Agent</th><th>Requested tool</th><th>Policy check</th><th>Policy status</th><th>Executor result</th><th>Delivery</th><th>Events</th></tr></thead><tbody>
{_render_department_table(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Delivery proof</div>
<h2 class="section-title">Receiver Acknowledgements</h2>
<table><thead><tr><th>Department</th><th>Tool</th><th>Receiver</th><th>Status</th><th>Dispatch id</th><th>Acknowledged by</th><th>Material mutation</th></tr></thead><tbody>
{_render_delivery_table(smoke)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Post-action measurement</div>
<h2 class="section-title">Live State Attribution</h2>
<table><thead><tr><th>Source</th><th>Before event</th><th>After event</th><th>Snapshot</th><th>Metric deltas</th></tr></thead><tbody>
{_render_measurement_table(smoke)}
</tbody></table>
</section>
<section class="grid two">
<div class="panel">
<div class="kicker">Live evidence</div>
<h2 class="section-title">Feed Signals Used</h2>
<ul class="evidence">
{_render_evidence(smoke)}
</ul>
</div>
<div class="panel">
<div class="kicker">Mongo and training</div>
<h2 class="section-title">Material for Next-Term Training</h2>
<p><b>Outcome memory:</b> {_e(outcome_memory.get('mongo_collection'))} / {_e(outcome_memory.get('outcome_id'))}</p>
<p><b>Closure manifest:</b> <span class="code">{_e(closure.get('artifacts', {}).get('manifest') if isinstance(closure.get('artifacts'), dict) else '')}</span></p>
<p><b>Examples:</b> {_e(closure_summary.get('example_count'))} total, {_e(closure_summary.get('supervised_example_count'))} supervised, {_e(closure_summary.get('eval_example_count'))} eval, {_e(closure_summary.get('reward_example_count'))} reward.</p>
<p><b>Measurement:</b> {_e(measurement.get('measurement_id'))}, confidence {_e(measurement.get('attribution_confidence'))}, reward value {_e(measurement.get('reward_value'))}</p>
<p><b>Training boundary:</b> {_e(closure.get('training_rule'))}</p>
</div>
</section>
<footer>
Source JSON: <span class="code">{_e(smoke_path)}</span><br />
Closure JSON: <span class="code">{_e(closure_path)}</span>
</footer>
</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def main() -> int:
    output = render_report(
        QA_DIR / "live-feed-agent-smoke.json",
        QA_DIR / "live-feed-training-closure.json",
        QA_DIR / "live-feed-agent-report.html",
    )
    print(json.dumps({"status": "rendered", "output_html": str(output)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
