#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _latest_report_path(root: Path) -> Path | None:
    candidates = sorted(
        root.glob("output/qa/operating-cycle-*/live-feed-operating-cycle.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _check(name: str, passed: bool, evidence: dict[str, Any], *, blocker: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "blocker": None if passed else blocker or f"{name} did not pass.",
        "evidence": evidence,
    }


def build_sustainable_growth_verification(case_bank_summary: dict[str, Any], operating_report: dict[str, Any], *, case_bank_path: Path, report_path: Path) -> dict[str, Any]:
    summary = operating_report.get("summary", {}) if isinstance(operating_report.get("summary"), dict) else {}
    cycles = operating_report.get("cycles", []) if isinstance(operating_report.get("cycles"), list) else []
    latest_cycle = cycles[-1] if cycles and isinstance(cycles[-1], dict) else {}
    cycle_measurement = latest_cycle.get("measurement", {}) if isinstance(latest_cycle.get("measurement"), dict) else {}
    reward_layers = cycle_measurement.get("reward_layers", {}) if isinstance(cycle_measurement.get("reward_layers"), dict) else {}
    controlled_effect = cycle_measurement.get("controlled_effect_projection", {}) if isinstance(cycle_measurement.get("controlled_effect_projection"), dict) else {}
    cycle_actions = latest_cycle.get("actions", {}) if isinstance(latest_cycle.get("actions"), dict) else {}
    cycle_agents = latest_cycle.get("agents", {}) if isinstance(latest_cycle.get("agents"), dict) else {}
    cycle_memory = latest_cycle.get("memory", {}) if isinstance(latest_cycle.get("memory"), dict) else {}
    truth = latest_cycle.get("truth_boundaries", {}) if isinstance(latest_cycle.get("truth_boundaries"), dict) else {}
    quality_gate = case_bank_summary.get("quality_gate", {}) if isinstance(case_bank_summary.get("quality_gate"), dict) else {}
    quality_metrics = quality_gate.get("metrics", {}) if isinstance(quality_gate.get("metrics"), dict) else {}
    sustainability_gate = case_bank_summary.get("sustainability_gate", {}) if isinstance(case_bank_summary.get("sustainability_gate"), dict) else {}
    sustainability_metrics = sustainability_gate.get("metrics", {}) if isinstance(sustainability_gate.get("metrics"), dict) else {}
    actual_training = operating_report.get("actual_training", {}) if isinstance(operating_report.get("actual_training"), dict) else {}
    model_ops = actual_training.get("model_ops", {}) if isinstance(actual_training.get("model_ops"), dict) else {}
    promotion_gate = model_ops.get("promotion_gate", {}) if isinstance(model_ops.get("promotion_gate"), dict) else {}

    checks = [
        _check(
            "live_state_simulation_not_seeded",
            operating_report.get("status") == "passed"
            and truth.get("uses_seed_data") is False
            and truth.get("scripted_case") is False
            and truth.get("real_external_park_connected") is False,
            {
                "report_status": operating_report.get("status"),
                "uses_seed_data": truth.get("uses_seed_data"),
                "scripted_case": truth.get("scripted_case"),
                "real_external_park_connected": truth.get("real_external_park_connected"),
                "issue": latest_cycle.get("issue"),
            },
            blocker="Latest operating cycle must be generated from the app live-state simulation and must not use seeded/scripted case data.",
        ),
        _check(
            "agent_negotiation_from_memory",
            _safe_int(cycle_agents.get("proposal_count")) >= 12
            and _safe_int(cycle_agents.get("negotiation_round_count")) >= 4
            and _safe_int(cycle_memory.get("applied_count")) > 0
            and summary.get("memory_growth", {}).get("memory_help_observed") is True,
            {
                "proposal_count": cycle_agents.get("proposal_count"),
                "negotiation_round_count": cycle_agents.get("negotiation_round_count"),
                "memory_applied_count": cycle_memory.get("applied_count"),
                "memory_growth": summary.get("memory_growth"),
            },
            blocker="Agents must negotiate and apply measured prior memory in the latest cycle.",
        ),
        _check(
            "bounded_tool_execution_with_reasoning",
            _safe_int(cycle_actions.get("executed_count")) > 0
            and _safe_int(cycle_actions.get("held_count")) > 0
            and _safe_int(cycle_actions.get("unresolved_without_owner_count")) == 0
            and _safe_int(cycle_actions.get("public_guest_messages_sent")) == 0
            and cycle_actions.get("material_state_mutation") is False,
            {
                "executed_count": cycle_actions.get("executed_count"),
                "held_count": cycle_actions.get("held_count"),
                "active_follow_up_count": cycle_actions.get("active_follow_up_count"),
                "unresolved_without_owner_count": cycle_actions.get("unresolved_without_owner_count"),
                "public_guest_messages_sent": cycle_actions.get("public_guest_messages_sent"),
                "material_state_mutation": cycle_actions.get("material_state_mutation"),
            },
            blocker="Tool execution must execute bounded low-risk actions, hold gated actions, and leave no ownerless hard decisions.",
        ),
        _check(
            "measured_operational_outcome",
            cycle_measurement.get("status") == "measured"
            and cycle_measurement.get("measured_outcome_available") is True
            and reward_layers.get("version") == "live_feed_reward_vector_v1"
            and _safe_float(reward_layers.get("operational_reward")) >= 0.55
            and controlled_effect.get("status") == "applied",
            {
                "measurement_status": cycle_measurement.get("status"),
                "measured_outcome_available": cycle_measurement.get("measured_outcome_available"),
                "operational_reward": reward_layers.get("operational_reward"),
                "promotion_eligible": cycle_measurement.get("promotion_eligible"),
                "controlled_effect_status": controlled_effect.get("status"),
                "controlled_effect_projection_count": controlled_effect.get("projection_count"),
            },
            blocker="Latest cycle must have measured reward-vector operational lift from controlled-effect evidence.",
        ),
        _check(
            "durable_trace_reward_case_bank",
            case_bank_summary.get("append_only") is True
            and case_bank_summary.get("dedupe_key") == "outcome_id"
            and quality_gate.get("ready_for_training") is True
            and _safe_int(quality_metrics.get("reward_vector_case_count")) >= _safe_int(quality_gate.get("requirements", {}).get("min_training_rows"), 50)
            and _safe_int(summary.get("reward_example_count")) > 0
            and _safe_int(summary.get("training_example_count")) > 0,
            {
                "append_only": case_bank_summary.get("append_only"),
                "dedupe_key": case_bank_summary.get("dedupe_key"),
                "quality_status": quality_gate.get("status"),
                "reward_vector_case_count": quality_metrics.get("reward_vector_case_count"),
                "training_example_count": summary.get("training_example_count"),
                "reward_example_count": summary.get("reward_example_count"),
                "latest_outcome_ids": case_bank_summary.get("latest_outcome_ids", [])[:5],
            },
            blocker="Case bank must be append-only, reward-vector backed, and produce durable training/reward material.",
        ),
        _check(
            "diverse_promotion_eligible_evidence",
            sustainability_gate.get("ready_for_sustainable_growth") is True
            and _safe_int(sustainability_metrics.get("promotion_eligible_case_count")) >= _safe_int(sustainability_gate.get("requirements", {}).get("min_promotion_eligible_cases"), 15)
            and _safe_float(sustainability_metrics.get("promotion_eligible_ratio")) >= _safe_float(sustainability_gate.get("requirements", {}).get("min_promotion_eligible_ratio"), 0.25)
            and _safe_int(sustainability_metrics.get("promotion_issue_kind_count")) >= _safe_int(sustainability_gate.get("requirements", {}).get("min_promotion_issue_kinds"), 8)
            and _safe_int(sustainability_metrics.get("promotion_target_count")) >= _safe_int(sustainability_gate.get("requirements", {}).get("min_promotion_targets"), 6),
            {
                "sustainability_status": sustainability_gate.get("status"),
                "promotion_eligible_case_count": sustainability_metrics.get("promotion_eligible_case_count"),
                "promotion_eligible_ratio": sustainability_metrics.get("promotion_eligible_ratio"),
                "promotion_issue_kind_count": sustainability_metrics.get("promotion_issue_kind_count"),
                "promotion_target_count": sustainability_metrics.get("promotion_target_count"),
            },
            blocker="Promotion evidence must be diverse enough across issue kinds and targets.",
        ),
        _check(
            "training_vs_promotion_readiness_separated",
            actual_training.get("status") == "ready"
            and summary.get("case_bank_quality_status") == "passed"
            and summary.get("case_bank_sustainability_status") == "growing"
            and promotion_gate.get("status") in {"slice_promotable", "hold"}
            and bool(promotion_gate.get("decision")),
            {
                "actual_training_status": actual_training.get("status"),
                "case_bank_quality_status": summary.get("case_bank_quality_status"),
                "case_bank_sustainability_status": summary.get("case_bank_sustainability_status"),
                "promotion_gate_status": promotion_gate.get("status"),
                "promotion_gate_decision": promotion_gate.get("decision"),
                "promotable_slices": promotion_gate.get("promotable_slices", []),
                "held_slices": promotion_gate.get("held_slices", [])[:3],
            },
            blocker="Report must show training readiness separately from promotion readiness.",
        ),
    ]

    blockers = [check["blocker"] for check in checks if check["status"] != "passed" and check.get("blocker")]
    return {
        "status": "passed" if not blockers else "failed",
        "mode": "live_feed_sustainable_growth_verification",
        "created_at": _now_iso(),
        "case_bank_summary_path": str(case_bank_path),
        "operating_report_path": str(report_path),
        "checks": checks,
        "blockers": blockers,
        "summary": {
            "passed_check_count": sum(1 for check in checks if check["status"] == "passed"),
            "failed_check_count": sum(1 for check in checks if check["status"] != "passed"),
            "case_bank_total_case_count": case_bank_summary.get("total_case_count"),
            "reward_vector_case_count": quality_metrics.get("reward_vector_case_count"),
            "promotion_eligible_case_count": sustainability_metrics.get("promotion_eligible_case_count"),
            "sustainability_status": sustainability_gate.get("status"),
            "actual_training_status": actual_training.get("status"),
            "promotion_gate_status": promotion_gate.get("status"),
            "promotion_gate_decision": promotion_gate.get("decision"),
        },
    }


def _render_html(report: dict[str, Any], path: Path) -> None:
    checks = report.get("checks", []) if isinstance(report.get("checks"), list) else []
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    rows = []
    for check in checks:
        evidence = check.get("evidence", {}) if isinstance(check.get("evidence"), dict) else {}
        rows.append(
            f"""
            <section class="check {html.escape(str(check.get('status')))}">
              <div>
                <h2>{html.escape(str(check.get('name')))}</h2>
                <span>{html.escape(str(check.get('status')))}</span>
              </div>
              <pre>{html.escape(json.dumps(evidence, indent=2, sort_keys=True, default=str))}</pre>
              {'' if check.get('status') == 'passed' else f"<p>{html.escape(str(check.get('blocker')))}</p>"}
            </section>
            """
        )
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ParkPulse Sustainable Growth Verification</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #17212b; background: #fff; }}
    header, main {{ padding: 28px 40px; }}
    header {{ border-bottom: 1px solid #d9e1e8; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 0; font-size: 17px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 20px; }}
    .card, .check {{ border: 1px solid #d9e1e8; border-radius: 8px; padding: 14px; background: #f7fafc; }}
    .card strong {{ display: block; color: #5d6875; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; }}
    .card span {{ font-size: 22px; font-weight: 700; }}
    .check {{ margin-top: 14px; }}
    .check > div {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    .check span {{ border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; background: #eaf8f2; color: #0f7a55; }}
    .check.failed span {{ background: #fff4df; color: #a45f00; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #fff; border: 1px solid #d9e1e8; border-radius: 8px; padding: 12px; color: #293847; }}
    footer {{ margin-top: 24px; color: #5d6875; border-top: 1px solid #d9e1e8; padding-top: 18px; }}
    @media (max-width: 900px) {{ header, main {{ padding: 18px; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>ParkPulse Sustainable Growth Verification</h1>
    <p>Machine-checks the live-feed multi-agent loop against the sustainable-growth objective.</p>
  </header>
  <main>
    <section class="grid">
      <div class="card"><strong>Status</strong><span>{html.escape(str(report.get('status')))}</span></div>
      <div class="card"><strong>Checks</strong><span>{html.escape(str(summary.get('passed_check_count')))} / {html.escape(str((summary.get('passed_check_count') or 0) + (summary.get('failed_check_count') or 0)))}</span></div>
      <div class="card"><strong>Reward Vectors</strong><span>{html.escape(str(summary.get('reward_vector_case_count')))}</span></div>
      <div class="card"><strong>Promotion Cases</strong><span>{html.escape(str(summary.get('promotion_eligible_case_count')))}</span></div>
    </section>
    {''.join(rows)}
    <footer>Generated {html.escape(str(report.get('created_at')))}. Source report: {html.escape(str(report.get('operating_report_path')))}</footer>
  </main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ParkPulse live-feed sustainable-growth evidence.")
    parser.add_argument("--case-bank-summary", default=str(REPO_ROOT / "output/qa/live-feed-case-bank/summary.json"))
    parser.add_argument("--operating-report", default=None)
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "output/qa/sustainable-growth-verification"))
    args = parser.parse_args()

    case_bank_path = Path(args.case_bank_summary)
    report_path = Path(args.operating_report) if args.operating_report else _latest_report_path(REPO_ROOT)
    if report_path is None:
        raise SystemExit("No operating report found. Run scripts/live_feed_operating_cycle.py first.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = build_sustainable_growth_verification(
        _read_json(case_bank_path),
        _read_json(report_path),
        case_bank_path=case_bank_path,
        report_path=report_path,
    )
    json_path = output_dir / "sustainable-growth-verification.json"
    html_path = output_dir / "sustainable-growth-verification.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    _render_html(report, html_path)
    print(json.dumps({"status": report["status"], "summary": report["summary"], "output_json": str(json_path), "output_html": str(html_path)}, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
