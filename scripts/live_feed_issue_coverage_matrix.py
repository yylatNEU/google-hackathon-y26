#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
BACKEND_DIR = REPO_ROOT / "backend"
for path in (SCRIPTS_DIR, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import live_feed_operating_cycle as cycle_runner


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _short(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _proposal_tool(proposal: dict[str, Any]) -> str:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    return str(envelope.get("requested_tool") or proposal.get("requested_tool") or "")


def _proposal_status(proposal: dict[str, Any]) -> str:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    return str(envelope.get("executor_status") or proposal.get("executor_status") or "")


def _receipt_status(receipt: dict[str, Any]) -> str:
    result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
    return str(result.get("status") or "")


def _coverage_row(result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    payload = result.get("payload", {}) if isinstance(result.get("payload"), dict) else {}
    proposals_root = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    proposals = proposals_root.get("proposals", []) if isinstance(proposals_root.get("proposals"), list) else []
    receipts_root = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    receipts = receipts_root.get("receipts", []) if isinstance(receipts_root.get("receipts"), list) else []
    issue = summary.get("issue", {}) if isinstance(summary.get("issue"), dict) else {}
    alignment = summary.get("issue_action_alignment", {}) if isinstance(summary.get("issue_action_alignment"), dict) else {}

    issue_specific = [row for row in proposals if isinstance(row, dict) and row.get("issue_specific") is True]
    issue_specific_keys = {
        (str(row.get("department") or ""), _proposal_tool(row))
        for row in issue_specific
    }
    executed_receipts = [row for row in receipts if isinstance(row, dict) and _receipt_status(row) == "executed_controlled"]
    held_receipts = [row for row in receipts if isinstance(row, dict) and _receipt_status(row) == "held"]
    executed_keys = {
        (str(row.get("department") or ""), str(row.get("source_tool") or ""))
        for row in executed_receipts
    }
    held_keys = {
        (str(row.get("department") or ""), str(row.get("source_tool") or ""))
        for row in held_receipts
    }
    issue_specific_executed = sorted(
        f"{department}::{tool}"
        for department, tool in (issue_specific_keys & executed_keys)
        if department and tool
    )
    issue_specific_held = sorted(
        f"{department}::{tool}"
        for department, tool in (issue_specific_keys & held_keys)
        if department and tool
    )
    issue_specific_policy_mix = {
        str((row.get("policy_judge", {}) if isinstance(row.get("policy_judge"), dict) else {}).get("status") or "unknown")
        for row in issue_specific
        if isinstance(row, dict)
    }
    first_issue_specific = [
        {
            "agent": row.get("agent_id"),
            "department": row.get("department"),
            "tool": _proposal_tool(row),
            "status": _proposal_status(row),
            "policy": (row.get("policy_judge", {}) if isinstance(row.get("policy_judge"), dict) else {}).get("status"),
            "disposition": (row.get("action_disposition", {}) if isinstance(row.get("action_disposition"), dict) else {}).get("decision"),
            "recommendation": _short(row.get("recommendation")),
        }
        for row in issue_specific[:4]
        if isinstance(row, dict)
    ]

    alignment_status = str(alignment.get("status") or "missing")
    has_issue_specific = bool(issue_specific)
    has_executed_match = bool(issue_specific_executed) or bool(alignment.get("executed_match"))
    has_gated_sensitive = bool(issue_specific_held) or bool(alignment.get("held_match"))
    ownerless = _safe_int((summary.get("actions", {}) if isinstance(summary.get("actions"), dict) else {}).get("unresolved_without_owner_count"))
    if summary.get("status") != "passed":
        grade = "failed"
    elif alignment_status == "unknown_issue_expectation" or not has_issue_specific:
        grade = "generic"
    elif alignment_status != "aligned_executed":
        grade = "weak"
    elif not has_executed_match:
        grade = "weak"
    elif ownerless:
        grade = "weak"
    else:
        grade = "strong"

    gaps: list[str] = []
    if alignment_status == "unknown_issue_expectation":
        gaps.append("No issue/action expectation registered.")
    if not has_issue_specific:
        gaps.append("No first-round issue-specific proposal.")
    if not has_executed_match:
        gaps.append("No issue-family bounded action executed.")
    if not has_gated_sensitive:
        gaps.append("No matching held/gated sensitive action was recorded.")
    if ownerless:
        gaps.append(f"{ownerless} follow-ups have no owner.")
    if summary.get("status") != "passed":
        gaps.append(f"Cycle status is {summary.get('status')}.")

    return {
        "issue_kind": issue.get("kind"),
        "target_id": issue.get("target_id"),
        "intensity": issue.get("intensity"),
        "grade": grade,
        "status": summary.get("status"),
        "alignment_status": alignment_status,
        "template_risk": alignment.get("template_risk"),
        "expected_tools": alignment.get("expected_tools", []),
        "executed_tools": alignment.get("executed_tools", []),
        "held_tools": alignment.get("held_tools", []),
        "issue_specific_proposal_count": len(issue_specific),
        "issue_specific_executed": issue_specific_executed,
        "issue_specific_held": issue_specific_held,
        "issue_specific_policy_mix": sorted(issue_specific_policy_mix),
        "proposal_count": len(proposals),
        "negotiation_round_count": _safe_int((summary.get("agents", {}) if isinstance(summary.get("agents"), dict) else {}).get("negotiation_round_count")),
        "executed_count": _safe_int((summary.get("actions", {}) if isinstance(summary.get("actions"), dict) else {}).get("executed_count")),
        "held_count": _safe_int((summary.get("actions", {}) if isinstance(summary.get("actions"), dict) else {}).get("held_count")),
        "memory_applied_count": _safe_int((summary.get("memory", {}) if isinstance(summary.get("memory"), dict) else {}).get("applied_count")),
        "outcome_id": (summary.get("memory", {}) if isinstance(summary.get("memory"), dict) else {}).get("outcome_id"),
        "run_json": (summary.get("artifacts", {}) if isinstance(summary.get("artifacts"), dict) else {}).get("run_json"),
        "first_issue_specific": first_issue_specific,
        "gaps": gaps,
    }


def _grade_badge(grade: str) -> str:
    labels = {
        "strong": "Strong",
        "weak": "Weak",
        "generic": "Generic",
        "failed": "Failed",
    }
    return f'<span class="badge {html.escape(grade)}">{html.escape(labels.get(grade, grade))}</span>'


def _render_list(items: Any, limit: int = 5) -> str:
    rows = items if isinstance(items, list) else []
    if not rows:
        return '<span class="muted">none</span>'
    return "<ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in rows[:limit]) + "</ul>"


def _render_html(report: dict[str, Any], path: Path) -> None:
    rows = report.get("rows", []) if isinstance(report.get("rows"), list) else []
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    table_rows = []
    for row in rows:
        first_props = row.get("first_issue_specific", []) if isinstance(row.get("first_issue_specific"), list) else []
        prop_lines = []
        for proposal in first_props[:3]:
            prop_lines.append(
                "<li>"
                f"<b>{html.escape(str(proposal.get('agent')))}</b> "
                f"{html.escape(str(proposal.get('department')))}::{html.escape(str(proposal.get('tool')))} "
                f"<span class=\"muted\">{html.escape(str(proposal.get('policy')))} / {html.escape(str(proposal.get('disposition')))}</span>"
                f"<br>{html.escape(str(proposal.get('recommendation')))}"
                "</li>"
            )
        table_rows.append(
            "<tr>"
            f"<td><b>{html.escape(str(row.get('issue_kind')))}</b><br><span class=\"muted\">{html.escape(str(row.get('target_id')))} / intensity {html.escape(str(row.get('intensity')))}</span></td>"
            f"<td>{_grade_badge(str(row.get('grade')))}<br><span class=\"muted\">{html.escape(str(row.get('alignment_status')))} / risk {html.escape(str(row.get('template_risk')))}</span></td>"
            f"<td><b>{html.escape(str(row.get('issue_specific_proposal_count')))}</b> issue-specific<br>{html.escape(str(row.get('negotiation_round_count')))} negotiation rounds<br>{html.escape(str(row.get('memory_applied_count')))} memory applied</td>"
            f"<td><b>Executed:</b> {_render_list(row.get('issue_specific_executed'), 4)}<b>Held:</b> {_render_list(row.get('issue_specific_held'), 4)}</td>"
            f"<td><b>Expected tools</b>{_render_list(row.get('expected_tools'), 5)}<b>Executed tools</b>{_render_list(row.get('executed_tools'), 5)}</td>"
            f"<td><ul>{''.join(prop_lines) or '<li class=\"muted\">none</li>'}</ul></td>"
            f"<td>{_render_list(row.get('gaps'), 5)}</td>"
            "</tr>"
        )
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ParkPulse Issue Coverage Matrix</title>
  <style>
    :root {{ color-scheme: light; --ink:#17212b; --muted:#65717f; --line:#d9e1e8; --bg:#f6f8fa; --panel:#ffffff; --ok:#147a47; --warn:#9a5b00; --bad:#b42318; --generic:#596579; }}
    body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ padding:28px 36px 18px; background:#102434; color:white; }}
    h1 {{ margin:0 0 8px; font-size:28px; letter-spacing:0; }}
    h2 {{ margin:28px 0 12px; font-size:20px; }}
    p {{ margin:0 0 10px; color:inherit; }}
    main {{ padding:22px 36px 40px; }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap:12px; }}
    .metric {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
    .metric strong {{ display:block; font-size:24px; }}
    .metric span {{ color:var(--muted); font-size:13px; }}
    table {{ width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th, td {{ border-bottom:1px solid var(--line); padding:12px; text-align:left; vertical-align:top; font-size:13px; }}
    th {{ background:#eaf0f5; font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:#40505f; }}
    ul {{ margin:6px 0 8px 18px; padding:0; }}
    li {{ margin:2px 0; }}
    .muted {{ color:var(--muted); font-size:12px; }}
    .badge {{ display:inline-block; border-radius:999px; padding:3px 9px; font-weight:700; font-size:12px; color:white; }}
    .strong {{ background:var(--ok); }}
    .weak {{ background:var(--warn); }}
    .generic {{ background:var(--generic); }}
    .failed {{ background:var(--bad); }}
    footer {{ padding:20px 36px; color:var(--muted); font-size:12px; }}
  </style>
</head>
<body>
  <header>
    <h1>ParkPulse Issue Coverage Matrix</h1>
    <p>One targeted live-feed decision loop per issue kind. Strong means the issue had first-round issue-specific negotiation, at least one matching bounded action path, no ownerless follow-up, and policy gates preserved sensitive actions.</p>
  </header>
  <main>
    <section class="grid">
      <div class="metric"><strong>{html.escape(str(summary.get('issue_count')))}</strong><span>Issue kinds tested</span></div>
      <div class="metric"><strong>{html.escape(str(summary.get('strong_count')))}</strong><span>Strong families</span></div>
      <div class="metric"><strong>{html.escape(str(summary.get('weak_count')))}</strong><span>Weak families</span></div>
      <div class="metric"><strong>{html.escape(str(summary.get('generic_count')))}</strong><span>Generic families</span></div>
      <div class="metric"><strong>{html.escape(str(summary.get('failed_count')))}</strong><span>Failed families</span></div>
      <div class="metric"><strong>{html.escape(str(summary.get('executed_count')))}</strong><span>Controlled executions</span></div>
      <div class="metric"><strong>{html.escape(str(summary.get('held_count')))}</strong><span>Held/gated actions</span></div>
      <div class="metric"><strong>{html.escape(str(summary.get('case_bank_total_case_count')))}</strong><span>Case bank total after run</span></div>
    </section>
    <h2>Gap Table</h2>
    <table>
      <thead>
        <tr>
          <th>Issue</th>
          <th>Grade</th>
          <th>Board</th>
          <th>Issue-Specific Action</th>
          <th>Fit</th>
          <th>First Negotiation</th>
          <th>Remaining Gap</th>
        </tr>
      </thead>
      <tbody>
        {''.join(table_rows)}
      </tbody>
    </table>
  </main>
  <footer>Generated {html.escape(str(report.get('created_at')))}. JSON: {html.escape(str(path.with_suffix('.json')))}</footer>
</body>
</html>
"""
    path.write_text(html_doc, encoding="utf-8")


async def _async_main(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = _now_iso()
    case_bank_dir = Path(args.case_bank_dir)
    starting_case_bank_rows = cycle_runner._read_case_bank_rows(case_bank_dir)
    catalog = cycle_runner.DIVERSITY_EVENT_CATALOG
    if args.only_issue_kind:
        wanted = {item.strip() for item in args.only_issue_kind.split(",") if item.strip()}
        catalog = [item for item in catalog if str(item.get("kind")) in wanted]
    if args.max_issues:
        catalog = catalog[: args.max_issues]

    cycles: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(catalog, 1):
        kind = str(item["kind"])
        try:
            result = await cycle_runner._run_cycle(
                index,
                output_dir,
                record_ledger=not args.no_ledger,
                diversity_control=True,
                case_bank_rows=starting_case_bank_rows,
                batch_summaries=[row["summary"] for row in cycles],
                agent_timeout_seconds=args.agent_timeout_seconds,
                forced_issue_kind=kind,
                forced_target_id=str(item.get("target_id") or ""),
                forced_intensity=_safe_int(item.get("intensity"), 75),
            )
            cycles.append(result)
            row = _coverage_row(result)
            print(json.dumps({"issue": kind, "grade": row["grade"], "alignment": row["alignment_status"]}, sort_keys=True))
        except Exception as error:
            errors.append({"issue_kind": kind, "error": f"{type(error).__name__}: {error}"})
            print(json.dumps({"issue": kind, "grade": "failed", "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
            if not args.continue_on_error:
                raise

    cycle_summaries = [row["summary"] for row in cycles]
    case_bank = cycle_runner._append_case_bank(
        cycle_summaries,
        case_bank_dir=case_bank_dir,
        batch_id=output_dir.name or f"issue-coverage-{started_at}",
        output_dir=output_dir,
        min_training_rows=args.min_training_rows,
        min_issue_kinds=args.min_issue_kinds,
        min_targets=args.min_targets,
        max_dominant_issue_ratio=args.max_dominant_issue_ratio,
        min_memory_applied_ratio=args.min_memory_applied_ratio,
    )
    case_bank_summary = case_bank.get("summary", {}) if isinstance(case_bank.get("summary"), dict) else {}
    rows = [_coverage_row(result) for result in cycles]
    for error in errors:
        rows.append(
            {
                "issue_kind": error.get("issue_kind"),
                "target_id": None,
                "intensity": None,
                "grade": "failed",
                "status": "error",
                "alignment_status": "error",
                "template_risk": "high",
                "expected_tools": [],
                "executed_tools": [],
                "held_tools": [],
                "issue_specific_proposal_count": 0,
                "issue_specific_executed": [],
                "issue_specific_held": [],
                "issue_specific_policy_mix": [],
                "proposal_count": 0,
                "negotiation_round_count": 0,
                "executed_count": 0,
                "held_count": 0,
                "memory_applied_count": 0,
                "outcome_id": None,
                "run_json": None,
                "first_issue_specific": [],
                "gaps": [str(error.get("error"))],
            }
        )
    grade_counts = {grade: sum(1 for row in rows if row.get("grade") == grade) for grade in ("strong", "weak", "generic", "failed")}
    summary = {
        "issue_count": len(rows),
        "strong_count": grade_counts["strong"],
        "weak_count": grade_counts["weak"],
        "generic_count": grade_counts["generic"],
        "failed_count": grade_counts["failed"],
        "executed_count": sum(_safe_int(row.get("executed_count")) for row in rows),
        "held_count": sum(_safe_int(row.get("held_count")) for row in rows),
        "memory_applied_count": sum(_safe_int(row.get("memory_applied_count")) for row in rows),
        "case_bank_total_case_count": case_bank_summary.get("total_case_count"),
        "case_bank_added_count": case_bank_summary.get("added_count"),
        "case_bank_duplicate_count": case_bank_summary.get("duplicate_count"),
    }
    report = {
        "status": "passed" if rows and not errors and grade_counts["weak"] == 0 and grade_counts["generic"] == 0 and grade_counts["failed"] == 0 else "review",
        "created_at": _now_iso(),
        "started_at": started_at,
        "summary": summary,
        "rows": rows,
        "errors": errors,
        "case_bank": case_bank_summary,
        "truth_boundaries": [
            "This matrix uses the live park simulator and live-feed persistence, not a real external park.",
            "Each issue is forced once to validate issue-family coverage; agent proposals still ground in refreshed feed event IDs.",
            "Controlled executor actions are internal receiver handoffs only; sensitive actions remain held/gated.",
        ],
    }
    json_path = output_dir / "live-feed-issue-coverage-matrix.json"
    html_path = output_dir / "live-feed-issue-coverage-matrix.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    _render_html(report, html_path)
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary": summary,
                "output_json": str(json_path),
                "output_html": str(html_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one targeted live-feed operating cycle per issue kind and report coverage gaps.")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "output/qa/live-feed-issue-coverage-matrix"))
    parser.add_argument("--case-bank-dir", default=str(REPO_ROOT / "output/qa/live-feed-case-bank"))
    parser.add_argument("--min-training-rows", type=int, default=50)
    parser.add_argument("--min-issue-kinds", type=int, default=12)
    parser.add_argument("--min-targets", type=int, default=6)
    parser.add_argument("--max-dominant-issue-ratio", type=float, default=0.3)
    parser.add_argument("--min-memory-applied-ratio", type=float, default=0.45)
    parser.add_argument("--agent-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-issues", type=int, default=None, help="Debug helper: run only the first N catalog issues.")
    parser.add_argument("--only-issue-kind", default=None, help="Comma-separated issue kinds for targeted debugging.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue matrix generation if one issue kind fails.")
    parser.add_argument("--no-ledger", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
