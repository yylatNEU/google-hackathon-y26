#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_PROGRESS_JSON = REPO_ROOT / "output" / "qa" / "sustainable-growth-progress" / "improvement-curve.json"
DEFAULT_CASE_BANK = REPO_ROOT / "output" / "qa" / "live-feed-case-bank" / "index.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "qa" / "source-conflict-drilldown"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_progress_recorder() -> Any:
    script_path = REPO_ROOT / "scripts" / "record_live_feed_improvement_curve.py"
    spec = importlib.util.spec_from_file_location("record_live_feed_improvement_curve", script_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local_training_rows() -> list[dict[str, Any]]:
    from park_actual_training import (
        _bounded_memory_training_rows,
        _dedupe_training_rows,
        _delayed_outcome_attribution_training_rows,
        _heartbeat_training_signal_rows,
        _live_feed_case_bank_training_rows,
        _sort_training_rows_latest_first,
    )

    return _sort_training_rows_latest_first(
        _dedupe_training_rows(
            [
                *_heartbeat_training_signal_rows(),
                *_delayed_outcome_attribution_training_rows(),
                *_live_feed_case_bank_training_rows(),
                *_bounded_memory_training_rows(),
            ]
        )
    )


def _scenario_curve_from_operating_report(operating_report: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    actual = operating_report.get("actual_training", {}) if isinstance(operating_report.get("actual_training"), dict) else {}
    model_ops = actual.get("model_ops", {}) if isinstance(actual.get("model_ops"), dict) else {}
    scenario_fitness = model_ops.get("scenario_fitness", {}) if isinstance(model_ops.get("scenario_fitness"), dict) else {}
    scenarios = scenario_fitness.get("scenarios", []) if isinstance(scenario_fitness.get("scenarios"), list) else []
    for row in scenarios:
        if isinstance(row, dict) and str(row.get("scenario_key")) == scenario_key:
            return {
                "scenario_key": scenario_key,
                "source": actual.get("source"),
                "decision": row.get("decision"),
                "sample_count": row.get("sample_count"),
                "latest_average_reward": row.get("latest_average_reward"),
                "curve_delta": row.get("curve_delta"),
                "reason": row.get("reason"),
                "curve_points": (row.get("curve", {}) if isinstance(row.get("curve"), dict) else {}).get("points", [])[-8:],
            }
    return {"scenario_key": scenario_key, "source": actual.get("source"), "status": "not_found_in_operating_report"}


def _case_row_summary(row: dict[str, Any], recorder: Any) -> dict[str, Any]:
    measurement = row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}
    projection = measurement.get("controlled_effect_projection", {}) if isinstance(measurement.get("controlled_effect_projection"), dict) else {}
    return {
        "case_id": row.get("case_id"),
        "outcome_id": row.get("outcome_id"),
        "created_at": row.get("created_at"),
        "issue": row.get("issue"),
        "operational_reward": recorder._reward(row),
        "promotion_eligible": recorder._promotion_eligible(row),
        "memory_applied_count": (row.get("memory", {}) if isinstance(row.get("memory"), dict) else {}).get("applied_count"),
        "controlled_effect_status": projection.get("status"),
        "controlled_effect_rows": [
            {
                "source": item.get("source"),
                "changed_metrics": item.get("changed_metrics"),
            }
            for item in (projection.get("rows", []) if isinstance(projection.get("rows"), list) else [])[:5]
            if isinstance(item, dict)
        ],
    }


def _training_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row.get("row_id"),
        "decision_id": row.get("decision_id"),
        "source": row.get("source"),
        "scenario_key": row.get("scenario_key"),
        "policy_key": row.get("policy_key"),
        "reward": row.get("reward"),
        "overall": row.get("overall"),
        "response_score": row.get("response_score"),
        "take_rate": row.get("take_rate"),
        "follow_through_rate": row.get("follow_through_rate"),
        "created_at": row.get("created_at"),
    }


def _repair_hypothesis(scenario_key: str, sources: dict[str, Any]) -> dict[str, Any]:
    decisions = {
        str(source.get("decision"))
        for source in sources.values()
        if isinstance(source, dict) and source.get("decision")
    }
    if "promote_slice" in decisions and "hold_slice" in decisions:
        return {
            "primary_issue": "direct_promote_vs_hold_conflict",
            "hypothesis": "The same scenario has contradictory promotion decisions across training sources.",
            "next_patch": "Compare row export/backfill and reward formulas before accepting either promotion or hold.",
        }
    if scenario_key in {"ride_down", "food_spike"}:
        return {
            "primary_issue": "reward_scale_or_curve_conflict",
            "hypothesis": "Case-bank operational reward is stable, but training reward curve is regressed.",
            "next_patch": "Normalize case-bank operational reward and training reward into a shared slice score, then rerun targeted cases.",
        }
    return {
        "primary_issue": "source_alignment_needed",
        "hypothesis": "Sources do not provide the same confidence about this slice.",
        "next_patch": "Require minimum row coverage and aligned curve direction before promotion.",
    }


def _build_report(progress: dict[str, Any], case_rows: list[dict[str, Any]], operating_report: dict[str, Any] | None, recorder: Any) -> dict[str, Any]:
    reconciliation = progress.get("source_reconciliation", {}) if isinstance(progress.get("source_reconciliation"), dict) else {}
    rows = reconciliation.get("rows", []) if isinstance(reconciliation.get("rows"), list) else []
    conflicts = [row for row in rows if isinstance(row, dict) and row.get("active_conflict", row.get("conflict"))]
    review_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and (
            row.get("active_conflict", row.get("conflict"))
            or row.get("historical_drift")
            or str(row.get("reconciled_decision") or "") in {"candidate_needs_more_current_evidence", "collect_more_source_evidence", "repair_weak_slice"}
        )
    ]
    local_rows = _local_training_rows()
    drilldowns = []
    for item in review_rows:
        scenario_key = str(item.get("scenario_key") or "unknown")
        source_summaries = item.get("sources", {}) if isinstance(item.get("sources"), dict) else {}
        scenario_case_rows = [row for row in case_rows if recorder._scenario_from_issue(row) == scenario_key]
        scenario_training_rows = [row for row in local_rows if str(row.get("scenario_key") or "unknown") == scenario_key]
        case_rewards = [recorder._reward(row) for row in scenario_case_rows if recorder._reward(row) > 0]
        training_rewards = [_safe_float(row.get("reward")) for row in scenario_training_rows if _safe_float(row.get("reward")) > 0]
        drilldowns.append(
            {
                "scenario_key": scenario_key,
                "active_conflict": bool(item.get("active_conflict", item.get("conflict"))),
                "historical_drift": bool(item.get("historical_drift")),
                "conflict_priority": item.get("conflict_priority"),
                "reconciled_decision": item.get("reconciled_decision"),
                "next_action": item.get("next_action"),
                "source_summaries": source_summaries,
                "repair": _repair_hypothesis(scenario_key, source_summaries),
                "case_bank_evidence": {
                    "row_count": len(scenario_case_rows),
                    "average_operational_reward": round(sum(case_rewards) / len(case_rewards), 3) if case_rewards else 0.0,
                    "promotion_eligible_count": sum(1 for row in scenario_case_rows if recorder._promotion_eligible(row)),
                    "latest_rows": [_case_row_summary(row, recorder) for row in scenario_case_rows[-8:]],
                },
                "refreshed_training_evidence": {
                    "row_count": len(scenario_training_rows),
                    "average_reward": round(sum(training_rewards) / len(training_rewards), 2) if training_rewards else 0.0,
                    "latest_rows": [_training_row_summary(row) for row in scenario_training_rows[:12]],
                },
                "operating_report_evidence": _scenario_curve_from_operating_report(operating_report or {}, scenario_key),
            }
        )
    return {
        "created_at": _now_iso(),
        "mode": "source_reconciliation_drilldown",
        "progress_source": progress.get("source_report"),
        "conflict_count": len(conflicts),
        "review_item_count": len(drilldowns),
        "summary": {
            "conflict_scenarios": [row.get("scenario_key") for row in drilldowns if row.get("active_conflict")],
            "historical_drift_scenarios": [row.get("scenario_key") for row in drilldowns if row.get("historical_drift")],
            "watch_scenarios": [row.get("scenario_key") for row in drilldowns if not row.get("active_conflict") and str(row.get("reconciled_decision") or "") != "candidate_consistent_growth"],
            "highest_priority": drilldowns[0].get("scenario_key") if drilldowns else None,
            "promotion_boundary": reconciliation.get("promotion_boundary") or "Hold promotion for conflicted slices until row-level evidence and reward formulas agree across current sources.",
        },
        "drilldowns": drilldowns,
    }


def _badge(value: Any) -> str:
    text = html.escape(str(value))
    normalized = str(value).lower()
    cls = "ok" if normalized in {"strong", "promote_slice", "case_bank_supports_growth"} else "warn" if normalized in {"weak", "hold_slice", "hold_source_conflicted_slice"} else "muted"
    return f'<span class="badge {cls}">{text}</span>'


def _source_table(sources: dict[str, Any]) -> str:
    body = ""
    for name, source in sources.items():
        if not isinstance(source, dict):
            continue
        body += f"""
        <tr>
          <td>{html.escape(str(name))}</td>
          <td>{_badge(source.get('status'))}</td>
          <td>{html.escape(str(source.get('decision')))}</td>
          <td>{html.escape(str(source.get('case_count')))}</td>
          <td>{html.escape(str(source.get('recent_average_reward')))}</td>
          <td>{html.escape(str(source.get('curve_delta')))}</td>
        </tr>
        """
    return f"<table><thead><tr><th>Source</th><th>Status</th><th>Decision</th><th>Rows</th><th>Recent Reward</th><th>Delta</th></tr></thead><tbody>{body}</tbody></table>"


def _rows_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{html.escape(str(row.get(col)))}</td>" for col in columns) + "</tr>"
    return f"<table><thead><tr>{''.join(f'<th>{html.escape(col)}</th>' for col in columns)}</tr></thead><tbody>{body}</tbody></table>"


def _render_html(report: dict[str, Any], path: Path) -> None:
    drilldowns = report.get("drilldowns", []) if isinstance(report.get("drilldowns"), list) else []
    sections = []
    for item in drilldowns:
        case_rows = (item.get("case_bank_evidence", {}) if isinstance(item.get("case_bank_evidence"), dict) else {}).get("latest_rows", [])
        train_rows = (item.get("refreshed_training_evidence", {}) if isinstance(item.get("refreshed_training_evidence"), dict) else {}).get("latest_rows", [])
        operating = item.get("operating_report_evidence", {}) if isinstance(item.get("operating_report_evidence"), dict) else {}
        repair = item.get("repair", {}) if isinstance(item.get("repair"), dict) else {}
        sections.append(
            f"""
            <section>
              <div class="section-head"><h2>{html.escape(str(item.get('scenario_key')))}</h2>{_badge(item.get('reconciled_decision'))}</div>
              <div class="grid">
                <div><strong>Active conflict</strong><span>{html.escape(str(item.get('active_conflict')))}</span><small>Historical drift: {html.escape(str(item.get('historical_drift')))}</small></div>
                <div><strong>Next action</strong><span>{html.escape(str(item.get('next_action') or repair.get('next_patch')))}</span><small>Priority {html.escape(str(item.get('conflict_priority')))}</small></div>
                <div><strong>Case rows</strong><span>{html.escape(str((item.get('case_bank_evidence') or {}).get('row_count')))}</span><small>Avg op reward {html.escape(str((item.get('case_bank_evidence') or {}).get('average_operational_reward')))}</small></div>
                <div><strong>Training rows</strong><span>{html.escape(str((item.get('refreshed_training_evidence') or {}).get('row_count')))}</span><small>Avg reward {html.escape(str((item.get('refreshed_training_evidence') or {}).get('average_reward')))}</small></div>
              </div>
              <h3>Source Summary</h3>
              {_source_table(item.get('source_summaries', {}) if isinstance(item.get('source_summaries'), dict) else {})}
              <h3>Operating Report Curve</h3>
              {_rows_table(operating.get('curve_points', []) if isinstance(operating.get('curve_points'), list) else [], ['episode', 'average_reward', 'latest_reward', 'sample_count', 'from', 'to'])}
              <h3>Latest Case-Bank Rows</h3>
              {_rows_table(case_rows if isinstance(case_rows, list) else [], ['created_at', 'outcome_id', 'operational_reward', 'promotion_eligible', 'controlled_effect_status'])}
              <h3>Latest Refreshed Training Rows</h3>
              {_rows_table(train_rows if isinstance(train_rows, list) else [], ['created_at', 'row_id', 'source', 'reward', 'policy_key', 'decision_id'])}
            </section>
            """
        )
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ParkPulse Source Conflict Drilldown</title>
  <style>
    :root {{ --ink:#17212b; --muted:#607080; --line:#d8e0e7; --panel:#f7fafb; --ok:#0b7651; --warn:#9f6200; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; color:var(--ink); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#fff; }}
    header, main {{ padding:30px 40px; }}
    header {{ border-bottom:1px solid var(--line); }}
    h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0; }}
    h2 {{ margin:0; font-size:20px; letter-spacing:0; }}
    h3 {{ margin:22px 0 10px; font-size:15px; color:var(--muted); text-transform:uppercase; letter-spacing:0; }}
    p {{ margin:0; color:var(--muted); line-height:1.5; }}
    section {{ margin:0 0 34px; padding-bottom:28px; border-bottom:1px solid var(--line); }}
    .section-head {{ display:flex; justify-content:space-between; gap:16px; align-items:center; margin-bottom:14px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:14px 0; }}
    .grid>div {{ border:1px solid var(--line); border-radius:8px; padding:14px; background:var(--panel); min-height:105px; }}
    strong {{ display:block; font-size:12px; text-transform:uppercase; color:var(--muted); margin-bottom:8px; letter-spacing:0; }}
    span {{ display:block; font-size:18px; font-weight:750; line-height:1.2; }}
    small {{ display:block; color:var(--muted); margin-top:8px; line-height:1.35; }}
    table {{ width:100%; border-collapse:collapse; border:1px solid var(--line); border-radius:8px; overflow:hidden; margin-bottom:12px; }}
    th,td {{ padding:9px 10px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); font-size:13px; }}
    th {{ color:var(--muted); background:#f2f6f8; font-size:12px; text-transform:uppercase; letter-spacing:0; }}
    tr:last-child td {{ border-bottom:0; }}
    .badge {{ display:inline-flex; width:fit-content; border-radius:999px; padding:4px 8px; border:1px solid var(--line); font-size:12px; font-weight:700; }}
    .badge.ok {{ color:var(--ok); background:#e9f8f1; border-color:#bde9d6; }}
    .badge.warn {{ color:var(--warn); background:#fff5df; border-color:#ecd39f; }}
    .badge.muted {{ color:var(--muted); background:#f4f6f8; }}
    @media(max-width:960px) {{ header,main {{ padding:22px 18px; }} .grid {{ grid-template-columns:1fr; }} table {{ display:block; overflow-x:auto; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Source Reconciliation Drilldown</h1>
    <p>Row-level evidence for active conflicts, thin current slices, and historical drift. Current active sources gate promotion; older operating snapshots remain visible as drift evidence.</p>
  </header>
  <main>
    {''.join(sections) if sections else '<section><h2>No Review Items</h2><p>Current active sources are aligned and no thin or drift slices were found.</p></section>'}
  </main>
</body>
</html>
"""
    path.write_text(html_doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate row-level ParkPulse source conflict drilldown.")
    parser.add_argument("--progress-json", type=Path, default=DEFAULT_PROGRESS_JSON)
    parser.add_argument("--case-bank", type=Path, default=DEFAULT_CASE_BANK)
    parser.add_argument("--operating-report", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    recorder = _load_progress_recorder()
    progress = _read_json(args.progress_json)
    case_rows = _read_jsonl(args.case_bank)
    operating_report_path = args.operating_report or Path(str(progress.get("source_report") or ""))
    operating_report = _read_json(operating_report_path) if operating_report_path.exists() else {}
    report = _build_report(progress, case_rows, operating_report, recorder)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "source-conflict-drilldown.json"
    html_path = args.output_dir / "source-conflict-drilldown.html"
    ledger_path = args.output_dir / "ledger.jsonl"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    _render_html(report, html_path)

    print(json.dumps({"status": "recorded", "json": str(json_path), "html": str(html_path), "ledger": str(ledger_path), "summary": report["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
