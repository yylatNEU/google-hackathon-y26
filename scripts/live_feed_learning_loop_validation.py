#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import html
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

QA_DIR = REPO_ROOT / "output" / "qa"
RUN_DIR = QA_DIR / "live-feed-learning-loop"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _copy_if_exists(src: Path, dest: Path) -> str | None:
    if not src.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return str(dest)


def _memory_snapshot(label: str) -> dict[str, Any]:
    from mongo_memory import get_operational_memory_dashboard

    dashboard = get_operational_memory_dashboard("live feed controlled executor measured outcome reward")
    latest_outcomes = dashboard.get("latest_outcomes", []) if isinstance(dashboard.get("latest_outcomes"), list) else []
    latest_learnings = dashboard.get("latest_learnings", []) if isinstance(dashboard.get("latest_learnings"), list) else []
    collections = dashboard.get("collections", []) if isinstance(dashboard.get("collections"), list) else []
    collection_counts = {
        str(row.get("name")): row.get("count")
        for row in collections
        if isinstance(row, dict) and row.get("name")
    }
    return {
        "label": label,
        "captured_at": _now_iso(),
        "status": dashboard.get("status"),
        "outcome_ids": [row.get("_id") for row in latest_outcomes if isinstance(row, dict) and row.get("_id")],
        "learning_ids": [row.get("_id") for row in latest_learnings if isinstance(row, dict) and row.get("_id")],
        "latest_outcomes": latest_outcomes[:5],
        "latest_learnings": latest_learnings[:5],
        "collection_counts": collection_counts,
        "dashboard_status": dashboard.get("status"),
    }


def _run_summary(smoke: dict[str, Any], closure: dict[str, Any], index: int, artifacts: dict[str, Any]) -> dict[str, Any]:
    summary = smoke.get("summary", {}) if isinstance(smoke.get("summary"), dict) else {}
    closure_summary = closure.get("summary", {}) if isinstance(closure.get("summary"), dict) else {}
    return {
        "index": index,
        "status": summary.get("status"),
        "run_status": summary.get("run_status"),
        "outcome_id": (summary.get("live_feed_outcome_memory", {}) if isinstance(summary.get("live_feed_outcome_memory"), dict) else {}).get("outcome_id"),
        "measurement_id": (summary.get("live_feed_outcome_measurement", {}) if isinstance(summary.get("live_feed_outcome_measurement"), dict) else {}).get("measurement_id"),
        "receiver_proof_id": (summary.get("live_feed_receiver_delivery", {}) if isinstance(summary.get("live_feed_receiver_delivery"), dict) else {}).get("proof_id"),
        "executed_count": (summary.get("tool_executor_live_test", {}) if isinstance(summary.get("tool_executor_live_test"), dict) else {}).get("executed_count"),
        "held_count": (summary.get("tool_executor_live_test", {}) if isinstance(summary.get("tool_executor_live_test"), dict) else {}).get("held_count"),
        "hard_follow_status": (summary.get("hard_decision_follow_through", {}) if isinstance(summary.get("hard_decision_follow_through"), dict) else {}).get("status"),
        "hard_follow_task_count": (summary.get("hard_decision_follow_through", {}) if isinstance(summary.get("hard_decision_follow_through"), dict) else {}).get("task_count"),
        "hard_follow_active_count": (summary.get("hard_decision_follow_through", {}) if isinstance(summary.get("hard_decision_follow_through"), dict) else {}).get("active_follow_up_count"),
        "hard_follow_unresolved_without_owner_count": (summary.get("hard_decision_follow_through", {}) if isinstance(summary.get("hard_decision_follow_through"), dict) else {}).get("unresolved_without_owner_count"),
        "proposal_count": summary.get("proposal_count"),
        "park_profile_context_status": summary.get("park_profile_context_status"),
        "profile_context_proposal_count": summary.get("profile_context_proposal_count"),
        "profile_precedence_count": summary.get("profile_precedence_count"),
        "profile_counterfactual_candidate_count": summary.get("profile_counterfactual_candidate_count"),
        "evidence_argument_count": summary.get("evidence_argument_count"),
        "disposition_evidence_argument_count": summary.get("disposition_evidence_argument_count"),
        "tradeoff_evidence_argument_count": summary.get("tradeoff_evidence_argument_count"),
        "follow_through_event_link_count": summary.get("follow_through_event_link_count"),
        "park_profile_version": (summary.get("park_profile_summary", {}) if isinstance(summary.get("park_profile_summary"), dict) else {}).get("profile_version"),
        "deep_reasoning_proposal_count": summary.get("deep_reasoning_proposal_count"),
        "candidate_action_count": summary.get("candidate_action_count"),
        "failure_mode_count": summary.get("failure_mode_count"),
        "action_disposition_count": summary.get("action_disposition_count"),
        "negotiation_round_count": summary.get("negotiation_round_count"),
        "tradeoff_matrix_count": summary.get("tradeoff_matrix_count"),
        "memory_decision_delta_count": summary.get("memory_decision_delta_count"),
        "measured_source_count": (summary.get("live_feed_outcome_measurement", {}) if isinstance(summary.get("live_feed_outcome_measurement"), dict) else {}).get("measured_source_count"),
        "attribution_confidence": closure_summary.get("outcome_measurement_attribution_confidence"),
        "reward_value": closure_summary.get("outcome_measurement_reward_value"),
        "closure_deep_reasoning_proposal_count": closure_summary.get("deep_reasoning_proposal_count"),
        "reward_example_count": closure_summary.get("reward_example_count"),
        "supervised_example_count": closure_summary.get("supervised_example_count"),
        "eval_example_count": closure_summary.get("eval_example_count"),
        "memory_prior_status": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("status"),
        "memory_prior_count": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("prior_count"),
        "memory_prior_outcome_ids": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("latest_outcome_ids", []),
        "memory_prior_applied_count": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("applied_count"),
        "memory_prior_applied_outcome_ids": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("applied_prior_outcome_ids", []),
        "memory_prior_weak_context_count": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("weak_context_count"),
        "memory_prior_blocked_count": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("blocked_count"),
        "memory_prior_accepted_departments": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("accepted_departments", []),
        "memory_prior_blocked_departments": (summary.get("live_feed_memory_priors", {}) if isinstance(summary.get("live_feed_memory_priors"), dict) else {}).get("blocked_departments", []),
        "uses_seed_data": smoke.get("uses_seed_data", False),
        "scripted_case": smoke.get("scripted_case", False),
        "artifacts": artifacts,
    }


async def run_learning_loop_validation(iterations: int = 2) -> dict[str, Any]:
    from scripts.live_feed_agent_smoke import main as smoke_main
    from scripts.live_feed_training_closure import close_live_feed_training_loop

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    before_memory = _memory_snapshot("before")
    runs: list[dict[str, Any]] = []
    for index in range(1, iterations + 1):
        smoke_status = await smoke_main()
        if smoke_status != 0:
            raise RuntimeError(f"live feed smoke failed on iteration {index}")
        smoke_source = QA_DIR / "live-feed-agent-smoke.json"
        smoke_copy = RUN_DIR / f"run-{index}-smoke.json"
        _copy_if_exists(smoke_source, smoke_copy)
        closure_dir = RUN_DIR / f"run-{index}-closure"
        closure = close_live_feed_training_loop(smoke_copy, closure_dir, record_ledger=True, reviewer="parkpulse-learning-loop-validation")
        smoke = _read_json(smoke_copy)
        artifacts = {
            "smoke_json": str(smoke_copy),
            "closure_manifest": str(closure_dir / "live-feed-training-closure.json"),
            "reward_jsonl": str(closure_dir / "live-feed-reward-examples.jsonl"),
            "supervised_jsonl": str(closure_dir / "live-feed-supervised-examples.jsonl"),
            "eval_jsonl": str(closure_dir / "live-feed-eval-examples.jsonl"),
            "reward_line_count": _line_count(closure_dir / "live-feed-reward-examples.jsonl"),
        }
        runs.append(_run_summary(smoke, closure, index, artifacts))
    after_memory = _memory_snapshot("after")
    run_outcome_ids = [row.get("outcome_id") for row in runs if row.get("outcome_id")]
    run_measurement_ids = [row.get("measurement_id") for row in runs if row.get("measurement_id")]
    after_outcome_ids = set(after_memory.get("outcome_ids", []))
    before_outcome_ids = set(before_memory.get("outcome_ids", []))
    new_dashboard_outcomes = sorted(after_outcome_ids - before_outcome_ids)
    prior_linkages = []
    selective_memory_checks = []
    for index, run in enumerate(runs):
        previous_outcomes = {str(row.get("outcome_id")) for row in runs[:index] if row.get("outcome_id")}
        used_priors = {str(item) for item in run.get("memory_prior_outcome_ids", []) if item}
        applied_priors = {str(item) for item in run.get("memory_prior_applied_outcome_ids", []) if item}
        matched = sorted(previous_outcomes & (used_priors | applied_priors))
        if index > 0:
            applied_count = int(run.get("memory_prior_applied_count") or 0)
            proposal_count = int(run.get("proposal_count") or 0)
            blocked_count = int(run.get("memory_prior_blocked_count") or 0)
            accepted_departments = set(run.get("memory_prior_accepted_departments", []) if isinstance(run.get("memory_prior_accepted_departments"), list) else [])
            expected_accepted = {"food_retail", "hr_labor", "marketing"}
            prior_linkages.append(
                {
                    "run_index": run.get("index"),
                    "previous_outcomes": sorted(previous_outcomes),
                    "retrieved_previous_outcomes": matched,
                    "status": "linked" if matched else "missing",
                }
            )
            selective_memory_checks.append(
                {
                    "run_index": run.get("index"),
                    "applied_count": applied_count,
                    "proposal_count": proposal_count,
                    "blocked_count": blocked_count,
                    "accepted_departments": sorted(accepted_departments),
                    "status": (
                        "selective"
                        if matched
                        and applied_count > 0
                        and applied_count < proposal_count
                        and blocked_count > 0
                        and accepted_departments <= expected_accepted
                        and expected_accepted <= accepted_departments
                        else "failed"
                    ),
                }
            )
    validation = {
        "status": "passed"
        if (
            len(runs) == iterations
            and all(row.get("status") == "passed" for row in runs)
            and all(int(row.get("deep_reasoning_proposal_count") or 0) == int(row.get("proposal_count") or -1) for row in runs)
            and all(int(row.get("candidate_action_count") or 0) >= int(row.get("proposal_count") or 0) * 2 for row in runs)
            and all(int(row.get("failure_mode_count") or 0) >= int(row.get("proposal_count") or 0) * 2 for row in runs)
            and all(int(row.get("action_disposition_count") or 0) == int(row.get("proposal_count") or -1) for row in runs)
            and all(row.get("park_profile_context_status") == "attached" for row in runs)
            and all(int(row.get("profile_context_proposal_count") or 0) == int(row.get("proposal_count") or -1) for row in runs)
            and all(int(row.get("profile_precedence_count") or 0) == int(row.get("proposal_count") or -1) for row in runs)
            and all(int(row.get("profile_counterfactual_candidate_count") or 0) >= int(row.get("proposal_count") or 0) * 2 for row in runs)
            and all(int(row.get("evidence_argument_count") or 0) == int(row.get("proposal_count") or -1) for row in runs)
            and all(int(row.get("disposition_evidence_argument_count") or 0) == int(row.get("proposal_count") or -1) for row in runs)
            and all(int(row.get("tradeoff_evidence_argument_count") or 0) == int(row.get("tradeoff_matrix_count") or -1) for row in runs)
            and all(int(row.get("negotiation_round_count") or 0) >= 4 for row in runs)
            and all(int(row.get("tradeoff_matrix_count") or 0) == int(row.get("proposal_count") or -1) for row in runs)
            and all(int(row.get("memory_decision_delta_count") or 0) > 0 for row in runs[1:])
            and all(row.get("hard_follow_status") == "routed" for row in runs)
            and all(int(row.get("hard_follow_task_count") or 0) == int(row.get("held_count") or -1) for row in runs)
            and all(int(row.get("hard_follow_unresolved_without_owner_count") or 0) == 0 for row in runs)
            and all(int(row.get("follow_through_event_link_count") or 0) == int(row.get("hard_follow_task_count") or -1) for row in runs)
            and len(set(run_outcome_ids)) == iterations
            and len(set(run_measurement_ids)) == iterations
            and all(int(row.get("reward_example_count") or 0) >= 1 for row in runs)
            and any(outcome_id in after_outcome_ids for outcome_id in run_outcome_ids)
            and all(row.get("status") == "linked" for row in prior_linkages)
            and all(row.get("status") == "selective" for row in selective_memory_checks)
        )
        else "failed",
        "mode": "live_feed_learning_loop_validation",
        "created_at": _now_iso(),
        "iterations": iterations,
        "runs": runs,
        "memory_growth": {
            "before_latest_outcome_count": len(before_memory.get("outcome_ids", [])),
            "after_latest_outcome_count": len(after_memory.get("outcome_ids", [])),
            "new_dashboard_outcome_ids": new_dashboard_outcomes,
            "run_outcome_ids": run_outcome_ids,
            "run_measurement_ids": run_measurement_ids,
            "unique_run_outcomes": len(set(run_outcome_ids)),
            "unique_run_measurements": len(set(run_measurement_ids)),
            "outcome_ids_visible_after": [outcome_id for outcome_id in run_outcome_ids if outcome_id in after_outcome_ids],
            "prior_linkages": prior_linkages,
            "selective_memory_checks": selective_memory_checks,
        },
        "memory_before": before_memory,
        "memory_after": after_memory,
        "boundary": "This validates growth of offline learning material and operational memory. It does not start training, promote a model, bypass policy gates, or send public guest messages.",
    }
    output_json = QA_DIR / "live-feed-learning-loop-validation.json"
    output_html = QA_DIR / "live-feed-learning-loop-validation.html"
    output_json.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_html.write_text(_render_html(validation, output_json), encoding="utf-8")
    validation["artifacts"] = {"json": str(output_json), "html": str(output_html)}
    output_json.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return validation


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _badge(value: Any) -> str:
    text = str(value or "")
    kind = "ok" if text in {"passed", "measured", "recorded"} else "warn" if text else "neutral"
    return f"<span class='badge {kind}'>{_e(text)}</span>"


def _render_html(validation: dict[str, Any], source_json: Path) -> str:
    rows = []
    for run in validation.get("runs", []) if isinstance(validation.get("runs"), list) else []:
        if not isinstance(run, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_e(run.get('index'))}</td>"
            f"<td>{_badge(run.get('status'))}</td>"
            f"<td>{_e(run.get('outcome_id'))}</td>"
            f"<td>{_e(run.get('measurement_id'))}</td>"
            f"<td>{_e(run.get('receiver_proof_id'))}</td>"
            f"<td>{_e(run.get('executed_count'))} / {_e(run.get('held_count'))}</td>"
            f"<td>{_e(run.get('hard_follow_task_count'))} / {_e(run.get('hard_follow_active_count'))}</td>"
            f"<td>{_e(run.get('profile_context_proposal_count'))} / {_e(run.get('proposal_count'))}</td>"
            f"<td>{_e(run.get('deep_reasoning_proposal_count'))} / {_e(run.get('proposal_count'))}</td>"
            f"<td>{_e(run.get('attribution_confidence'))}</td>"
            f"<td>{_e(run.get('reward_value'))}</td>"
            f"<td>{_e(run.get('reward_example_count'))}</td>"
            "</tr>"
        )
    memory = validation.get("memory_growth", {}) if isinstance(validation.get("memory_growth"), dict) else {}
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Learning Loop Validation</title>
<style>
body {{ margin:0; background:#091116; color:#eef8fb; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ width:min(1360px, calc(100vw - 32px)); margin:0 auto; padding:28px 0 44px; }}
.panel, .metric {{ background:#101b22; border:1px solid #263740; border-radius:8px; padding:18px; }}
.hero {{ display:grid; grid-template-columns:1.2fr .8fr; gap:14px; }}
h1 {{ margin:0; font-size:clamp(32px,5vw,62px); line-height:1; }}
p, small {{ color:#9bacb5; line-height:1.5; }}
.grid {{ display:grid; gap:14px; margin-top:16px; }}
.metrics {{ grid-template-columns:repeat(4,minmax(0,1fr)); }}
.metric span {{ display:block; color:#8fc5ff; font-size:11px; text-transform:uppercase; font-weight:900; }}
.metric strong {{ display:block; margin-top:8px; font-size:28px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:10px 9px; border-bottom:1px solid #263740; text-align:left; vertical-align:top; }}
th {{ color:#9bacb5; background:#0d171d; text-transform:uppercase; font-size:11px; }}
.badge {{ border-radius:999px; padding:5px 8px; font-size:12px; font-weight:800; }}
.badge.ok {{ background:rgba(118,230,166,.15); color:#76e6a6; }}
.badge.warn {{ background:rgba(255,209,102,.14); color:#ffd166; }}
.badge.neutral {{ background:#18242c; color:#c5d2d9; }}
.code {{ font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap:anywhere; }}
@media (max-width:980px) {{ .hero, .metrics {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main>
<section class="hero">
<div class="panel">
<h1>Learning loop growth validation</h1>
<p>Two full live-feed learning cases were run in one runtime. Each case had live department cooperation, controlled execution, receiver acknowledgement, post-action measurement, Mongo-compatible outcome memory, offline reward material, and later runs must retrieve earlier measured outcomes as memory priors.</p>
</div>
<div class="panel">
<p><b>Status:</b> {_badge(validation.get('status'))}</p>
<p><b>Boundary:</b> {_e(validation.get('boundary'))}</p>
<p><b>Source:</b> <span class="code">{_e(source_json)}</span></p>
</div>
</section>
<section class="grid metrics">
<div class="metric"><span>Iterations</span><strong>{_e(validation.get('iterations'))}</strong><small>full learning cases</small></div>
<div class="metric"><span>Unique outcomes</span><strong>{_e(memory.get('unique_run_outcomes'))}</strong><small>run outcome ids</small></div>
<div class="metric"><span>Unique measurements</span><strong>{_e(memory.get('unique_run_measurements'))}</strong><small>post-action attribution ids</small></div>
<div class="metric"><span>Visible in memory</span><strong>{_e(len(memory.get('outcome_ids_visible_after', [])))}</strong><small>run outcomes in latest memory dashboard</small></div>
<div class="metric"><span>Prior linkages</span><strong>{_e(sum(1 for row in memory.get('prior_linkages', []) if isinstance(row, dict) and row.get('status') == 'linked'))}</strong><small>later run used earlier outcome memory</small></div>
<div class="metric"><span>Selective memory</span><strong>{_e(sum(1 for row in memory.get('selective_memory_checks', []) if isinstance(row, dict) and row.get('status') == 'selective'))}</strong><small>accepted only relevant memory edges</small></div>
</section>
<section class="panel grid">
<h2>Case Runs</h2>
<table><thead><tr><th>Run</th><th>Status</th><th>Outcome</th><th>Measurement</th><th>Receiver proof</th><th>Exec / held</th><th>Follow-up tasks / active</th><th>Profile context</th><th>Deep reasoning</th><th>Confidence</th><th>Reward</th><th>Reward rows</th></tr></thead><tbody>
{"".join(rows)}
</tbody></table>
</section>
<section class="panel grid">
<h2>Memory Growth</h2>
<p><b>Run outcome ids:</b> <span class="code">{_e(', '.join(memory.get('run_outcome_ids', [])))}</span></p>
<p><b>Run measurement ids:</b> <span class="code">{_e(', '.join(memory.get('run_measurement_ids', [])))}</span></p>
<p><b>New dashboard outcome ids:</b> <span class="code">{_e(', '.join(memory.get('new_dashboard_outcome_ids', [])))}</span></p>
<p><b>Prior linkages:</b> <span class="code">{_e(json.dumps(memory.get('prior_linkages', []), sort_keys=True))}</span></p>
<p><b>Selective memory checks:</b> <span class="code">{_e(json.dumps(memory.get('selective_memory_checks', []), sort_keys=True))}</span></p>
</section>
</main>
</body>
</html>
"""


def main() -> int:
    validation = asyncio.run(run_learning_loop_validation(iterations=2))
    print(
        json.dumps(
            {
                "status": validation["status"],
                "memory_growth": validation["memory_growth"],
                "artifacts": validation["artifacts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if validation["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
