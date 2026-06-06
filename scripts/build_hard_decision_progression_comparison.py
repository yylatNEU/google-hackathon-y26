from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _get(data: Any, path: list[Any], default: Any = None) -> Any:
    cursor = data
    for key in path:
        if isinstance(cursor, dict):
            cursor = cursor.get(key)
        elif isinstance(cursor, list) and isinstance(key, int) and 0 <= key < len(cursor):
            cursor = cursor[key]
        else:
            return default
    return default if cursor is None else cursor


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _avg(values: list[Any], digits: int = 3) -> float | None:
    numbers = [_num(value) for value in values]
    filtered = [value for value in numbers if value is not None]
    return round(mean(filtered), digits) if filtered else None


def _round(value: Any, digits: int = 3) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _branch_rows(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _get(cycle, ["measurement", "reward_layers", "substitute_outcome_attribution", "rows"], [])
    return rows if isinstance(rows, list) else []


def _baseline_monitor_score(report: dict[str, Any]) -> float:
    scores = []
    for cycle in report.get("cycles", []) if isinstance(report.get("cycles"), list) else []:
        for row in _branch_rows(cycle):
            if isinstance(row, dict):
                scores.append(row.get("monitor_only_counterfactual_score"))
    return _avg(scores) or 0.05


def _label_counts(values: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "missing")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _model_summary(name: str, report: dict[str, Any], source: str, note: str) -> dict[str, Any]:
    cycles = report.get("cycles", []) if isinstance(report.get("cycles"), list) else []
    hard_scores = []
    hard_labels = []
    risk_labels = []
    case_rows = []
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        layers = _get(cycle, ["measurement", "reward_layers"], {}) or {}
        if not isinstance(layers, dict):
            layers = {}
        hard = _num(layers.get("hard_decision_activation_reward"))
        hard_scores.append(hard)
        hard_labels.append(layers.get("hard_decision_activation_label"))
        risk_labels.append(layers.get("risk_lift_label"))
        case_rows.append(
            {
                "case": f"cycle_{cycle.get('cycle')}",
                "issue": _get(cycle, ["issue", "kind"]),
                "target": _get(cycle, ["issue", "target_id"]),
                "slice": _get(cycle, ["ml_policy", "scenario_key"]),
                "hard_decision": _round(hard),
                "hard_label": layers.get("hard_decision_activation_label") or "missing",
                "risk_lift": _round(layers.get("risk_lift_reward")),
                "risk_label": layers.get("risk_lift_label"),
                "operational_reward": _round(layers.get("operational_reward")),
                "composite_reward": _round(layers.get("composite_reward")),
                "executed": _get(cycle, ["actions", "executed_count"]),
                "held": _get(cycle, ["actions", "held_count"]),
                "memory": _get(layers, ["metrics", "memory_applied_count"]),
            }
        )
    scored = [value for value in hard_scores if value is not None]
    return {
        "name": name,
        "source": source,
        "note": note,
        "case_count": len(cycles),
        "hard_decision_scored_case_count": len(scored),
        "hard_decision_average": _avg(scored),
        "hard_decision_min": round(min(scored), 3) if scored else None,
        "hard_decision_max": round(max(scored), 3) if scored else None,
        "hard_decision_spread": round(max(scored) - min(scored), 3) if scored else None,
        "hard_decision_label_counts": _label_counts(hard_labels),
        "risk_lift_label_counts": _label_counts(risk_labels),
        "operational_reward_average": _avg([row.get("operational_reward") for row in case_rows]),
        "composite_reward_average": _avg([row.get("composite_reward") for row in case_rows]),
        "executed_action_count": _get(report, ["summary", "executed_action_count"]),
        "held_action_count": _get(report, ["summary", "held_action_count"]),
        "promotion_gate_status": _get(report, ["summary", "promotion_gate_status"]),
        "promotion_gate_decision": _get(report, ["summary", "promotion_gate_decision"]),
        "case_rows": case_rows,
    }


def _baseline_summary(current: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "name": "Monitor-only baseline",
        "source": source,
        "note": "Same-case baseline does not execute or lift hard actions.",
        "case_count": len(current.get("cycles", []) if isinstance(current.get("cycles"), list) else []),
        "hard_decision_scored_case_count": 0,
        "hard_decision_average": 0.0,
        "hard_decision_min": 0.0,
        "hard_decision_max": 0.0,
        "hard_decision_spread": 0.0,
        "hard_decision_label_counts": {"monitor_only_hold": 8},
        "risk_lift_label_counts": {"not_attempted": 8},
        "operational_reward_average": _baseline_monitor_score(current),
        "composite_reward_average": None,
        "executed_action_count": 0,
        "held_action_count": "all",
        "promotion_gate_status": "not_promotable_baseline",
        "promotion_gate_decision": "monitor_only_hold",
        "case_rows": [],
    }


def _esc(value: Any) -> str:
    return html.escape(str("" if value is None else value))


def _bar(value: Any, max_value: float = 1.0) -> str:
    number = _num(value)
    if number is None:
        return '<div class="bar muted"><i style="width:0%"></i><span>n/a</span></div>'
    width = max(0.0, min(100.0, (number / max_value) * 100.0))
    return f'<div class="bar"><i style="width:{width:.1f}%"></i><span>{_esc(round(number, 3))}</span></div>'


def _render(payload: dict[str, Any]) -> str:
    models = payload["models"]
    cards = "\n".join(
        f"""
        <article class="card">
          <h3>{_esc(row['name'])}</h3>
          <p>{_esc(row['note'])}</p>
          <div class="score"><b>Hard decision target</b>{_bar(row['hard_decision_average'])}</div>
          <div class="kv"><b>Spread</b><span>{_esc(row['hard_decision_min'])} - {_esc(row['hard_decision_max'])}</span></div>
          <div class="kv"><b>Scored cases</b><span>{_esc(row['hard_decision_scored_case_count'])} / {_esc(row['case_count'])}</span></div>
          <div class="kv"><b>Gate</b><span>{_esc(row['promotion_gate_status'])}</span></div>
        </article>
        """
        for row in models
    )
    model_body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['name'])}<br><small>{_esc(row['source'])}</small></td>"
        f"<td>{_bar(row['hard_decision_average'])}</td>"
        f"<td>{_esc(row['hard_decision_spread'])}</td>"
        f"<td>{_esc(row['hard_decision_label_counts'])}</td>"
        f"<td>{_esc(row['risk_lift_label_counts'])}</td>"
        f"<td>{_esc(row['operational_reward_average'])}</td>"
        f"<td>{_esc(row['composite_reward_average'])}</td>"
        f"<td>{_esc(row['executed_action_count'])} / {_esc(row['held_action_count'])}</td>"
        "</tr>"
        for row in models
    )
    latest_cases = next((row["case_rows"] for row in models if row["name"].startswith("Latest")), [])
    case_body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['case'])}<br><small>{_esc(row['issue'])} at {_esc(row['target'])}</small></td>"
        f"<td>{_esc(row['slice'])}</td>"
        f"<td>{_bar(row['hard_decision'])}<small>{_esc(row['hard_label'])}</small></td>"
        f"<td>{_esc(row['risk_lift'])}<br><small>{_esc(row['risk_label'])}</small></td>"
        f"<td>{_esc(row['operational_reward'])}</td>"
        f"<td>{_esc(row['executed'])} / {_esc(row['held'])}</td>"
        f"<td>{_esc(row['memory'])}</td>"
        "</tr>"
        for row in latest_cases
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ParkPulse Hard Decision Model Progression</title>
<style>
:root{{--ink:#17212b;--muted:#607080;--line:#dbe2e8;--panel:#f7f9fb;--ok:#0b7a55;--warn:#9a5a00;--blue:#2458a6}}
body{{margin:0;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:#fff}} main{{max-width:1280px;margin:0 auto;padding:28px}}
h1{{font-size:28px;margin:0 0 6px}} h2{{font-size:18px;margin:28px 0 10px}} p,small{{color:var(--muted)}} .cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}}
.card,.panel{{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:16px}} .panel{{background:#fff;margin:14px 0;overflow:auto}} .card h3{{margin:0 0 6px;font-size:17px}} .kv{{display:grid;grid-template-columns:92px 1fr;gap:8px;border-top:1px solid var(--line);padding:8px 0}}
.score b{{display:block;margin-bottom:4px}} .bar{{position:relative;height:24px;border:1px solid var(--line);background:#fff;border-radius:5px;overflow:hidden}} .bar i{{display:block;height:100%;background:linear-gradient(90deg,#77b7a0,#2458a6)}} .bar span{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-weight:700}} .bar.muted{{background:#eef2f6}}
table{{width:100%;border-collapse:collapse;min-width:1080px}} th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px}} th{{font-size:12px;color:var(--muted);background:var(--panel);position:sticky;top:0}} code{{background:#eef2f6;padding:2px 5px;border-radius:5px}}
.note{{border-left:4px solid var(--warn);background:#fff8ef;border-radius:6px;padding:12px}}
@media(max-width:940px){{.cards{{grid-template-columns:1fr}}main{{padding:18px}}}}
</style></head><body><main>
<h1>ParkPulse Hard Decision Model Progression</h1>
<p>Generated {_esc(payload['generated_at'])}. This compares the latest tuned hard-decision target with an intermediate checkpoint that had hard-decision scoring, plus the monitor-only baseline.</p>
<section class="note"><b>Read this carefully:</b> the intermediate checkpoint is not the immediate previous deployed model. It is the previous scored checkpoint. The old immediate snapshot is still useful for gate history, but it cannot directly compare hard-decision quality because that field was missing.</section>
<div class="cards">{cards}</div>
<section class="panel"><h2>Scored Model Matrix</h2><table><thead><tr><th>Model</th><th>Hard decision avg</th><th>Spread</th><th>Hard labels</th><th>Risk labels</th><th>Operational avg</th><th>Composite avg</th><th>Executed / held</th></tr></thead><tbody>{model_body}</tbody></table></section>
<section class="panel"><h2>Latest V2 Case Evidence</h2><table><thead><tr><th>Case</th><th>Slice</th><th>Hard decision</th><th>Risk lift</th><th>Operational reward</th><th>Executed / held</th><th>Memory</th></tr></thead><tbody>{case_body}</tbody></table></section>
<section class="panel"><h2>Files</h2><p>JSON: <code>{_esc(payload['outputs']['json'])}</code></p></section>
</main></body></html>"""


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_path = (ROOT / args.latest).resolve()
    intermediate_path = (ROOT / args.intermediate).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    latest = _read_json(latest_path)
    intermediate = _read_json(intermediate_path)
    latest_rel = str(latest_path.relative_to(ROOT))
    intermediate_rel = str(intermediate_path.relative_to(ROOT))
    models = [
        _model_summary(
            "Latest v2 tuned hard-decision model",
            latest,
            latest_rel,
            "Uses hard-decision activation as a first-class target with gradient from measured impact.",
        ),
        _model_summary(
            "Intermediate scored model",
            intermediate,
            intermediate_rel,
            "First scored checkpoint; proves hard actions were lifted, but the score saturates at 1.0.",
        ),
        _baseline_summary(latest, latest_rel),
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "hard_decision_model_progression",
        "inputs": {
            "latest": latest_rel,
            "intermediate_scored_checkpoint": intermediate_rel,
        },
        "models": models,
        "interpretation": {
            "latest_vs_intermediate": "Latest v2 is not higher numerically because v1 saturated at 1.0; v2 is better for training because it creates non-flat quality signal.",
            "latest_vs_baseline": "Baseline has zero hard-decision activation because it does not execute or lift hard actions.",
            "comparability": "Latest and intermediate are separate live-feed batches, not the exact same case replay.",
        },
    }
    output_json = output_dir / "hard-decision-progression-comparison.json"
    output_html = output_dir / "hard-decision-progression-comparison.html"
    payload["outputs"] = {
        "json": str(output_json.relative_to(ROOT)),
        "html": str(output_html.relative_to(ROOT)),
    }
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    output_html.write_text(_render(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare latest hard-decision scoring against an intermediate scored ParkPulse checkpoint.")
    parser.add_argument("--latest", default="output/qa/hard-decision-target-v2-20260605/live-feed-operating-cycle.json")
    parser.add_argument("--intermediate", default="output/qa/hard-decision-target-comparison-20260605/live-feed-operating-cycle.json")
    parser.add_argument("--output-dir", default="output/qa/hard-decision-target-v2-20260605")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps({"status": "written", "outputs": result["outputs"], "models": result["models"]}, indent=2, sort_keys=True))
