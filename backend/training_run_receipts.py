from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

from controlled_training_eval import latest_controlled_training_eval
from controlled_training_generation import latest_controlled_training_pack


def record_training_run_receipt(
    *,
    attempt_type: str,
    request: dict[str, Any] | None = None,
    actual_training: dict[str, Any] | None = None,
    controlled_eval: dict[str, Any] | None = None,
    live_feed_preflight: dict[str, Any] | None = None,
    status: str | None = None,
    readiness_issues: list[str] | None = None,
) -> dict[str, Any]:
    request_payload = request if isinstance(request, dict) else {}
    training = actual_training if isinstance(actual_training, dict) else {}
    preflight = live_feed_preflight if isinstance(live_feed_preflight, dict) else training.get("training_live_feed_preflight", {})
    preflight = preflight if isinstance(preflight, dict) else {}
    eval_report = controlled_eval if isinstance(controlled_eval, dict) else latest_controlled_training_eval()
    pack = latest_controlled_training_pack()
    gcp_ml = training.get("gcp_ml", {}) if isinstance(training.get("gcp_ml"), dict) else {}
    bqml = gcp_ml.get("bigquery_ml_training", {}) if isinstance(gcp_ml.get("bigquery_ml_training"), dict) else {}
    model_ops = training.get("model_ops", {}) if isinstance(training.get("model_ops"), dict) else {}
    promotion_gate = model_ops.get("promotion_gate", {}) if isinstance(model_ops.get("promotion_gate"), dict) else {}
    rollback = model_ops.get("slice_rollback_ledger", {}) if isinstance(model_ops.get("slice_rollback_ledger"), dict) else {}
    receipt = {
        "id": _receipt_id(attempt_type, request_payload, training, eval_report),
        "created_at": _now_iso(),
        "status": status or _receipt_status(training, bqml),
        "mode": "offline_training_run_receipt",
        "attempt_type": attempt_type,
        "request": {
            "run_gcp_training": bool(request_payload.get("run_gcp_training") or request_payload.get("runGcpTraining")),
            "export_live_episodes": bool(request_payload.get("export_live_episodes") or request_payload.get("exportLiveEpisodes")),
            "min_rows": request_payload.get("min_rows") or request_payload.get("minRows"),
        },
        "controlled_pack": {
            "id": pack.get("id"),
            "status": pack.get("status"),
            "artifact_paths": (pack.get("artifacts", {}) if isinstance(pack.get("artifacts"), dict) else {}).get("paths", {}),
        },
        "controlled_eval_gate": {
            "id": eval_report.get("id"),
            "status": eval_report.get("status"),
            "decision": eval_report.get("decision"),
            "passed_role_count": (eval_report.get("summary", {}) if isinstance(eval_report.get("summary"), dict) else {}).get("passed_role_count"),
            "role_count": (eval_report.get("summary", {}) if isinstance(eval_report.get("summary"), dict) else {}).get("role_count"),
            "artifact_paths": (eval_report.get("artifacts", {}) if isinstance(eval_report.get("artifacts"), dict) else {}).get("paths", {}),
        },
        "actual_training": {
            "status": training.get("status"),
            "sample_count": training.get("sample_count"),
            "min_sample_count": training.get("min_sample_count"),
            "uses_generated_data": training.get("uses_generated_data"),
            "source": training.get("source"),
        },
        "gcp_ml": {
            "bigquery_ready": (gcp_ml.get("bigquery", {}) if isinstance(gcp_ml.get("bigquery"), dict) else {}).get("ready"),
            "bigquery_dataset": (gcp_ml.get("bigquery", {}) if isinstance(gcp_ml.get("bigquery"), dict) else {}).get("dataset"),
            "bqml_status": bqml.get("status"),
            "bqml_model_id": bqml.get("model_id"),
            "bqml_job_id": bqml.get("job_id"),
        },
        "promotion": {
            "status": promotion_gate.get("status"),
            "decision": promotion_gate.get("decision"),
            "blockers": promotion_gate.get("blockers", []) if isinstance(promotion_gate.get("blockers"), list) else [],
            "warnings": promotion_gate.get("warnings", []) if isinstance(promotion_gate.get("warnings"), list) else [],
            "rollback_status": rollback.get("status"),
            "rollback_rows": rollback.get("row_count"),
            "promotion_started": False,
        },
        "live_feed_preflight": _live_feed_preflight_receipt(preflight),
        "readiness_issues": readiness_issues if readiness_issues is not None else _readiness_issues(training, eval_report, bqml, preflight),
        "training_rule": "This receipt records a governed offline-training attempt. It does not promote models or mutate rewards.",
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "model_promotion_started": False,
    }
    _append_jsonl(_receipt_log_path(), receipt)
    return {"status": "recorded", "mode": "offline_training_run_receipt", "receipt": receipt}


def training_run_receipt_ledger(limit: int = 80) -> dict[str, Any]:
    rows = _read_jsonl(_receipt_log_path(), limit=limit)
    return {
        "status": "ready" if rows else "empty",
        "mode": "offline_training_run_receipt_ledger",
        "path": _receipt_log_path(),
        "summary": {
            "receipt_count": len(rows),
            "started_count": len([row for row in rows if row.get("status") in {"started", "recently_started", "ready"}]),
            "blocked_count": len([row for row in rows if str(row.get("status") or "").startswith("blocked")]),
            "latest_status": rows[0].get("status") if rows else None,
        },
        "receipts": rows,
        "training_rule": "Receipts are audit evidence only; model promotion remains gated separately.",
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
    }


def _receipt_status(training: dict[str, Any], bqml: dict[str, Any]) -> str:
    if training.get("status") == "blocked":
        return "blocked"
    if bqml.get("status"):
        return str(bqml.get("status"))
    return str(training.get("status") or bqml.get("status") or "recorded")


def _live_feed_preflight_receipt(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": preflight.get("status"),
        "mode": preflight.get("mode"),
        "refresh_status": preflight.get("refresh_status"),
        "requested_sources": preflight.get("requested_sources", []) if isinstance(preflight.get("requested_sources"), list) else [],
        "refreshed_sources": preflight.get("refreshed_sources", []) if isinstance(preflight.get("refreshed_sources"), list) else [],
        "result_count": preflight.get("result_count", 0),
        "before": preflight.get("before") if isinstance(preflight.get("before"), dict) else None,
        "after": preflight.get("after") if isinstance(preflight.get("after"), dict) else None,
        "remaining_issues": preflight.get("remaining_issues", []) if isinstance(preflight.get("remaining_issues"), list) else [],
    }


def _readiness_issues(training: dict[str, Any], eval_report: dict[str, Any], bqml: dict[str, Any], preflight: dict[str, Any] | None = None) -> list[str]:
    issues = []
    if eval_report.get("status") != "passed":
        issues.extend(eval_report.get("readiness_issues", []) if isinstance(eval_report.get("readiness_issues"), list) else [])
    debug = training.get("debug", {}) if isinstance(training.get("debug"), dict) else {}
    issues.extend(debug.get("readiness_issues", []) if isinstance(debug.get("readiness_issues"), list) else [])
    issues.extend(bqml.get("readiness_issues", []) if isinstance(bqml.get("readiness_issues"), list) else [])
    preflight_payload = preflight if isinstance(preflight, dict) else {}
    issues.extend(preflight_payload.get("readiness_issues", []) if isinstance(preflight_payload.get("readiness_issues"), list) else [])
    deduped: list[str] = []
    seen = set()
    for item in issues:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped[:20]


def _receipt_id(attempt_type: str, request: dict[str, Any], training: dict[str, Any], eval_report: dict[str, Any]) -> str:
    payload = {
        "attempt_type": attempt_type,
        "request": request,
        "training_status": training.get("status"),
        "sample_count": training.get("sample_count"),
        "eval_id": eval_report.get("id"),
        "at": time.time(),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"training_run_{hashlib.sha256(encoded).hexdigest()[:18]}"


def _receipt_log_path() -> str:
    return os.getenv("PARKPULSE_TRAINING_RUN_RECEIPT_LOG_PATH", "/tmp/parkpulse/training_run_receipts.jsonl")


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _read_jsonl(path: str, limit: int) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, min(500, int(limit or 80))) :]
    except Exception:
        return []
    rows = []
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
