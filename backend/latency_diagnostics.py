from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from copy import deepcopy
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Callable


_PROBE_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="parkpulse-latency-probe")
_PERSIST_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="parkpulse-latency-persist")
_IMPORT_PROFILE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="parkpulse-import-profile")
_PROBE_LOCK = threading.Lock()
_PERSIST_LOCK = threading.Lock()
_IMPORT_PROFILE_LOCK = threading.Lock()
_PROBE_CACHE: dict[str, dict[str, Any]] = {}
_PROBE_FUTURES: dict[str, Future[Any]] = {}
_PROBE_FAILURES: dict[str, int] = {}
_PROBE_CIRCUIT_OPENED_AT: dict[str, float] = {}
_PERSIST_FUTURE: Future[Any] | None = None
_PERSIST_LAST: dict[str, Any] = {"status": "never_run"}
_IMPORT_PROFILE_FUTURE: Future[Any] | None = None
_IMPORT_PROFILE_CACHE: dict[str, Any] = {"status": "never_run", "module": "parkpulse_api"}
_PROBE_STALE_SECONDS = float(os.getenv("PARKPULSE_LATENCY_PROBE_STALE_SECONDS", "300"))
_PROBE_CIRCUIT_FAILURE_THRESHOLD = int(float(os.getenv("PARKPULSE_LATENCY_PROBE_FAILURE_THRESHOLD", "2")))
_PROBE_CIRCUIT_RECOVERY_SECONDS = float(os.getenv("PARKPULSE_LATENCY_PROBE_CIRCUIT_RECOVERY_SECONDS", "120"))
_IMPORT_PROFILE_TIMEOUT_SECONDS = float(os.getenv("PARKPULSE_IMPORT_PROFILE_TIMEOUT_SECONDS", "30"))
_IMPORT_PROFILE_STALE_SECONDS = float(os.getenv("PARKPULSE_IMPORT_PROFILE_STALE_SECONDS", "900"))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _cache_probe_result(name: str, result: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    result.setdefault("probe", name)
    result.setdefault("finished_at", _now_iso())
    result.setdefault("finished_epoch", now)
    with _PROBE_LOCK:
        _PROBE_CACHE[name] = result
        _PROBE_FUTURES.pop(name, None)
        if result.get("status") in {"ok", "disabled"}:
            _PROBE_FAILURES[name] = 0
            _PROBE_CIRCUIT_OPENED_AT.pop(name, None)
        elif result.get("status") not in {"running", "skipped"}:
            failures = int(_PROBE_FAILURES.get(name, 0)) + 1
            _PROBE_FAILURES[name] = failures
            if failures >= _PROBE_CIRCUIT_FAILURE_THRESHOLD:
                _PROBE_CIRCUIT_OPENED_AT[name] = now
    return result


def _run_probe(name: str, operation) -> dict[str, Any]:
    started_epoch = time.time()
    started_ms = _epoch_ms()
    try:
        result = operation()
        status = str(result.get("status") or "ok") if isinstance(result, dict) else "ok"
        payload = result if isinstance(result, dict) else {"result": result}
        payload["status"] = status
        payload["duration_ms"] = _epoch_ms() - started_ms
        return _cache_probe_result(name, payload)
    except Exception as error:
        return _cache_probe_result(
            name,
            {
                "status": "failed",
                "duration_ms": _epoch_ms() - started_ms,
                "error": str(error)[:500],
                "started_epoch": started_epoch,
            },
        )


def _probe_circuit_state(name: str) -> str:
    opened = _PROBE_CIRCUIT_OPENED_AT.get(name)
    if opened is None:
        return "closed"
    if time.time() - opened >= _PROBE_CIRCUIT_RECOVERY_SECONDS:
        return "half_open"
    return "open"


def _probe_is_fresh(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    finished_epoch = _number(row.get("finished_epoch"), 0)
    return finished_epoch > 0 and time.time() - finished_epoch <= _PROBE_STALE_SECONDS


def _probe_mongo() -> dict[str, Any]:
    if not (os.getenv("MONGODB_URI") or os.getenv("MONGODB_DIRECT_URI")):
        return {"status": "disabled", "reason": "Mongo URI is not configured."}
    from mongo_memory import init_operational_memory

    status = init_operational_memory()
    return {
        "status": "ok" if status.get("connected") else "degraded",
        "mode": status.get("mode"),
        "connected": status.get("connected"),
        "errors": status.get("errors", [])[:2] if isinstance(status.get("errors"), list) else [],
    }


def _probe_bigquery() -> dict[str, Any]:
    if not (_env_enabled("PARKPULSE_LIVE_BIGQUERY") or _env_enabled("PARKPULSE_COLLABORATION_LIVE_BIGQUERY")):
        return {"status": "disabled", "reason": "Live BigQuery export is not enabled."}
    from bigquery_analytics import bigquery_status

    status = bigquery_status()
    return {
        "status": "ok" if status.get("ready") else "degraded",
        "mode": status.get("mode"),
        "ready": status.get("ready"),
        "dataset": status.get("dataset"),
        "readiness_issues": status.get("readiness_issues", [])[:3],
    }


def _probe_vertex() -> dict[str, Any]:
    if not _env_enabled("ENABLE_VERTEX_GENAI_EVAL"):
        return {"status": "disabled", "reason": "Vertex GenAI eval is not enabled."}
    from evaluator_loop import evaluator_loop_status, run_vertex_hosted_evaluation

    status = evaluator_loop_status()
    if not _env_enabled("PARKPULSE_LATENCY_PROBE_VERTEX_LIVE"):
        return {
            "status": "ok" if status.get("status") in {"ready", "configured"} else "degraded",
            "mode": "status_probe",
            "provider": status.get("provider"),
            "hosted_configured": status.get("hosted_configured"),
            "hosted_trigger_enabled": status.get("hosted_trigger_enabled"),
            "readiness_issues": status.get("readiness_issues", [])[:3],
        }
    result = run_vertex_hosted_evaluation(
        {
            "scenario_key": "latency_probe",
            "decision_id": "latency-probe",
            "overall": 90,
            "scorecard_status": "passed",
            "response_score": 88,
            "response_status": "latency_probe",
            "dimension_scores": {"Groundedness": 90, "Safety": 95, "Actionability": 90},
            "dimension_explanations": {"Groundedness": "Probe payload.", "Safety": "Probe payload.", "Actionability": "Probe payload."},
            "failure_reasons": [],
            "selected_action": {"label": "Latency probe"},
            "governance": {"gate_status": "clear", "allowed": True, "findings": []},
            "response_metrics": {"status": "latency_probe", "score": 88, "takeRate": 0.8, "positiveResponseRate": 0.9, "reactiveFollowThroughRate": 0.85},
        }
    )
    return {
        "status": "ok" if result.get("status") == "completed" else "degraded",
        "mode": "live_evaluate_instances_probe",
        "transport": result.get("transport"),
        "provider": result.get("provider"),
        "vertex_status": result.get("status"),
        "reason": result.get("reason"),
    }


_PROBES = {
    "mongo": _probe_mongo,
    "vertex": _probe_vertex,
    "bigquery": _probe_bigquery,
}


def trigger_latency_probes(*, force: bool = False, probe_names: list[str] | None = None) -> dict[str, Any]:
    names = probe_names or list(_PROBES.keys())
    started: list[str] = []
    skipped: dict[str, str] = {}
    now = time.time()
    with _PROBE_LOCK:
        for name in names:
            if name not in _PROBES:
                skipped[name] = "unknown_probe"
                continue
            circuit = _probe_circuit_state(name)
            if circuit == "open" and not force:
                skipped[name] = "circuit_open"
                continue
            future = _PROBE_FUTURES.get(name)
            if future is not None and not future.done():
                skipped[name] = "already_running"
                continue
            cached = _PROBE_CACHE.get(name)
            if not force and _probe_is_fresh(cached):
                skipped[name] = "fresh"
                continue
            if circuit == "half_open":
                _PROBE_CIRCUIT_OPENED_AT.pop(name, None)
            _PROBE_CACHE[name] = {
                "probe": name,
                "status": "running",
                "started_at": _now_iso(),
                "started_epoch": now,
                "previous": cached,
            }
            _PROBE_FUTURES[name] = _PROBE_EXECUTOR.submit(_run_probe, name, _PROBES[name])
            started.append(name)
    return {"started": started, "skipped": skipped}


def latency_probe_snapshot() -> dict[str, Any]:
    with _PROBE_LOCK:
        rows = {name: dict(_PROBE_CACHE.get(name, {"probe": name, "status": "never_run"})) for name in _PROBES}
        for name, row in rows.items():
            future = _PROBE_FUTURES.get(name)
            if future is not None and not future.done():
                row["status"] = "running"
            row["fresh"] = _probe_is_fresh(row)
            row["circuit_state"] = _probe_circuit_state(name)
            row["failure_count"] = int(_PROBE_FAILURES.get(name, 0))
        return {
            "status": "ready",
            "stale_seconds": _PROBE_STALE_SECONDS,
            "circuit_failure_threshold": _PROBE_CIRCUIT_FAILURE_THRESHOLD,
            "circuit_recovery_seconds": _PROBE_CIRCUIT_RECOVERY_SECONDS,
            "probes": rows,
        }


def _parse_importtime(stderr: str, limit: int = 16) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(r"^import time:\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|\s*(.+?)\s*$")
    for line in stderr.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        self_us = int(match.group(1))
        cumulative_us = int(match.group(2))
        module = match.group(3).strip()
        if module.startswith("["):
            continue
        rows.append(
            {
                "module": module,
                "self_ms": round(self_us / 1000, 3),
                "cumulative_ms": round(cumulative_us / 1000, 3),
            }
        )
    return {
        "top_self": sorted(rows, key=lambda row: row["self_ms"], reverse=True)[:limit],
        "top_cumulative": sorted(rows, key=lambda row: row["cumulative_ms"], reverse=True)[:limit],
        "module_count": len(rows),
    }


def _run_import_profile(module_name: str = "parkpulse_api") -> dict[str, Any]:
    started_ms = _epoch_ms()
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = backend_dir if not existing_pythonpath else f"{backend_dir}{os.pathsep}{existing_pythonpath}"
    try:
        result = subprocess.run(
            [sys.executable, "-X", "importtime", "-c", f"import {module_name}"],
            cwd=backend_dir,
            env=env,
            text=True,
            capture_output=True,
            timeout=_IMPORT_PROFILE_TIMEOUT_SECONDS,
            check=False,
        )
        parsed = _parse_importtime(result.stderr)
        status = "ok" if result.returncode == 0 else "failed"
        payload = {
            "status": status,
            "module": module_name,
            "duration_ms": _epoch_ms() - started_ms,
            "returncode": result.returncode,
            "finished_at": _now_iso(),
            "finished_epoch": time.time(),
            **parsed,
        }
        if result.returncode != 0:
            payload["stderr_tail"] = result.stderr.splitlines()[-12:]
        return payload
    except subprocess.TimeoutExpired as error:
        return {
            "status": "timeout",
            "module": module_name,
            "duration_ms": _epoch_ms() - started_ms,
            "timeout_seconds": _IMPORT_PROFILE_TIMEOUT_SECONDS,
            "finished_at": _now_iso(),
            "finished_epoch": time.time(),
            "stderr_tail": (error.stderr or "").splitlines()[-12:] if isinstance(error.stderr, str) else [],
        }
    except Exception as error:
        return {
            "status": "failed",
            "module": module_name,
            "duration_ms": _epoch_ms() - started_ms,
            "error": str(error)[:300],
            "finished_at": _now_iso(),
            "finished_epoch": time.time(),
        }


def trigger_import_profile(*, force: bool = False, module_name: str = "parkpulse_api") -> dict[str, Any]:
    global _IMPORT_PROFILE_FUTURE, _IMPORT_PROFILE_CACHE
    now = time.time()
    with _IMPORT_PROFILE_LOCK:
        future = _IMPORT_PROFILE_FUTURE
        if future is not None and not future.done():
            return {"started": False, "skipped": "already_running"}
        finished_epoch = _number(_IMPORT_PROFILE_CACHE.get("finished_epoch"), 0)
        if not force and finished_epoch > 0 and now - finished_epoch <= _IMPORT_PROFILE_STALE_SECONDS:
            return {"started": False, "skipped": "fresh"}
        _IMPORT_PROFILE_CACHE = {
            "status": "running",
            "module": module_name,
            "started_at": _now_iso(),
            "started_epoch": now,
            "previous": _IMPORT_PROFILE_CACHE,
        }

        def _profile_and_cache() -> dict[str, Any]:
            global _IMPORT_PROFILE_CACHE
            payload = _run_import_profile(module_name)
            with _IMPORT_PROFILE_LOCK:
                _IMPORT_PROFILE_CACHE = payload
            return payload

        _IMPORT_PROFILE_FUTURE = _IMPORT_PROFILE_EXECUTOR.submit(_profile_and_cache)
        return {"started": True, "module": module_name}


def import_profile_snapshot() -> dict[str, Any]:
    with _IMPORT_PROFILE_LOCK:
        row = dict(_IMPORT_PROFILE_CACHE)
        future = _IMPORT_PROFILE_FUTURE
        if future is not None and not future.done():
            row["status"] = "running"
        row["fresh"] = _number(row.get("finished_epoch"), 0) > 0 and time.time() - _number(row.get("finished_epoch"), 0) <= _IMPORT_PROFILE_STALE_SECONDS
        row["stale_seconds"] = _IMPORT_PROFILE_STALE_SECONDS
        return row


def latency_history_payload(rows: list[dict[str, Any]], limit: int = 10) -> dict[str, Any]:
    diagnostics_rows = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("documentType") == "latency_diagnostics"
    ][: max(1, limit)]
    trend_rows: list[dict[str, Any]] = []
    cause_counts: dict[str, int] = {}
    max_probe_duration_ms = 0
    max_probe_name = ""

    for row in diagnostics_rows:
        summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
        top_cause = summary.get("top_cause", {}) if isinstance(summary.get("top_cause"), dict) else {}
        timings = row.get("timings", {}) if isinstance(row.get("timings"), dict) else {}
        probes = timings.get("dependency_probes", {}) if isinstance(timings.get("dependency_probes"), dict) else {}
        durations: dict[str, int] = {}
        statuses: dict[str, str] = {}
        for name, probe in probes.items():
            if not isinstance(probe, dict):
                continue
            statuses[str(name)] = str(probe.get("status") or "unknown")
            duration_ms = int(_number(probe.get("duration_ms"), -1))
            if duration_ms >= 0:
                durations[str(name)] = duration_ms
                if duration_ms > max_probe_duration_ms:
                    max_probe_duration_ms = duration_ms
                    max_probe_name = str(name)
        cause_id = str(top_cause.get("id") or "unknown")
        cause_counts[cause_id] = cause_counts.get(cause_id, 0) + 1
        trend_rows.append(
            {
                "id": row.get("_id"),
                "created_at": row.get("createdAt") or row.get("checked_at"),
                "status": row.get("status"),
                "top_cause_id": cause_id,
                "top_cause": top_cause.get("label"),
                "severity": top_cause.get("severity"),
                "full_runtime_status": summary.get("full_runtime_status"),
                "probe_durations_ms": durations,
                "probe_statuses": statuses,
            }
        )

    recurring_causes = sorted(cause_counts.items(), key=lambda item: item[1], reverse=True)
    return {
        "status": "ready",
        "sample_count": len(trend_rows),
        "summary": {
            "latest_status": trend_rows[0].get("status") if trend_rows else None,
            "latest_top_cause_id": trend_rows[0].get("top_cause_id") if trend_rows else None,
            "recurring_top_cause_id": recurring_causes[0][0] if recurring_causes else None,
            "recurring_top_cause_count": recurring_causes[0][1] if recurring_causes else 0,
            "max_probe_name": max_probe_name or None,
            "max_probe_duration_ms": max_probe_duration_ms or None,
        },
        "rows": trend_rows,
    }


def schedule_latency_diagnostics_persist(
    diagnostics: dict[str, Any],
    persist_fn: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    global _PERSIST_FUTURE, _PERSIST_LAST
    queued_at = _now_iso()
    snapshot = deepcopy(diagnostics)

    def _persist() -> dict[str, Any]:
        global _PERSIST_LAST
        try:
            document_id = persist_fn(snapshot)
            result = {
                "status": "stored",
                "eval_document_id": document_id,
                "collection": "eval_results",
                "stored_at": _now_iso(),
            }
        except Exception as error:
            result = {
                "status": "failed",
                "collection": "eval_results",
                "error": str(error)[:300],
                "stored_at": _now_iso(),
            }
        with _PERSIST_LOCK:
            _PERSIST_LAST = result
        return result

    with _PERSIST_LOCK:
        if _PERSIST_FUTURE is not None and not _PERSIST_FUTURE.done():
            return {
                "status": "skipped",
                "reason": "persist_in_flight",
                "collection": "eval_results",
                "queued_at": queued_at,
                "last": dict(_PERSIST_LAST),
            }
        _PERSIST_FUTURE = _PERSIST_EXECUTOR.submit(_persist)
        return {
            "status": "queued",
            "collection": "eval_results",
            "queued_at": queued_at,
            "last": dict(_PERSIST_LAST),
        }


def _receipt_payloads(receipts: dict[str, Any] | None, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(receipts, dict):
        return []
    rows: list[dict[str, Any]] = []
    for item in receipts.values():
        if isinstance(item, dict) and isinstance(item.get("payload"), dict):
            rows.append(item["payload"])
    return rows[:limit]


def _workflow_slow_points(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for payload in payloads:
        telemetry = payload.get("run_telemetry", {}) if isinstance(payload.get("run_telemetry"), dict) else payload
        workflow = telemetry.get("agent_workflow", {}) if isinstance(telemetry.get("agent_workflow"), dict) else {}
        receipt = payload.get("run_receipt", {}) if isinstance(payload.get("run_receipt"), dict) else {}
        for stage in workflow.get("stages", []) if isinstance(workflow.get("stages"), list) else []:
            if not isinstance(stage, dict):
                continue
            points.append(
                {
                    "receipt_id": receipt.get("id"),
                    "stage": stage.get("stage"),
                    "mode": stage.get("mode"),
                    "stage_ms": int(_number(stage.get("stage_ms"))),
                    "elapsed_ms": int(_number(stage.get("elapsed_ms"))),
                    "metadata": {key: value for key, value in stage.items() if key not in {"stage", "mode", "stage_ms", "elapsed_ms"}},
                }
            )
    return sorted(points, key=lambda item: item["stage_ms"], reverse=True)[:8]


def _latest_sweep_slow_points(latest_sweep: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(latest_sweep, dict):
        return []
    points: list[dict[str, Any]] = []
    for row in latest_sweep.get("scenarios", []) if isinstance(latest_sweep.get("scenarios"), list) else []:
        if not isinstance(row, dict):
            continue
        elapsed_ms = int(_number(row.get("elapsed_ms")))
        if elapsed_ms <= 0:
            continue
        points.append(
            {
                "scenario_key": row.get("scenario_key"),
                "elapsed_ms": elapsed_ms,
                "vertex_status": (row.get("vertex", {}) if isinstance(row.get("vertex"), dict) else {}).get("status"),
                "transport": (row.get("vertex", {}) if isinstance(row.get("vertex"), dict) else {}).get("transport"),
            }
        )
    return sorted(points, key=lambda item: item["elapsed_ms"], reverse=True)[:8]


def _cause(
    *,
    cause_id: str,
    label: str,
    status: str,
    severity: str,
    evidence: list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "id": cause_id,
        "label": label,
        "status": status,
        "severity": severity,
        "evidence": evidence,
        "next_action": next_action,
    }


def build_latency_diagnostics(
    *,
    full_runtime: dict[str, Any],
    receipts: dict[str, Any] | None = None,
    latest_sweep: dict[str, Any] | None = None,
    probe_snapshot: dict[str, Any] | None = None,
    import_profile: dict[str, Any] | None = None,
    include_env: bool = False,
) -> dict[str, Any]:
    timeout_tiers = full_runtime.get("timeout_tiers", {}) if isinstance(full_runtime.get("timeout_tiers"), dict) else {}
    receipt_payloads = _receipt_payloads(receipts)
    workflow_points = _workflow_slow_points(receipt_payloads)
    sweep_points = _latest_sweep_slow_points(latest_sweep)
    causes: list[dict[str, Any]] = []
    probes = probe_snapshot.get("probes", {}) if isinstance(probe_snapshot, dict) and isinstance(probe_snapshot.get("probes"), dict) else {}
    import_profile = import_profile if isinstance(import_profile, dict) else {}

    runtime_status = str(full_runtime.get("status") or "unknown")
    load_elapsed_ms = int(_number(full_runtime.get("load_elapsed_ms") or full_runtime.get("load_duration_ms")))
    first_response_ms = int(_number(timeout_tiers.get("agent_run_full_load_seconds"), 1.5) * 1000)
    stale_ms = int(_number(timeout_tiers.get("full_runtime_stale_load_seconds"), 90) * 1000)
    if runtime_status in {"loading", "stale_loading"}:
        severity = "critical" if load_elapsed_ms >= stale_ms else "warning" if load_elapsed_ms >= first_response_ms else "info"
        causes.append(
            _cause(
                cause_id="full_runtime_import",
                label="Full runtime import/load",
                status=runtime_status,
                severity=severity,
                evidence=[
                    f"full_runtime.status={runtime_status}",
                    f"load_elapsed_ms={load_elapsed_ms}",
                    f"first_response_budget_ms={first_response_ms}",
                ],
                next_action="Keep hot routes on lazy contracts and inspect import-time cost before relying on full runtime for first response.",
            )
        )
    elif runtime_status == "failed":
        causes.append(
            _cause(
                cause_id="full_runtime_import",
                label="Full runtime import/load",
                status="failed",
                severity="critical",
                evidence=[str(full_runtime.get("load_error") or "full runtime failed")[:500]],
                next_action="Fix the import/load exception before using full-runtime endpoints.",
            )
        )

    if workflow_points:
        slowest = workflow_points[0]
        severity = "warning" if slowest["stage_ms"] >= 2000 else "info"
        causes.append(
            _cause(
                cause_id="agent_workflow_stage",
                label="Agent workflow stage timing",
                status="measured",
                severity=severity,
                evidence=[f"{slowest.get('stage')} took {slowest['stage_ms']}ms", f"mode={slowest.get('mode')}"],
                next_action="Use the slowest stage list to decide whether memory, Gemini, policy, eval, dispatch, or analytics needs the next timeout wrapper.",
            )
        )

    if sweep_points:
        slowest_sweep = sweep_points[0]
        severity = "warning" if slowest_sweep["elapsed_ms"] >= 10000 else "info"
        causes.append(
            _cause(
                cause_id="vertex_evaluator",
                label="Vertex evaluator latency",
                status="measured",
                severity=severity,
                evidence=[
                    f"{slowest_sweep.get('scenario_key')} evaluator elapsed_ms={slowest_sweep['elapsed_ms']}",
                    f"transport={slowest_sweep.get('transport')}",
                ],
                next_action="Keep scenario sweeps async or sampled; do not block first-response operator actions on multi-scenario Vertex eval.",
            )
        )
    elif _env_enabled("ENABLE_VERTEX_GENAI_EVAL"):
        causes.append(
            _cause(
                cause_id="vertex_evaluator",
                label="Vertex evaluator latency",
                status="configured_unmeasured",
                severity="info",
                evidence=["ENABLE_VERTEX_GENAI_EVAL=true", "No persisted sweep timing found."],
                next_action="Run the Vertex scenario sweep once to capture per-scenario evaluator latency.",
            )
        )

    if os.getenv("MONGODB_URI") or os.getenv("MONGODB_DIRECT_URI"):
        mongo_probe = probes.get("mongo", {}) if isinstance(probes.get("mongo"), dict) else {}
        if mongo_probe.get("status") in {"ok", "degraded", "failed", "running"}:
            severity = "warning" if mongo_probe.get("status") in {"degraded", "failed", "running"} else "info"
            causes.append(
                _cause(
                    cause_id="mongo_initialization",
                    label="Mongo initialization",
                    status=str(mongo_probe.get("status")),
                    severity=severity,
                    evidence=[
                        f"probe_status={mongo_probe.get('status')}",
                        f"duration_ms={mongo_probe.get('duration_ms', 'pending')}",
                        f"mode={mongo_probe.get('mode', 'unknown')}",
                    ],
                    next_action="Keep Mongo off first-response paths when probe is degraded/running; use fallback memory and background warmup.",
                )
            )
        else:
            causes.append(
                _cause(
                    cause_id="mongo_initialization",
                    label="Mongo initialization",
                    status="possible",
                    severity="warning",
                    evidence=["Mongo URI is configured; cold reads can wait for server selection unless using fast fallback helpers."],
                    next_action="Refresh diagnostics to start a background Mongo probe, then use cached probe timing for root cause.",
                )
            )

    vertex_probe = probes.get("vertex", {}) if isinstance(probes.get("vertex"), dict) else {}
    if vertex_probe.get("status") in {"ok", "degraded", "failed", "running"} and not sweep_points:
        severity = "warning" if vertex_probe.get("status") in {"degraded", "failed", "running"} else "info"
        causes.append(
            _cause(
                cause_id="vertex_evaluator",
                label="Vertex evaluator latency",
                status=str(vertex_probe.get("status")),
                severity=severity,
                evidence=[
                    f"probe_status={vertex_probe.get('status')}",
                    f"duration_ms={vertex_probe.get('duration_ms', 'pending')}",
                    f"mode={vertex_probe.get('mode', 'unknown')}",
                ],
                next_action="Use background Vertex eval for proof; do not block operator response on live evaluator latency.",
            )
        )

    if _env_enabled("PARKPULSE_LIVE_BIGQUERY") or _env_enabled("PARKPULSE_COLLABORATION_LIVE_BIGQUERY"):
        bigquery_probe = probes.get("bigquery", {}) if isinstance(probes.get("bigquery"), dict) else {}
        if bigquery_probe.get("status") in {"ok", "degraded", "failed", "running"}:
            severity = "warning" if bigquery_probe.get("status") in {"degraded", "failed", "running"} else "info"
            causes.append(
                _cause(
                    cause_id="bigquery_export",
                    label="BigQuery status/export",
                    status=str(bigquery_probe.get("status")),
                    severity=severity,
                    evidence=[
                        f"probe_status={bigquery_probe.get('status')}",
                        f"duration_ms={bigquery_probe.get('duration_ms', 'pending')}",
                        f"mode={bigquery_probe.get('mode', 'unknown')}",
                    ],
                    next_action="Keep BigQuery export backgrounded unless probe is consistently healthy and below the response budget.",
                )
            )
        else:
            causes.append(
                _cause(
                    cause_id="bigquery_export",
                    label="BigQuery status/export",
                    status="possible",
                    severity="warning",
                    evidence=["Live BigQuery export is enabled."],
                    next_action="Refresh diagnostics to start a background BigQuery probe, then use cached probe timing for root cause.",
                )
            )
    elif probes.get("bigquery", {}).get("status") == "disabled":
        causes.append(
            _cause(
                cause_id="bigquery_export",
                label="BigQuery status/export",
                status="disabled",
                severity="info",
                evidence=["Live BigQuery export is disabled."],
                next_action="No action needed unless you enable live BigQuery export.",
            )
        )

    import_profile_status = str(import_profile.get("status") or "")
    if import_profile_status in {"failed", "timeout"}:
        causes.append(
            _cause(
                cause_id="import_profile_probe",
                label="Submodule import profile",
                status=import_profile_status,
                severity="warning",
                evidence=[
                    f"import_profile.status={import_profile_status}",
                    f"duration_ms={import_profile.get('duration_ms', 'unknown')}",
                ],
                next_action="Run the import profile locally to identify which module import is blocking full-runtime warmup.",
            )
        )

    if not causes:
        causes.append(
            _cause(
                cause_id="no_slow_cause_observed",
                label="No slow cause observed",
                status="clear",
                severity="info",
                evidence=["No slow workflow stage, stale runtime load, or persisted Vertex sweep latency was available."],
                next_action="Run an agent action or Vertex sweep, then refresh diagnostics.",
            )
        )

    cause_rank = {"critical": 0, "warning": 1, "info": 2}
    causes = sorted(causes, key=lambda item: cause_rank.get(str(item.get("severity")), 9))
    payload = {
        "status": "attention" if causes and causes[0]["severity"] in {"critical", "warning"} else "ok",
        "checked_at": _now_iso(),
        "summary": {
            "top_cause": causes[0],
            "full_runtime_status": runtime_status,
            "slow_workflow_stage_count": len(workflow_points),
            "vertex_sweep_timing_count": len(sweep_points),
        },
        "causes": causes,
        "timings": {
            "full_runtime": full_runtime,
            "slowest_workflow_stages": workflow_points,
            "vertex_sweep_scenarios": sweep_points,
            "dependency_probes": probes,
            "import_profile_detail": import_profile,
        },
        "thresholds": {
            "first_response_budget_ms": first_response_ms,
            "stale_full_runtime_ms": stale_ms,
            "slow_stage_warning_ms": 2000,
            "vertex_sweep_warning_ms": 10000,
        },
    }
    if include_env:
        payload["env_flags"] = {
            "vertex_eval_enabled": _env_enabled("ENABLE_VERTEX_GENAI_EVAL"),
            "live_bigquery_enabled": _env_enabled("PARKPULSE_LIVE_BIGQUERY") or _env_enabled("PARKPULSE_COLLABORATION_LIVE_BIGQUERY"),
            "mongo_configured": bool(os.getenv("MONGODB_URI") or os.getenv("MONGODB_DIRECT_URI")),
        }
    payload["gate"] = latency_acceptance_gate(payload)
    return payload


def latency_acceptance_gate(diagnostics: dict[str, Any], *, fail_on_warning: bool | None = None) -> dict[str, Any]:
    fail_on_warning = _env_enabled("PARKPULSE_LATENCY_GATE_FAIL_ON_WARNING") if fail_on_warning is None else fail_on_warning
    timings = diagnostics.get("timings", {}) if isinstance(diagnostics.get("timings"), dict) else {}
    thresholds = diagnostics.get("thresholds", {}) if isinstance(diagnostics.get("thresholds"), dict) else {}
    full_runtime = timings.get("full_runtime", {}) if isinstance(timings.get("full_runtime"), dict) else {}
    probes = timings.get("dependency_probes", {}) if isinstance(timings.get("dependency_probes"), dict) else {}
    import_profile = timings.get("import_profile_detail", {}) if isinstance(timings.get("import_profile_detail"), dict) else {}

    max_stage_ms = int(_number(os.getenv("PARKPULSE_LATENCY_GATE_MAX_STAGE_MS"), _number(thresholds.get("slow_stage_warning_ms"), 2000)))
    max_vertex_ms = int(_number(os.getenv("PARKPULSE_LATENCY_GATE_MAX_VERTEX_SWEEP_MS"), _number(thresholds.get("vertex_sweep_warning_ms"), 10000)))
    max_import_profile_ms = int(_number(os.getenv("PARKPULSE_LATENCY_GATE_MAX_IMPORT_PROFILE_MS"), 30000))
    max_probe_ms = {
        "mongo": int(_number(os.getenv("PARKPULSE_LATENCY_GATE_MAX_MONGO_PROBE_MS"), 3000)),
        "vertex": int(_number(os.getenv("PARKPULSE_LATENCY_GATE_MAX_VERTEX_PROBE_MS"), 5000)),
        "bigquery": int(_number(os.getenv("PARKPULSE_LATENCY_GATE_MAX_BIGQUERY_PROBE_MS"), 5000)),
    }

    blockers: list[str] = []
    warnings: list[str] = []
    for cause in diagnostics.get("causes", []) if isinstance(diagnostics.get("causes"), list) else []:
        severity = str(cause.get("severity") or "")
        cause_id = str(cause.get("id") or "unknown")
        if severity == "critical":
            blockers.append(f"critical:{cause_id}")
        elif severity == "warning":
            warnings.append(f"warning:{cause_id}")

    runtime_status = str(full_runtime.get("status") or "")
    if runtime_status in {"failed", "stale_loading"}:
        blockers.append(f"full_runtime:{runtime_status}")

    for stage in timings.get("slowest_workflow_stages", []) if isinstance(timings.get("slowest_workflow_stages"), list) else []:
        if isinstance(stage, dict) and int(_number(stage.get("stage_ms"))) > max_stage_ms:
            warnings.append(f"stage:{stage.get('stage')}:{stage.get('stage_ms')}ms")

    for row in timings.get("vertex_sweep_scenarios", []) if isinstance(timings.get("vertex_sweep_scenarios"), list) else []:
        if isinstance(row, dict) and int(_number(row.get("elapsed_ms"))) > max_vertex_ms:
            warnings.append(f"vertex_sweep:{row.get('scenario_key')}:{row.get('elapsed_ms')}ms")

    for name, probe in probes.items():
        if not isinstance(probe, dict):
            continue
        status = str(probe.get("status") or "")
        duration = int(_number(probe.get("duration_ms"), -1))
        if status == "failed":
            blockers.append(f"probe:{name}:failed")
        elif status in {"degraded", "running"}:
            warnings.append(f"probe:{name}:{status}")
        if duration >= 0 and duration > max_probe_ms.get(str(name), 5000):
            warnings.append(f"probe:{name}:{duration}ms")

    if import_profile.get("status") in {"failed", "timeout"}:
        warnings.append(f"import_profile:{import_profile.get('status')}")
    if int(_number(import_profile.get("duration_ms"), -1)) > max_import_profile_ms:
        warnings.append(f"import_profile:{import_profile.get('duration_ms')}ms")

    passed = not blockers and not (fail_on_warning and warnings)
    return {
        "status": "passed" if passed else "blocked",
        "mode": "strict" if fail_on_warning else "critical_only",
        "fail_on_warning": fail_on_warning,
        "blockers": blockers,
        "warnings": warnings[:12],
        "budgets": {
            "max_stage_ms": max_stage_ms,
            "max_vertex_sweep_ms": max_vertex_ms,
            "max_import_profile_ms": max_import_profile_ms,
            "max_probe_ms": max_probe_ms,
        },
    }
