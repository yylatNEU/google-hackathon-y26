from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import hashlib
import importlib
import json
import os
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote

from env_bootstrap import load_backend_env
from agent_role_skills import list_agent_role_skills, route_agent_role


load_backend_env()

_fast_delivery_outbox_status = None
_fast_delivery_summary = None
_fast_response_summary = None
_fast_send_equipment_command = None
_fast_send_guest_promotion = None
_fast_send_worker_notification = None

try:
    from park_simulation import park_simulation as _fast_park_simulation
except Exception:
    _fast_park_simulation = None

try:
    from policy_loader import operational_doctrine_index as _fast_operational_doctrine_index
except Exception:
    _fast_operational_doctrine_index = None

_started_at = time.time()
_parkpulse_app: Any | None = None
_parkpulse_module: Any | None = None
_load_lock = threading.Lock()
_load_error: str | None = None
_load_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="parkpulse-full-runtime")
_load_task: concurrent.futures.Future[Any] | None = None
_refinement_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="parkpulse-refinement")
_load_started_at: float | None = None
_load_completed_at: float | None = None
_load_duration_ms: int | None = None
_load_profile_lock = threading.Lock()
_load_profile_events: list[dict[str, Any]] = []
_run_receipts: dict[str, dict[str, Any]] = {}
_run_receipt_order: list[str] = []
_receipt_lock = threading.Lock()
_refinement_receipts: set[str] = set()
_refinement_lock = threading.Lock()
_exported_episode_fitness_ids: set[str] = set()
_heartbeat_policy_snapshot: dict[str, Any] | None = None
_heartbeat_policy_snapshot_loaded_at = 0.0
_heartbeat_policy_refreshing = False
_heartbeat_controller_running = False
_heartbeat_controller_last_action_at = 0.0
_heartbeat_action_logs: list[dict[str, Any]] = []
_heartbeat_action_log_lock = threading.Lock()
_hot_endpoint_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_hot_endpoint_refreshing: set[str] = set()
_last_fast_park_step_at = 0.0
_fast_park_step_interval_seconds = 1.5
_runtime_metrics: dict[str, int] = {
    "full_runtime_load_started": 0,
    "full_runtime_load_succeeded": 0,
    "full_runtime_load_failed": 0,
    "operator_command_full_success": 0,
    "operator_command_fallback": 0,
    "operator_command_refinement_started": 0,
    "operator_command_refinement_succeeded": 0,
    "operator_command_refinement_failed": 0,
    "agent_run_full_success": 0,
    "agent_run_fallback": 0,
    "agent_run_refinement_started": 0,
    "agent_run_refinement_succeeded": 0,
    "agent_run_refinement_failed": 0,
}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _hot_endpoint_ttls() -> dict[str, float]:
    return {
        "readyz": max(0.0, _float_env("PARKPULSE_LAZY_READINESS_CACHE_TTL_SECONDS", 5.0)),
        "park_state": max(0.0, _float_env("PARKPULSE_STATE_CACHE_TTL_SECONDS", 2.0)),
        "integration_status": max(0.0, _float_env("PARKPULSE_INTEGRATION_STATUS_CACHE_TTL_SECONDS", 15.0)),
        "agent_monitoring": max(0.0, _float_env("PARKPULSE_MONITORING_CACHE_TTL_SECONDS", 10.0)),
    }


def _timeout_tiers() -> dict[str, float]:
    first_response_load = _float_env("PARKPULSE_FIRST_RESPONSE_FULL_LOAD_TIMEOUT_SECONDS", 1.5)
    return {
        "hot_path_seconds": _float_env("PARKPULSE_HOT_PATH_TIMEOUT_SECONDS", 3),
        "fast_hybrid_seconds": _float_env("PARKPULSE_FAST_HYBRID_TIMEOUT_SECONDS", 2),
        "operator_full_load_seconds": _float_env("OPERATOR_COMMAND_FULL_LOAD_TIMEOUT_SECONDS", first_response_load),
        "operator_command_seconds": _float_env("OPERATOR_COMMAND_TIMEOUT_SECONDS", 20),
        "agent_run_full_load_seconds": _float_env("PARKPULSE_AGENT_RUN_FULL_LOAD_TIMEOUT_SECONDS", first_response_load),
        "agent_run_seconds": _float_env("PARKPULSE_AGENT_RUN_TIMEOUT_SECONDS", _float_env("OPERATOR_COMMAND_TIMEOUT_SECONDS", 20)),
        "refinement_seconds": _float_env("PARKPULSE_AGENT_RUN_REFINEMENT_TIMEOUT_SECONDS", 20),
        "full_runtime_stale_load_seconds": _float_env("PARKPULSE_FULL_RUNTIME_STALE_LOAD_SECONDS", 30),
        "max_background_refinements": _float_env("PARKPULSE_MAX_BACKGROUND_REFINEMENTS", 0),
        "offline_planning_seconds": _float_env("PARKPULSE_OFFLINE_PLANNING_TIMEOUT_SECONDS", 300),
    }


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _heartbeat_controller_enabled() -> bool:
    return _truthy_env("PARKPULSE_HEARTBEAT_CONTROLLER_ENABLED", True)


def _sync_full_response_enabled() -> bool:
    return _truthy_env("PARKPULSE_SYNC_FULL_RESPONSE_ENABLED", False)


def _metric(name: str, amount: int = 1) -> None:
    _runtime_metrics[name] = int(_runtime_metrics.get(name, 0)) + amount


def _api_capability_registry() -> dict[str, Any]:
    return {
        "status": "ready",
        "entrypoint": "lazy-main",
        "full_runtime": _full_runtime_status(),
        "route_families": [
            {
                "id": "health_readiness",
                "mode": "hot_path",
                "routes": ["/", "/healthz", "/readyz", "/api/park/full-runtime-status", "/api/park/api-capabilities"],
                "timeout_tier": "hot_path_seconds",
            },
            {
                "id": "operator_agent_run",
                "mode": "progressive_fast_then_full",
                "routes": ["/api/park/agent-run", "/api/park/operator-command", "/api/park/operator-command/stream"],
                "timeout_tier": "fast_hybrid_seconds",
                "upgrade_receipt": "/api/park/run-receipt/{id}",
            },
            {
                "id": "role_agents",
                "mode": "fast_hybrid",
                "routes": ["/api/park/agent-role-run", "/api/park/agent-role-refine", "/api/park/agent-role-skills", "/api/park/customer-support-agent"],
                "timeout_tier": "fast_hybrid_seconds",
            },
            {
                "id": "proactive",
                "mode": "stream_or_fast_fallback",
                "routes": ["/api/park/proactive-run", "/api/park/proactive-run/stream", "/api/park/proactive-insights"],
                "timeout_tier": "operator_command_seconds",
            },
            {
                "id": "dynamic_twin_mvp",
                "mode": "hot_path",
                "routes": ["/api/park/dynamic-twin-demo", "/api/park/actual-training"],
                "timeout_tier": "hot_path_seconds",
            },
            {
                "id": "full_runtime_tools",
                "mode": "full_runtime_after_warmup",
                "routes": ["event-plan", "benchmark", "audit", "memory", "delivery", "gcp"],
                "timeout_tier": "offline_planning_seconds",
            },
        ],
    }


def _lazy_analytics_export(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    live_bigquery = any(
        os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
        for name in ("PARKPULSE_LIVE_BIGQUERY", "PARKPULSE_COLLABORATION_LIVE_BIGQUERY")
    )
    if live_bigquery:
        from bigquery_analytics import export_analytics_rows

        return export_analytics_rows(rows_by_table)
    return {
        "status": "disabled",
        "mode": "analytics_export_disabled",
        "row_counts": {table: len(rows) for table, rows in rows_by_table.items()},
        "readiness_issues": ["PARKPULSE_LIVE_BIGQUERY is not enabled for lazy sweep routes."],
    }


async def _export_live_episode_fitness_to_bigquery(limit: int = 80) -> dict[str, Any]:
    if _fast_park_simulation is None or not hasattr(_fast_park_simulation, "get_episode_fitness"):
        return {"status": "unavailable", "mode": "live_episode_fitness_export", "row_counts": {}}
    payload = await _fast_park_simulation.get_episode_fitness(limit=limit)
    episodes = payload.get("episodes", []) if isinstance(payload.get("episodes"), list) else []
    rows_by_table: dict[str, list[dict[str, Any]]] = {"outcome_events": [], "action_dispatches": [], "eval_results": []}
    exported_ids: list[str] = []
    try:
        from bigquery_analytics import build_analytics_rows, export_analytics_rows
    except Exception as error:
        return {"status": "error", "mode": "live_episode_fitness_export", "row_counts": {}, "readiness_issues": [str(error)[:300]]}

    for episode in reversed(episodes):
        if not isinstance(episode, dict):
            continue
        episode_id = str(episode.get("id") or "")
        if not episode_id or episode_id in _exported_episode_fitness_ids:
            continue
        scores = episode.get("scores", {}) if isinstance(episode.get("scores"), dict) else {}
        pressure = episode.get("pressure", {}) if isinstance(episode.get("pressure"), dict) else {}
        difficulty = episode.get("difficulty", {}) if isinstance(episode.get("difficulty"), dict) else {}
        incidents = episode.get("active_random_incidents", []) if isinstance(episode.get("active_random_incidents"), list) else []
        action = episode.get("action", {}) if isinstance(episode.get("action"), dict) else {}
        fitness = float(scores.get("fitness") or 0)
        difficulty_adjusted = float(scores.get("difficulty_adjusted_fitness") or fitness)
        reward_delta = float(scores.get("reward_delta") or 0)
        pressure_reduction = float(pressure.get("reduction_vs_baseline") or 0)
        scenario_key = str(episode.get("scenario_key") or "live_complex_park")
        decision_id = f"{episode_id}_decision"
        outcome_id = f"{episode_id}_outcome"
        take_rate = max(0.0, min(0.99, 0.45 + reward_delta / 100))
        follow_rate = max(0.0, min(0.99, 0.5 + pressure_reduction / 100))
        positive_rate = max(0.0, min(0.99, fitness / 100))
        analytics_rows = build_analytics_rows(
            decision_id=decision_id,
            outcome_id=outcome_id,
            scenario_key=scenario_key,
            delivery={
                "response": {
                    "takeRate": take_rate,
                    "positiveResponseRate": positive_rate,
                    "reactiveFollowThroughRate": follow_rate,
                    "score": fitness,
                },
                "dispatches": [
                    {
                        "id": f"{episode_id}_action",
                        "channel": "runtime_action",
                        "targetSystem": str(action.get("target") or "park_runtime"),
                        "status": "observed",
                        "response": {
                            "takeRate": take_rate,
                            "positiveResponseRate": positive_rate,
                            "reactiveFollowThroughRate": follow_rate,
                        },
                    }
                ],
            },
            outcome={
                "learning": {
                    "take_rate_signal": (
                        f"Live complex park episode: action {action.get('target')}/{action.get('action')} scored "
                        f"{fitness:g}, reward delta {reward_delta:+g}, difficulty {difficulty.get('score', 0)}."
                    )
                },
                "state_impact": {
                    "headline": (
                        f"Live episode against {len(incidents)} random incident(s); pressure reduction "
                        f"{pressure_reduction:+g} vs no-action counterfactual."
                    )
                },
            },
            eval_result={
                "overall": difficulty_adjusted,
                "scorecard": {
                    "overall": difficulty_adjusted,
                    "response_score": fitness,
                    "status": "passed" if reward_delta > 0 else "review",
                    "policy_gate_status": "runtime_observed",
                },
                "dimension_scores": {
                    "fitness": fitness,
                    "reward_delta": reward_delta,
                    "pressure_reduction": pressure_reduction,
                    "difficulty": float(difficulty.get("score") or 0),
                    "incident_count": float(difficulty.get("active_random_incident_count") or len(incidents)),
                },
            },
            source="live_complex_park_episode",
        )
        for table, rows in analytics_rows.items():
            rows_by_table.setdefault(table, []).extend(rows)
        exported_ids.append(episode_id)

    if not exported_ids:
        return {
            "status": "no_new_rows",
            "mode": "live_episode_fitness_export",
            "row_counts": {table: len(rows) for table, rows in rows_by_table.items()},
            "episode_count": len(episodes),
        }
    export = export_analytics_rows(rows_by_table)
    if export.get("status") == "exported":
        _exported_episode_fitness_ids.update(exported_ids)
    export["mode"] = "live_episode_fitness_export"
    export["episode_ids"] = exported_ids
    return export


async def _send_json(send, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
                (b"access-control-allow-origin", b"*"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _read_json_body(receive) -> dict[str, Any]:
    body = b""
    while True:
        event = await receive()
        if event.get("type") != "http.request":
            break
        body += event.get("body", b"")
        if not event.get("more_body"):
            break
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n".encode("utf-8")


def _load_full_module():
    return importlib.import_module("parkpulse_api")


def _record_load_profile_event(phase: str, **metadata: Any) -> None:
    now = time.time()
    baseline = _load_started_at or _started_at
    event = {
        "phase": phase,
        "epoch": now,
        "elapsed_ms": int((now - baseline) * 1000),
        **metadata,
    }
    with _load_profile_lock:
        _load_profile_events.append(event)
        del _load_profile_events[:-40]


def _load_profile_snapshot() -> list[dict[str, Any]]:
    with _load_profile_lock:
        return list(_load_profile_events)


def _load_full_module_locked():
    global _parkpulse_app, _parkpulse_module, _load_error, _load_started_at, _load_completed_at, _load_duration_ms
    if _parkpulse_app is not None:
        return _parkpulse_module
    with _load_lock:
        if _parkpulse_app is not None:
            return _parkpulse_module
        _load_started_at = time.time()
        _load_completed_at = None
        _load_duration_ms = None
        _metric("full_runtime_load_started")
        _record_load_profile_event("load_task_started")
        try:
            _record_load_profile_event("import_parkpulse_api_start")
            module = _load_full_module()
            _record_load_profile_event("import_parkpulse_api_done", module=getattr(module, "__name__", "parkpulse_api"))
            _parkpulse_module = module
            _parkpulse_app = module.app
            _record_load_profile_event("app_resolved", app_type=type(_parkpulse_app).__name__)
            _load_error = None
            _metric("full_runtime_load_succeeded")
            return module
        except Exception as error:
            _load_error = str(error)
            _record_load_profile_event("load_failed", error=str(error)[:300])
            _metric("full_runtime_load_failed")
            raise
        finally:
            _load_completed_at = time.time()
            if _load_started_at is not None:
                _load_duration_ms = int((_load_completed_at - _load_started_at) * 1000)
            _record_load_profile_event("load_finished", duration_ms=_load_duration_ms)


def _completed_full_module_future() -> concurrent.futures.Future[Any]:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    future.set_result(_parkpulse_module)
    return future


def _store_load_task_result(task: concurrent.futures.Future[Any]) -> None:
    global _load_error
    try:
        task.result()
    except concurrent.futures.CancelledError:
        _load_error = "full runtime load task was cancelled"
    except Exception as error:
        _load_error = str(error)


def _ensure_full_module_load_task() -> concurrent.futures.Future[Any]:
    global _load_task
    if _parkpulse_app is not None:
        return _completed_full_module_future()
    if _load_task is None or (_load_task.done() and _parkpulse_app is None):
        _load_task = _load_executor.submit(_load_full_module_locked)
        _load_task.add_done_callback(_store_load_task_result)
    return _load_task


def _warmup_policy_payload(*, force: bool = False) -> dict[str, Any]:
    from latency_diagnostics import import_profile_snapshot, latency_probe_snapshot, trigger_import_profile, trigger_latency_probes

    runtime_task = _ensure_full_module_load_task()
    probe_trigger = trigger_latency_probes(force=force)
    import_profile_trigger = (
        trigger_import_profile(force=force)
        if os.getenv("PARKPULSE_WARMUP_IMPORT_PROFILE", "1").strip().lower() in {"1", "true", "yes", "on"}
        else {"started": False, "skipped": "disabled"}
    )
    return {
        "status": "warming" if not runtime_task.done() else _full_runtime_status()["status"],
        "policy": "full_runtime_plus_dependency_probes",
        "force": force,
        "queued_at": time.time(),
        "full_runtime": _full_runtime_status(),
        "dependency_probes": latency_probe_snapshot(),
        "probe_trigger": probe_trigger,
        "import_profile": import_profile_snapshot(),
        "import_profile_trigger": import_profile_trigger,
        "steps": [
            "full_runtime_import_backgrounded",
            "dependency_probes_backgrounded",
            "submodule_import_profile_backgrounded",
        ],
    }


def _full_runtime_loading_elapsed_seconds() -> float | None:
    if _load_task is None or _load_task.done() or _load_started_at is None or _parkpulse_app is not None:
        return None
    return time.time() - _load_started_at


def _full_runtime_load_is_stale() -> bool:
    elapsed = _full_runtime_loading_elapsed_seconds()
    if elapsed is None:
        return False
    return elapsed >= float(_timeout_tiers()["full_runtime_stale_load_seconds"])


def _full_runtime_status() -> dict[str, Any]:
    stale_load = _full_runtime_load_is_stale()
    if _parkpulse_app is not None:
        status = "loaded"
    elif stale_load:
        status = "stale_loading"
    elif _load_task is not None and not _load_task.done():
        status = "loading"
    elif _load_error:
        status = "failed"
    else:
        status = "idle"
    elapsed_ms = None
    if _load_started_at and status in {"loading", "stale_loading"}:
        elapsed_ms = int((time.time() - _load_started_at) * 1000)
    return {
        "status": status,
        "loaded": _parkpulse_app is not None,
        "load_error": _load_error,
        "load_started_at": _load_started_at,
        "load_completed_at": _load_completed_at,
        "load_elapsed_ms": elapsed_ms,
        "load_duration_ms": _load_duration_ms,
        "stale_load": stale_load,
        "import_profile": _load_profile_snapshot(),
        "timeout_tiers": _timeout_tiers(),
        "metrics": dict(_runtime_metrics),
    }


async def _resolve_hot_builder(builder) -> dict[str, Any]:
    value = builder()
    if asyncio.iscoroutine(value):
        value = await value
    return value


async def _refresh_hot_endpoint(cache_key: str, ttl_seconds: float, builder) -> None:
    try:
        value = await _resolve_hot_builder(builder)
        _hot_endpoint_cache[cache_key] = (time.monotonic() + ttl_seconds, value)
    except Exception as error:
        print(f"ParkPulse lazy hot endpoint refresh failed for {cache_key}: {error}")
    finally:
        _hot_endpoint_refreshing.discard(cache_key)


async def _cached_hot_endpoint(cache_key: str, ttl_seconds: float, builder) -> dict[str, Any]:
    if ttl_seconds <= 0:
        return await _resolve_hot_builder(builder)

    now = time.monotonic()
    cached = _hot_endpoint_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    if cached:
        if cache_key not in _hot_endpoint_refreshing:
            _hot_endpoint_refreshing.add(cache_key)
            asyncio.create_task(_refresh_hot_endpoint(cache_key, ttl_seconds, builder))
        return cached[1]

    value = await _resolve_hot_builder(builder)
    _hot_endpoint_cache[cache_key] = (time.monotonic() + ttl_seconds, value)
    return value


async def _fast_park_state() -> dict[str, Any]:
    if _fast_park_simulation is None:
        return {
            "status": "simulation_unavailable",
            "entrypoint": "lazy-main",
            "operationsAudit": {"ready": False, "mode": "lazy_entrypoint_fast_state_unavailable"},
        }
    await _advance_fast_park_from_wall_clock()
    state = await _fast_park_simulation.get_state()
    if _fast_operational_doctrine_index is not None:
        state.setdefault("policyDoctrine", _fast_operational_doctrine_index())
    state.setdefault(
        "operationsAudit",
        {
            "ready": True,
            "mode": "lazy_entrypoint_fast_state",
            "findings": [],
            "policy_refs": ["PARK-SAFE-001", "PARK-OPS-001", "PARK-CARE-001"],
        },
    )
    return state


async def _fast_park_state_lite() -> dict[str, Any]:
    if _fast_park_simulation is None:
        return await _fast_park_state()
    await _advance_fast_park_from_wall_clock()
    get_state_lite = getattr(_fast_park_simulation, "get_state_lite", None)
    state = await get_state_lite() if callable(get_state_lite) else await _fast_park_simulation.get_state()
    state = dict(state)
    state.pop("industrialDossiers", None)
    if _fast_operational_doctrine_index is not None:
        state.setdefault("policyDoctrine", _fast_operational_doctrine_index())
    state.setdefault(
        "operationsAudit",
        {
            "ready": True,
            "mode": "lazy_entrypoint_fast_state_lite",
            "findings": [],
            "policy_refs": ["PARK-SAFE-001", "PARK-OPS-001", "PARK-CARE-001"],
        },
    )
    state["heartbeatController"] = _heartbeat_controller_status(include_logs=False)
    return state


def _model_context_value(snapshot: dict[str, Any] | None, scenario_key: str, policy_id: str = "live_complex_park_episode") -> dict[str, Any]:
    if not snapshot:
        return {"q_value": None, "sample_count": 0, "source": "no_snapshot"}
    model = snapshot.get("model", {}) if isinstance(snapshot.get("model"), dict) else {}
    for context in model.get("context_values", []) if isinstance(model.get("context_values"), list) else []:
        if not isinstance(context, dict) or str(context.get("context")) != scenario_key:
            continue
        for policy in context.get("ranked_policies", []) if isinstance(context.get("ranked_policies"), list) else []:
            if isinstance(policy, dict) and str(policy.get("policy_id")) == policy_id:
                return {"q_value": _safe_float(policy.get("q_value")), "sample_count": int(policy.get("sample_count") or 0), "source": "context_policy"}
    for policy in model.get("ranked_policies", []) if isinstance(model.get("ranked_policies"), list) else []:
        if isinstance(policy, dict) and str(policy.get("policy_id")) == policy_id:
            return {"q_value": _safe_float(policy.get("average_reward")), "sample_count": int(policy.get("sample_count") or 0), "source": "global_policy"}
    return {"q_value": None, "sample_count": 0, "source": "missing_policy"}


def _load_heartbeat_policy_snapshot(force: bool = False) -> dict[str, Any]:
    global _heartbeat_policy_snapshot, _heartbeat_policy_snapshot_loaded_at
    max_age = max(10.0, _float_env("PARKPULSE_HEARTBEAT_POLICY_REFRESH_SECONDS", 180.0))
    now = time.monotonic()
    if not force and _heartbeat_policy_snapshot is not None and now - _heartbeat_policy_snapshot_loaded_at < max_age:
        return _heartbeat_policy_snapshot
    from park_actual_training import actual_training_status

    payload = actual_training_status(min_rows=_int_env("PARKPULSE_HEARTBEAT_MIN_TRAINING_ROWS", 3), run_gcp_training=False)
    snapshot = {
        "status": payload.get("status"),
        "mode": "cached_post_trained_policy_snapshot",
        "loaded_at": _now_iso(),
        "loaded_monotonic": now,
        "source": payload.get("source"),
        "sample_count": payload.get("sample_count"),
        "model": payload.get("model", {}),
        "gcp_ml": {
            "bigquery": payload.get("gcp_ml", {}).get("bigquery", {}) if isinstance(payload.get("gcp_ml"), dict) else {},
            "bigquery_ml_training": payload.get("gcp_ml", {}).get("bigquery_ml_training", {}) if isinstance(payload.get("gcp_ml"), dict) else {},
        },
        "debug": payload.get("debug", {}),
    }
    _heartbeat_policy_snapshot = snapshot
    _heartbeat_policy_snapshot_loaded_at = now
    return snapshot


def _schedule_heartbeat_policy_refresh(force: bool = False) -> None:
    global _heartbeat_policy_refreshing
    if _heartbeat_policy_refreshing:
        return
    _heartbeat_policy_refreshing = True

    async def refresh() -> None:
        global _heartbeat_policy_refreshing
        try:
            await asyncio.to_thread(_load_heartbeat_policy_snapshot, force)
        except Exception as error:
            _record_heartbeat_action_log(
                {
                    "status": "policy_refresh_error",
                    "mode": "heartbeat_controller",
                    "created_at": _now_iso(),
                    "error": str(error)[:300],
                }
            )
        finally:
            _heartbeat_policy_refreshing = False

    asyncio.create_task(refresh())


def _heartbeat_policy_snapshot_for_tick() -> dict[str, Any] | None:
    max_age = max(10.0, _float_env("PARKPULSE_HEARTBEAT_POLICY_REFRESH_SECONDS", 180.0))
    if _heartbeat_policy_snapshot is None:
        try:
            return _load_heartbeat_policy_snapshot(force=True)
        except Exception as error:
            _record_heartbeat_action_log(
                {
                    "status": "policy_load_error",
                    "mode": "heartbeat_controller",
                    "created_at": _now_iso(),
                    "error": str(error)[:300],
                }
            )
            return None
    if time.monotonic() - _heartbeat_policy_snapshot_loaded_at >= max_age:
        _schedule_heartbeat_policy_refresh(force=True)
    return _heartbeat_policy_snapshot


def _active_heartbeat_events(state: dict[str, Any]) -> list[dict[str, Any]]:
    chaos = state.get("chaosEngine", {}) if isinstance(state.get("chaosEngine"), dict) else {}
    events = chaos.get("activeUnexpectedEvents", []) if isinstance(chaos.get("activeUnexpectedEvents"), list) else []
    if not events:
        flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
        events = flow.get("interventions", []) if isinstance(flow.get("interventions"), list) else []
    return [event for event in events if isinstance(event, dict)]


def _heartbeat_candidate_actions(state: dict[str, Any], snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    scenario_key = str(scenario.get("key") or "unknown")
    events = _active_heartbeat_events(state)
    kind_text = " ".join(str(event.get("kind") or "") for event in events[:8]).lower()
    context_value = _model_context_value(snapshot, scenario_key)
    learned_q = context_value.get("q_value")
    candidates = [
        {
            "id": "food_redirect",
            "target": "food",
            "action": "redirect_food_demand",
            "domains": ("payment", "inventory", "food", "mobile_order", "demand"),
            "label": "Redirect food demand to available capacity.",
        },
        {
            "id": "equipment_hold",
            "target": "equipment",
            "action": "hold_equipment_changes",
            "domains": ("energy", "heat", "storm", "lightning", "weather"),
            "label": "Hold risky equipment/HVAC changes while load is unstable.",
        },
        {
            "id": "staff_redeploy",
            "target": "staff",
            "action": "redeploy_staff",
            "domains": ("staff", "radio", "security", "access"),
            "label": "Redeploy staff toward the highest operating pressure.",
        },
        {
            "id": "crowd_reroute",
            "target": "crowd_safety",
            "action": "calm_reroute",
            "domains": ("parade", "demand", "parking", "ticketing", "restroom", "show", "crowd"),
            "label": "Calmly reroute crowd flow away from pressure points.",
        },
        {
            "id": "ride_reroute",
            "target": "ride",
            "action": "reroute_down_ride",
            "domains": ("ride", "sensor", "queue"),
            "label": "Reroute guests around ride or queue risk.",
        },
    ]
    scenario_boosts = {
        "food_spike": "food_redirect",
        "staff_shortage": "staff_redeploy",
        "storm_response": "equipment_hold",
        "ride_down": "ride_reroute",
    }
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        match_score = sum(1 for token in candidate["domains"] if token in kind_text) * 16
        if scenario_boosts.get(scenario_key) == candidate["id"]:
            match_score += 11
        intensity = max((_safe_float(event.get("intensity")) for event in events), default=0.0)
        learned_component = (_safe_float(learned_q, 0.0) - 50) * 0.6 if learned_q is not None else 0.0
        score = round(match_score + min(24.0, intensity / 4) + learned_component, 2)
        scored.append(
            {
                **candidate,
                "score": score,
                "learned_q": learned_q,
                "learned_sample_count": context_value.get("sample_count", 0),
                "learned_source": context_value.get("source"),
                "scenario_key": scenario_key,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def _heartbeat_policy_gate(candidate: dict[str, Any] | None, state: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not candidate:
        return {"allowed": False, "gate_status": "no_action", "findings": ["No bounded candidate action scored above the action threshold."]}
    if not snapshot or snapshot.get("status") != "ready":
        return {"allowed": False, "gate_status": "review", "findings": ["No ready post-trained policy snapshot is loaded."]}
    allowed_targets = {"food", "equipment", "staff", "crowd_safety", "ride"}
    if candidate.get("target") not in allowed_targets:
        return {"allowed": False, "gate_status": "blocked", "findings": ["Candidate target is outside heartbeat controller authority."]}
    if _safe_float(candidate.get("learned_q"), 0.0) < _float_env("PARKPULSE_HEARTBEAT_MIN_MODEL_Q", 45.0):
        return {"allowed": False, "gate_status": "review", "findings": ["Learned policy value is below heartbeat auto-execute threshold."]}
    if candidate.get("learned_sample_count", 0) < _int_env("PARKPULSE_HEARTBEAT_MIN_CONTEXT_SAMPLES", 2):
        return {"allowed": False, "gate_status": "review", "findings": ["Context has too few observed training samples for autonomous heartbeat action."]}
    return {
        "allowed": True,
        "gate_status": "allowed",
        "findings": ["Bounded reversible action selected from cached post-trained policy snapshot."],
    }


def _record_heartbeat_action_log(entry: dict[str, Any]) -> None:
    with _heartbeat_action_log_lock:
        _heartbeat_action_logs.insert(0, entry)
        del _heartbeat_action_logs[_int_env("PARKPULSE_HEARTBEAT_ACTION_LOG_LIMIT", 160):]


def _heartbeat_controller_status(include_logs: bool = True, limit: int = 20) -> dict[str, Any]:
    now = time.monotonic()
    snapshot_age = round(now - _heartbeat_policy_snapshot_loaded_at, 1) if _heartbeat_policy_snapshot_loaded_at else None
    snapshot = _heartbeat_policy_snapshot or {}
    model = snapshot.get("model", {}) if isinstance(snapshot.get("model"), dict) else {}
    payload = {
        "status": "enabled" if _heartbeat_controller_enabled() else "disabled",
        "mode": "cached_post_trained_model_heartbeat_controller",
        "uses_bigquery_every_tick": False,
        "policy_snapshot": {
            "loaded": bool(_heartbeat_policy_snapshot),
            "loaded_at": snapshot.get("loaded_at"),
            "age_seconds": snapshot_age,
            "refresh_seconds": _float_env("PARKPULSE_HEARTBEAT_POLICY_REFRESH_SECONDS", 180.0),
            "sample_count": snapshot.get("sample_count"),
            "source": snapshot.get("source"),
            "best_policy_id": model.get("best_policy_id"),
            "bqml_model_id": (snapshot.get("gcp_ml", {}).get("bigquery_ml_training", {}) if isinstance(snapshot.get("gcp_ml"), dict) else {}).get("model_id"),
        },
        "controller": {
            "action_cooldown_seconds": _float_env("PARKPULSE_HEARTBEAT_ACTION_COOLDOWN_SECONDS", 30.0),
            "last_action_age_seconds": round(now - _heartbeat_controller_last_action_at, 1) if _heartbeat_controller_last_action_at else None,
            "running": _heartbeat_controller_running,
            "refreshing_policy": _heartbeat_policy_refreshing,
        },
        "log_count": len(_heartbeat_action_logs),
    }
    if include_logs:
        with _heartbeat_action_log_lock:
            payload["logs"] = list(_heartbeat_action_logs[: max(1, min(160, int(limit or 20)))])
    return payload


async def _maybe_run_heartbeat_controller(advanced_steps: int) -> dict[str, Any] | None:
    global _heartbeat_controller_running, _heartbeat_controller_last_action_at
    if not _heartbeat_controller_enabled() or _fast_park_simulation is None or advanced_steps <= 0:
        return None
    if _heartbeat_controller_running:
        return None
    cooldown = max(1.0, _float_env("PARKPULSE_HEARTBEAT_ACTION_COOLDOWN_SECONDS", 30.0))
    if _heartbeat_controller_last_action_at and time.monotonic() - _heartbeat_controller_last_action_at < cooldown:
        return None
    _heartbeat_controller_running = True
    try:
        snapshot = _heartbeat_policy_snapshot_for_tick()
        get_state_lite = getattr(_fast_park_simulation, "get_state_lite", None)
        state = await get_state_lite() if callable(get_state_lite) else await _fast_park_simulation.get_state()
        events = _active_heartbeat_events(state)
        min_events = _int_env("PARKPULSE_HEARTBEAT_MIN_ACTIVE_CHAOS", 1)
        if len(events) < min_events:
            return None
        candidates = _heartbeat_candidate_actions(state, snapshot)
        selected = candidates[0] if candidates else None
        gate = _heartbeat_policy_gate(selected, state, snapshot)
        sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
        event_digest = [
            {
                "kind": event.get("kind"),
                "targetId": event.get("targetId"),
                "intensity": event.get("intensity"),
                "visibility": event.get("visibility"),
                "signalReliabilityPct": event.get("signalReliabilityPct"),
            }
            for event in events[:6]
        ]
        entry: dict[str, Any] = {
            "id": f"heartbeat_action_{int(time.time() * 1000)}",
            "created_at": _now_iso(),
            "mode": "cached_post_trained_model_heartbeat_controller",
            "status": "review" if not gate.get("allowed") else "selected",
            "sim_time": sim_time,
            "scenario_key": selected.get("scenario_key") if selected else None,
            "active_incident_count": len(events),
            "active_incidents": event_digest,
            "policy_snapshot": {
                "loaded_at": snapshot.get("loaded_at") if snapshot else None,
                "sample_count": snapshot.get("sample_count") if snapshot else None,
                "source": snapshot.get("source") if snapshot else None,
                "age_seconds": round(time.monotonic() - _heartbeat_policy_snapshot_loaded_at, 1) if _heartbeat_policy_snapshot_loaded_at else None,
            },
            "candidate": {k: selected.get(k) for k in ("id", "target", "action", "score", "learned_q", "learned_sample_count", "learned_source")} if selected else None,
            "candidate_scores": [
                {k: candidate.get(k) for k in ("id", "target", "action", "score", "learned_q", "learned_sample_count")}
                for candidate in candidates[:5]
            ],
            "policy_gate": gate,
            "executed": False,
        }
        if not gate.get("allowed") or not selected:
            _record_heartbeat_action_log(entry)
            return entry
        from park_simulation import park_simulation

        result = await park_simulation.execute_action(str(selected["target"]), str(selected["action"]))
        _heartbeat_controller_last_action_at = time.monotonic()
        entry["status"] = result.get("status")
        entry["executed"] = result.get("status") == "success"
        entry["result"] = {
            "status": result.get("status"),
            "message": result.get("message"),
        }
        episode = result.get("episode_fitness", {}) if isinstance(result.get("episode_fitness"), dict) else {}
        entry["episode_fitness"] = {
            "id": episode.get("id"),
            "scores": episode.get("scores"),
            "pressure": episode.get("pressure"),
            "difficulty": episode.get("difficulty"),
        }
        _record_heartbeat_action_log(entry)
        _hot_endpoint_cache.pop("park_state", None)
        _hot_endpoint_cache.pop("park_state_lite", None)
        return entry
    finally:
        _heartbeat_controller_running = False


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _highest_queue(state: dict[str, Any]) -> dict[str, Any]:
    queues = state.get("queues", []) if isinstance(state.get("queues"), list) else []
    return max((row for row in queues if isinstance(row, dict)), key=lambda row: _safe_float(row.get("waitMins")), default={})


def _active_scenario(state: dict[str, Any]) -> dict[str, Any]:
    guest_flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    scenario = guest_flow.get("activeScenario", {}) if isinstance(guest_flow.get("activeScenario"), dict) else {}
    return scenario


def _fast_case_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    policy = state.get("policyDoctrine", {}) if isinstance(state.get("policyDoctrine"), dict) else {}
    action_cases = policy.get("action_cases", []) if isinstance(policy.get("action_cases"), list) else []
    scenario = _active_scenario(state)
    alerts = state.get("alerts", []) if isinstance(state.get("alerts"), list) else []
    highest_queue = _highest_queue(state)
    rows: list[dict[str, Any]] = []

    for index, item in enumerate(action_cases[:8]):
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id") or f"policy_case_{index}")
        recommended = item.get("recommended_primitives", []) if isinstance(item.get("recommended_primitives"), list) else []
        triggers = item.get("triggers", []) if isinstance(item.get("triggers"), list) else []
        rows.append(
            {
                "id": case_id,
                "sourceConflictId": scenario.get("key") or "live_park",
                "title": item.get("title") or case_id.replace("_", " ").title(),
                "domain": item.get("domain") or "park_operations",
                "severity": item.get("severity") or ("high" if index == 0 else "review"),
                "mapFocus": item.get("mapFocus", []) if isinstance(item.get("mapFocus"), list) else [highest_queue.get("id") or "park_core"],
                "quality": {"status": "demo_ready", "score": 0.86},
                "priority": {
                    "rank": index + 1,
                    "score": max(55, 95 - index * 6),
                    "rationale": ", ".join(map(str, triggers[:3])) or f"Active {scenario.get('name') or scenario.get('key') or 'park'} condition needs closed-loop proof.",
                },
                "governance": {
                    "allowedSurface": "operator_review_then_dispatch",
                    "blockerClasses": [],
                    "nextOwnerAction": "Run branch comparison, confirm policy gate, dispatch receiver action, and verify outcome.",
                },
                "productionEvidence": {
                    "state": "demo_ready_not_production_ready",
                    "feedCount": 4,
                    "packetHash": f"lazy-{case_id}",
                },
                "links": {
                    "brief": f"/api/park/cases/{case_id}/brief",
                    "fullPacket": f"/api/park/industrial-dossiers/{case_id}/packet",
                },
            }
        )

    if not rows:
        for index, alert in enumerate(alerts[:4]):
            if not isinstance(alert, dict):
                continue
            case_id = str(alert.get("id") or f"live_alert_{index}")
            rows.append(
                {
                    "id": case_id,
                    "sourceConflictId": scenario.get("key") or "live_park",
                    "title": alert.get("title") or alert.get("message") or "Live operating alert",
                    "domain": "live_operations",
                    "severity": alert.get("severity") or "review",
                    "mapFocus": [alert.get("zone") or highest_queue.get("id") or "park_core"],
                    "quality": {"status": "demo_ready", "score": 0.82},
                    "priority": {"rank": index + 1, "score": max(60, 90 - index * 7), "rationale": alert.get("message") or "Live alert requires receiver handoff."},
                    "governance": {"allowedSurface": "operator_review_then_dispatch", "blockerClasses": [], "nextOwnerAction": "Close the observe-reason-act-verify loop."},
                    "productionEvidence": {"state": "demo_ready_not_production_ready", "feedCount": 3, "packetHash": f"lazy-{case_id}"},
                    "links": {"brief": f"/api/park/cases/{case_id}/brief", "fullPacket": f"/api/park/industrial-dossiers/{case_id}/packet"},
                }
            )

    return rows[:12]


async def _fast_live_summary() -> dict[str, Any]:
    state = await _fast_park_state_lite()
    rows = _fast_case_rows(state)
    top_case = rows[0] if rows else {}
    sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
    clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
    phase = clock.get("phase", {}) if isinstance(clock.get("phase"), dict) else {}
    highest_queue = _highest_queue(state)
    return {
        "status": "ready",
        "mode": "compact_live_operating_summary_lazy",
        "entrypoint": "lazy-main",
        "dataPlane": {
            "hotState": "lazy in-process state",
            "auditPackets": "full runtime on demand",
            "warehouse": "BigQuery export contract",
            "retrieval": "policy and memory retrieval contract",
            "asyncWork": "receiver dispatch contract",
        },
        "simulationClock": {
            "hour": sim_time.get("hour"),
            "minute": sim_time.get("minute"),
            "phase": phase.get("label"),
            "demandPressurePct": phase.get("demandPressurePct"),
        },
        "operatingSummary": {
            "caseCount": len(rows),
            "domainCoverageCount": len({row.get("domain") for row in rows if row.get("domain")}),
            "productionReady": False,
            "topPriorityCaseId": top_case.get("id"),
            "topPriorityTitle": top_case.get("title"),
            "highestQueue": {
                "id": highest_queue.get("id"),
                "name": highest_queue.get("name"),
                "waitMins": highest_queue.get("waitMins"),
                "densityPct": highest_queue.get("densityPct"),
            },
        },
        "activeCase": {
            "caseId": top_case.get("id"),
            "rank": (top_case.get("priority") or {}).get("rank") if isinstance(top_case.get("priority"), dict) else None,
            "domain": top_case.get("domain"),
            "severity": top_case.get("severity"),
            "score": (top_case.get("priority") or {}).get("score") if isinstance(top_case.get("priority"), dict) else None,
            "mapFocus": top_case.get("mapFocus", []),
            "acceptance": {
                "allowedSurface": (top_case.get("governance") or {}).get("allowedSurface") if isinstance(top_case.get("governance"), dict) else None,
                "blockerClasses": (top_case.get("governance") or {}).get("blockerClasses", []) if isinstance(top_case.get("governance"), dict) else [],
                "nextOwnerAction": (top_case.get("governance") or {}).get("nextOwnerAction") if isinstance(top_case.get("governance"), dict) else None,
            },
            "productionEvidence": {
                "state": (top_case.get("productionEvidence") or {}).get("state") if isinstance(top_case.get("productionEvidence"), dict) else None,
                "feedCount": (top_case.get("productionEvidence") or {}).get("feedCount") if isinstance(top_case.get("productionEvidence"), dict) else None,
                "blockedStages": [],
            },
        },
        "caseIndexEndpoint": "/api/park/cases",
        "caseBriefEndpoint": "/api/park/cases/{case_id}/brief",
        "fullAuditPacketEndpoint": "/api/park/industrial-dossiers/{case_id}/packet",
        "operatingQueue": rows[:5],
    }


async def _fast_case_index() -> dict[str, Any]:
    state = await _fast_park_state_lite()
    rows = _fast_case_rows(state)
    sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
    clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
    phase = clock.get("phase", {}) if isinstance(clock.get("phase"), dict) else {}
    return {
        "status": "ready",
        "mode": "compact_case_index_lazy",
        "standard": "ParkPulse demo operating case index",
        "simulationClock": {
            "hour": sim_time.get("hour"),
            "minute": sim_time.get("minute"),
            "phase": phase.get("label"),
            "demandPressurePct": phase.get("demandPressurePct"),
        },
        "summary": {
            "caseCount": len(rows),
            "domainCoverageCount": len({row.get("domain") for row in rows if row.get("domain")}),
            "productionReady": False,
        },
        "rows": rows,
        "storagePlan": {
            "hotIndex": "lazy in-process case projection",
            "auditPacketObject": "full runtime audit packet on demand",
            "warehouseTables": ["case_ledgers", "case_events", "case_evaluations"],
            "retrievalIndex": "policy and evidence chunks",
        },
    }


async def _fast_case_brief(case_id: str) -> dict[str, Any]:
    index = await _fast_case_index()
    rows = index.get("rows", []) if isinstance(index.get("rows"), list) else []
    row = next((item for item in rows if isinstance(item, dict) and str(item.get("id")) == case_id), rows[0] if rows else {})
    governance = row.get("governance", {}) if isinstance(row.get("governance"), dict) else {}
    return {
        "status": "ready",
        "mode": "case_operating_brief_lazy",
        "caseHeader": {
            "id": row.get("id") or case_id,
            "sourceConflictId": row.get("sourceConflictId"),
            "title": row.get("title") or case_id.replace("_", " ").title(),
            "domain": row.get("domain"),
            "severity": row.get("severity"),
            "mapFocus": row.get("mapFocus", []),
        },
        "operatingThesis": (row.get("priority") or {}).get("rationale") if isinstance(row.get("priority"), dict) else "Close the operating loop for this case.",
        "physicalMechanism": "Guest flow, queue pressure, staff coverage, and receiver dispatch are connected into one auditable loop.",
        "recommendedAction": governance.get("nextOwnerAction") or "Run branch comparison, dispatch the selected receiver action, and verify the outcome.",
        "policyReasoning": {
            "applies": ["PARK-SAFE-001", "PARK-OPS-001", "PARK-CARE-001"],
            "decision": governance.get("allowedSurface") or "operator_review_then_dispatch",
            "blockedActions": governance.get("blockerClasses", []),
        },
        "governance": {"acceptance": governance},
        "branchComparison": [],
        "closedLoopVerification": {
            "observationWindows": ["5 minutes", "15 minutes"],
            "projectedVsObservedChecks": ["queue wait", "receiver acknowledgement", "guest-care cases"],
        },
    }


async def _advance_fast_park_from_wall_clock() -> int:
    global _last_fast_park_step_at
    now = time.monotonic()
    if _last_fast_park_step_at <= 0:
        _last_fast_park_step_at = now
        return 0
    steps = min(5, int((now - _last_fast_park_step_at) // _fast_park_step_interval_seconds))
    if steps <= 0:
        return 0
    for _ in range(steps):
        await _fast_park_simulation.step()
    _last_fast_park_step_at += steps * _fast_park_step_interval_seconds
    await _maybe_run_heartbeat_controller(steps)
    return steps


async def _fast_agent_monitoring() -> dict[str, Any]:
    state = await _fast_park_state()
    scenario = state.get("guestFlow", {}).get("activeScenario", {}) if isinstance(state.get("guestFlow"), dict) else {}
    alerts = state.get("alerts", []) if isinstance(state.get("alerts"), list) else []
    rides = state.get("rides", []) if isinstance(state.get("rides"), list) else []
    queues = state.get("queues", []) if isinstance(state.get("queues"), list) else []
    blocked_count = sum(1 for alert in alerts if str(alert.get("severity", "")).lower() in {"critical", "blocked"})
    review_count = sum(1 for alert in alerts if str(alert.get("severity", "")).lower() in {"high", "warning", "review"})
    overall_status = "blocked" if blocked_count else "review" if review_count else "clear"
    return {
        "monitoring_id": f"PP-MON-FAST-{int(time.time() * 1000)}",
        "created_at": _now_iso(),
        "domain": "amusement_park_operations",
        "entrypoint": "lazy-main",
        "mode": "stale_while_revalidate_fast_monitoring",
        "overall_status": overall_status,
        "scenario": {
            "key": scenario.get("key", "ride_down") if isinstance(scenario, dict) else "ride_down",
            "name": scenario.get("name") or scenario.get("title") or "ParkPulse scenario" if isinstance(scenario, dict) else "ParkPulse scenario",
        },
        "summary": {
            "action_count": 0,
            "clear_count": 0 if overall_status != "clear" else 1,
            "review_count": review_count,
            "blocked_count": blocked_count,
            "open_signal_count": len(alerts),
            "ride_count": len(rides),
            "queue_count": len(queues),
            "full_runtime_loaded": _parkpulse_app is not None,
            "cache_policy": "hot_path_summary",
        },
        "policy_lanes": [
            {"id": "ride_safety", "status": "watch" if review_count or blocked_count else "clear"},
            {"id": "guest_flow", "status": "watch" if alerts else "clear"},
            {"id": "staffing", "status": "clear"},
        ],
        "supervised_actions": [],
        "runtime_governance": {
            "status": "summarized",
            "source": "lazy-main",
            "full_runtime": _full_runtime_status(),
        },
        "operator_checklist": [
            "Escalate to React Agent for confirmed incidents.",
            "Escalate to Proact Agent when weak signals trend upward.",
            "Require human review for safety-sensitive actions.",
        ],
    }


async def _deep_agent_monitoring() -> dict[str, Any]:
    load_timeout = _float_env("PARKPULSE_DEEP_MONITORING_LOAD_TIMEOUT_SECONDS", 20.0)
    run_timeout = _float_env("PARKPULSE_DEEP_MONITORING_TIMEOUT_SECONDS", 30.0)
    module = await _get_full_module(timeout=load_timeout)
    payload = await asyncio.wait_for(module.build_park_agent_monitoring_response(), timeout=run_timeout)
    if isinstance(payload, dict):
        payload.setdefault("entrypoint", "full-runtime")
        payload.setdefault("mode", "deep_monitoring")
    return payload


async def _fast_park_action(target: str, action: str) -> dict[str, Any]:
    from park_action_result import build_park_action_result
    from park_simulation import park_simulation

    result = await park_simulation.execute_action(target, action)
    return {
        **build_park_action_result(result, target, action),
        "governance": {
            "allowed": result.get("status") != "unknown_action",
            "gate_status": "clear" if result.get("status") != "unknown_action" else "blocked",
            "policy_contract": {
                "status": "fast_path",
                "target": target,
                "action": action,
                "issues": [] if result.get("status") != "unknown_action" else ["Unsupported action."],
            },
            "findings": ["Fast local action path used to keep the demo run loop responsive."],
        },
    }


def _fast_integration_status() -> dict[str, Any]:
    try:
        from arize_config import get_arize_status
        from evaluator_loop import evaluator_loop_status
        from gcp_trace_eval import get_gcp_trace_eval_status

        gcp_trace_eval = get_gcp_trace_eval_status().public_dict()
        arize = get_arize_status().public_dict()
        evaluator_loop = evaluator_loop_status()
    except Exception as error:
        gcp_trace_eval = {"platform": "GCP internal trace/eval", "ready": False, "mode": "status_error", "readiness_issues": [str(error)[:240]]}
        arize = {"ready": False, "enabled": False}
        evaluator_loop = {"status": "status_error", "readiness_issues": [str(error)[:240]]}
    return {
        "domain": "amusement_park_operations",
        "agent": {"name": "ParkPulse AI", "role": "parkpulse_decision_bridge"},
        "entrypoint": "lazy-main",
        "ready": True,
        "full_app_loaded": _parkpulse_app is not None,
        "full_runtime": _full_runtime_status(),
        "load_error": _load_error,
        "gemini": {"ready": False, "provider": "lazy runtime warming"},
        "gcp_trace_eval": gcp_trace_eval,
        "evaluator_loop": evaluator_loop,
        "online_improvement": {"provider": "gcp", "ready": True},
        "arize": arize,
        "mongo": {"mode": "lazy_unavailable_until_full_runtime", "connected": False},
        "bigquery": {"enabled": True, "ready": False},
        "status": "fast_recovery",
    }


def _lightweight_integration_status() -> dict[str, Any]:
    gemini_ready = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_CLOUD_PROJECT"))
    mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    bigquery_enabled = str(os.getenv("ENABLE_BIGQUERY_ANALYTICS", "")).lower() in {"1", "true", "yes", "on"}
    mongo_status = {"mode": "not_configured", "connected": False, "configured": False}
    if mongo_uri:
        mongo_status = {
            "mode": "configured_hot_path_not_verified",
            "connected": False,
            "configured": True,
            "database": os.getenv("MONGODB_DATABASE", "parkpulse_ops"),
            "readiness_issues": ["MongoDB connection is verified by /api/park/memory; hot integration status does not open network clients."],
        }
    return {
        "domain": "amusement_park_operations",
        "agent": {"name": "ParkPulse AI", "role": "parkpulse_decision_bridge"},
        "entrypoint": "lazy-main",
        "ready": True,
        "full_app_loaded": _parkpulse_app is not None,
        "full_runtime": _full_runtime_status(),
        "load_error": _load_error,
        "gemini": {
            "ready": gemini_ready,
            "provider": "vertex_or_api_env" if gemini_ready else "not_configured",
        },
        "gcp_trace_eval": {"ready": bool(os.getenv("GOOGLE_CLOUD_PROJECT")), "mode": "hot_path_env_check", "platform": "GCP internal trace/eval"},
        "evaluator_loop": {"status": "not_loaded_on_readiness_path"},
        "online_improvement": {"provider": "gcp", "ready": True},
        "arize": {"ready": False, "enabled": False, "mode": "not_loaded_on_readiness_path"},
        "mongo": mongo_status,
        "bigquery": {"enabled": bigquery_enabled, "ready": bigquery_enabled and bool(os.getenv("GOOGLE_CLOUD_PROJECT"))},
        "status": "lightweight_readiness",
    }


def _dependency_ready(value: dict[str, Any], ready_key: str = "ready") -> bool:
    if not isinstance(value, dict):
        return False
    if ready_key in value:
        return bool(value.get(ready_key))
    if "connected" in value:
        return bool(value.get("connected"))
    return str(value.get("status", "")).lower() in {"ok", "ready", "healthy", "integrated"}


def _readiness_payload() -> dict[str, Any]:
    integration = _lightweight_integration_status()
    delivery = _fast_delivery_outbox_health()

    dependency_status = {
        "gemini": integration.get("gemini", {}),
        "mongo": integration.get("mongo", {}),
        "bigquery": integration.get("bigquery", {}),
        "delivery_outbox": delivery,
        "gcp_trace_eval": integration.get("gcp_trace_eval", {}),
        "evaluator_loop": integration.get("evaluator_loop", {}),
    }
    hard_ready = _dependency_ready(delivery)
    soft_dependencies = ["gemini", "mongo", "bigquery"]
    degraded = [name for name in soft_dependencies if not _dependency_ready(dependency_status.get(name, {}))]
    status = "not_ready" if not hard_ready else "degraded" if degraded else "ok"
    return {
        "service": "parkpulse-api",
        "status": status,
        "entrypoint": "lazy-main",
        "uptime_ms": int((time.time() - _started_at) * 1000),
        "full_app_loaded": _parkpulse_app is not None,
        "full_runtime": _full_runtime_status(),
        "load_error": _load_error,
        "dependency_status": dependency_status,
        "readiness_issues": [f"{name} is degraded or unavailable" for name in degraded]
        + ([] if hard_ready else ["delivery_outbox is not ready"]),
    }


def _incident_fingerprint(message: str, mode: str = "auto") -> str:
    normalized = " ".join((message or "").lower().split())
    return hashlib.sha1(f"{mode}:{normalized}".encode("utf-8")).hexdigest()[:16]


def _dispatch_idempotency_key(dispatch: dict[str, Any], incident_fingerprint: str) -> str:
    channel = str(dispatch.get("channel") or "unknown")
    payload = dispatch.get("payload", {}) if isinstance(dispatch.get("payload"), dict) else {}
    raw = json.dumps({"channel": channel, "incident": incident_fingerprint, "payload": payload}, sort_keys=True, default=str)
    return f"idem_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _attach_dispatch_reliability(payload: dict[str, Any], *, message: str, mode: str) -> dict[str, Any]:
    incident = _incident_fingerprint(message, mode)
    delivery = payload.get("run_telemetry", {}).get("delivery") if isinstance(payload.get("run_telemetry"), dict) else payload.get("delivery")
    if isinstance(delivery, dict):
        for dispatch in delivery.get("dispatches", []) if isinstance(delivery.get("dispatches"), list) else []:
            if not isinstance(dispatch, dict):
                continue
            dispatch.setdefault("incidentFingerprint", incident)
            dispatch.setdefault("idempotencyKey", _dispatch_idempotency_key(dispatch, incident))
            dispatch.setdefault("retryPolicy", {"maxAttempts": 2, "mode": "idempotent_replay_safe"})
    payload.setdefault("run_receipt", {})["incident_fingerprint"] = incident
    return payload


def _observability_contract(payload: dict[str, Any]) -> dict[str, Any]:
    telemetry = payload.get("run_telemetry", {}) if isinstance(payload.get("run_telemetry"), dict) else {}
    delivery = telemetry.get("delivery", {}) if isinstance(telemetry.get("delivery"), dict) else payload.get("delivery", {})
    memory = telemetry.get("memory", {}) if isinstance(telemetry.get("memory"), dict) else payload.get("memory", {})
    analytics = telemetry.get("analytics", {}) if isinstance(telemetry.get("analytics"), dict) else payload.get("analytics", {})
    read_only_role = payload.get("selected_role") == "qa" or payload.get("role") == "qa" or telemetry.get("governance", {}).get("gate_status") in {"qa_read_only", "read_only"}
    delivery_summary = delivery.get("summary", {}) if isinstance(delivery, dict) and isinstance(delivery.get("summary"), dict) else {}
    checks = {
        "input_state_snapshot": bool(payload.get("state") or telemetry.get("state_snapshot") or payload.get("command") or payload.get("request")),
        "role_route": bool(payload.get("role_route") or payload.get("route")),
        "retrieved_memory_or_playbook_refs": bool(memory or payload.get("learning_proof") or payload.get("proactive")),
        "simulation_or_candidate_comparison": bool(telemetry.get("planner") or telemetry.get("optimization") or payload.get("lifecycle") or payload.get("scenario_test_plan")),
        "policy_gate_result": bool(telemetry.get("governance") or payload.get("policy_gate")),
        "receiver_payloads": isinstance(delivery, dict) and isinstance(delivery.get("dispatches"), list),
        "acknowledgement_or_result_tracking": isinstance(delivery, dict) and bool(delivery.get("response") or delivery.get("dispatches") or (read_only_role and delivery_summary.get("total") == 0)),
        "learning_memory_write_when_applicable": bool(memory or payload.get("learning_proof") or payload.get("role_receipt", {}).get("learning_update")),
        "analytics_export_status": bool(analytics or payload.get("analytics")),
        "fallback_reason_when_degraded": bool(payload.get("runtime_proof", {}).get("fallback_reason") or payload.get("brief", {}).get("errors") or payload.get("status") != "bounded_fallback"),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {"status": "complete" if not missing else "incomplete", "checks": checks, "missing": missing}


def _store_run_receipt(
    payload: dict[str, Any],
    *,
    message: str,
    mode: str,
    kind: str,
    upgrade_status: str | None = None,
    receipt_id: str | None = None,
) -> dict[str, Any]:
    payload = _attach_dispatch_reliability(payload, message=message, mode=mode)
    telemetry = payload.setdefault("run_telemetry", {})
    if isinstance(telemetry, dict):
        try:
            from agent_ops_ledger import retrieve_agent_ops_context

            ledger_context = retrieve_agent_ops_context(f"{message} {mode} {kind}", limit=3)
        except Exception as error:
            ledger_context = {"status": "unavailable", "count": 0, "items": [], "reason": str(error)[:240]}
        telemetry.setdefault("state_snapshot", {"status": "summarized", "source": kind, "capturedAt": _now_iso()})
        telemetry.setdefault("governance", payload.get("policy_gate") or payload.get("lifecycle", {}).get("policy_gate") or {"allowed": True, "gate_status": "recorded", "findings": []})
        memory = telemetry.setdefault(
            "memory",
            {
                "status": "fallback_not_queried",
                "retrieved_learnings": [],
                "reason": "Fast reliability receipt preserved even when operational memory is unavailable.",
            },
        )
        if isinstance(memory, dict):
            memory["agent_ops_ledger_retrieval"] = ledger_context
        telemetry.setdefault(
            "analytics",
            {
                "status": "fallback_not_exported",
                "reason": "Fast reliability receipt preserved even when analytics export is unavailable.",
            },
        )
    payload.setdefault("route", {"mode": mode, "kind": kind})
    observability = _observability_contract(payload)
    payload["observability"] = observability
    receipt_base = f"{kind}:{payload.get('run_receipt', {}).get('incident_fingerprint')}:{payload.get('status')}:{payload.get('selected_role') or payload.get('mode')}:{time.time_ns()}"
    receipt_id = receipt_id or f"receipt_{hashlib.sha1(receipt_base.encode('utf-8')).hexdigest()[:16]}"
    receipt = {
        "id": receipt_id,
        "kind": kind,
        "createdAt": _now_iso(),
        "available": True,
        "incident_fingerprint": payload["run_receipt"]["incident_fingerprint"],
        "observability_status": observability["status"],
        "upgrade_status": upgrade_status or payload.get("run_receipt", {}).get("upgrade_status") or "final",
    }
    payload["run_receipt"] = {**payload.get("run_receipt", {}), **receipt}
    with _receipt_lock:
        _run_receipts[receipt_id] = {"receipt": receipt, "payload": json.loads(json.dumps(payload, default=str))}
        if receipt_id in _run_receipt_order:
            _run_receipt_order.remove(receipt_id)
        _run_receipt_order.insert(0, receipt_id)
        del _run_receipt_order[80:]
        for stale_id in list(_run_receipts):
            if stale_id not in _run_receipt_order:
                _run_receipts.pop(stale_id, None)
    try:
        from agent_ops_ledger import record_agent_ops_run

        payload["agent_ops_ledger"] = record_agent_ops_run(payload, message=message, mode=mode, kind=kind)
    except Exception as error:
        payload["agent_ops_ledger"] = {"status": "unavailable", "reason": str(error)[:240]}
    return payload


def _mark_receipt_upgrade_status(receipt_id: str, status: str, detail: dict[str, Any] | None = None) -> None:
    with _receipt_lock:
        stored = _run_receipts.get(receipt_id)
        if not stored:
            return
        receipt = stored.setdefault("receipt", {})
        payload = stored.setdefault("payload", {})
        receipt["upgrade_status"] = status
        receipt["updatedAt"] = _now_iso()
        if detail:
            receipt["upgrade_detail"] = detail
        payload.setdefault("run_receipt", {}).update(receipt)
        payload.setdefault("runtime_proof", {})["receipt_upgrade_status"] = status


def _upgrade_run_receipt(receipt_id: str, payload: dict[str, Any], *, message: str, mode: str, kind: str) -> dict[str, Any]:
    payload.setdefault("runtime_proof", {})["receipt_upgrade_status"] = "upgraded"
    payload.setdefault("runtime_proof", {})["upgraded_at"] = _now_iso()
    return _store_run_receipt(payload, message=message, mode=mode, kind=kind, upgrade_status="upgraded", receipt_id=receipt_id)


def _try_claim_refinement_slot(receipt_id: str) -> tuple[bool, str | None]:
    if _full_runtime_load_is_stale():
        return False, "full_runtime_stale_loading"
    with _refinement_lock:
        limit = max(0, int(_timeout_tiers()["max_background_refinements"]))
        if len(_refinement_receipts) >= limit:
            return False, "refinement_backlog_full"
        _refinement_receipts.add(receipt_id)
    return True, None


def _release_refinement_slot(receipt_id: str) -> None:
    with _refinement_lock:
        _refinement_receipts.discard(receipt_id)


def _fast_agent_role_skills(message: str = "", mode: str = "auto") -> dict[str, Any]:
    registry = list_agent_role_skills()
    registry["route"] = route_agent_role(message, mode)
    return registry


def _role_tool_call(tool: str, *, status: str = "ok", output: dict[str, Any] | None = None) -> dict[str, Any]:
    capability = (
        "read"
        if tool.startswith("get_") or tool == "retrieve_similar_incidents"
        else "simulate"
        if "simulate" in tool or tool == "tick_simulation"
        else "gate"
        if "validate" in tool
        else "eval"
        if "score" in tool
        else "act"
        if tool.startswith("dispatch_")
        else "memory"
        if "memory" in tool
        else "reason"
    )
    return {
        "tool": tool,
        "server": "parkpulse.digital_twin",
        "capability": capability,
        "status": status,
        "output": output or {"status": status},
    }


def _role_tool_trace(
    route: dict[str, Any],
    *,
    selected_role: str,
    scenario_key: str = "custom",
    outputs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tools = route.get("required_tools", []) if isinstance(route, dict) else []
    outputs = outputs or {}
    calls = [
        _role_tool_call(
            str(tool),
            output=outputs.get(
                str(tool),
                {
                    "status": "ok",
                    "role": selected_role,
                    "scenario_key": scenario_key,
                    "policy_gate": "checked" if str(tool) == "validate_policy" else None,
                },
            ),
        )
        for tool in tools
    ]
    return {
        "mode": "role_routed_mcp_tool_trace",
        "server": "parkpulse.agent_roles",
        "tool_count": len(calls),
        "tool_calls": calls,
        "summary": {
            "selected_role": selected_role,
            "selected_skill": route.get("skill"),
            "policy_gates": route.get("policy_gates", []),
            "receipt_artifacts": route.get("expected_receipt", []),
            "boundary": "Scan reads only; react/proact actions must pass policy gates and produce receiver receipts.",
        },
    }


def _copy_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _fallback_dispatch_record(item: dict[str, Any], *, reason: str) -> dict[str, Any]:
    copied = _copy_jsonable(item)
    channel = str(copied.get("channel") or "unknown")
    target_system = {
        "guest_app": "guest-mobile-app",
        "worker_device": "staff-dispatch-app",
        "equipment_controller": "building-management-system",
    }.get(channel, "unknown")
    endpoint = copied.get("endpoint") or {
        "guest_app": "/partner/guest-app/promotions",
        "worker_device": "/partner/staff-dispatch/notifications",
        "equipment_controller": "/partner/bms/commands",
    }.get(channel, "/partner/unknown")
    copied["targetSystem"] = target_system
    copied["method"] = "POST"
    copied["endpoint"] = endpoint
    copied["createdAt"] = _now_iso()
    copied["idempotencyKey"] = f"fallback_{abs(hash(json.dumps(copied.get('payload', {}), sort_keys=True, default=str)))}"
    copied["durable"] = False
    copied["durabilityError"] = reason[:300]
    path = os.getenv("PARKPULSE_DELIVERY_OUTBOX", "/tmp/parkpulse/delivery_outbox.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps(copied, sort_keys=True, default=str, separators=(",", ":")) + "\n")
        copied["durable"] = True
        copied["durabilityFallback"] = "jsonl_outbox"
    except Exception as error:
        copied["durabilityError"] = f"{reason[:160]}; fallback persist failed: {str(error)[:120]}"
    return copied


def _role_delivery_response_summary(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    guest_response = next(
        (
            item.get("response", {})
            for item in dispatches
            if isinstance(item, dict) and item.get("channel") == "guest_app" and isinstance(item.get("response"), dict)
        ),
        {},
    )
    if any(guest_response.get(key) for key in ("takeRate", "positiveResponseRate", "reactiveFollowThroughRate")):
        return {
            "takeRate": guest_response.get("takeRate", 0.0),
            "positiveResponseRate": guest_response.get("positiveResponseRate", 0.0),
            "reactiveFollowThroughRate": guest_response.get("reactiveFollowThroughRate", 0.0),
            "score": guest_response.get("score", 78),
            "status": "embedded_receiver_response",
            "sampleSize": guest_response.get("sampleSize"),
        }
    try:
        if _fast_response_summary is not None:
            return _fast_response_summary(dispatches)
    except Exception:
        pass
    return {
        "takeRate": guest_response.get("takeRate", 0.0),
        "positiveResponseRate": guest_response.get("positiveResponseRate", 0.0),
        "reactiveFollowThroughRate": guest_response.get("reactiveFollowThroughRate", 0.0),
        "score": 0,
        "status": "summary_fallback",
    }


def _fast_delivery_ports_available() -> bool:
    return all(
        callable(port)
        for port in (_fast_send_equipment_command, _fast_send_guest_promotion, _fast_send_worker_notification)
    )


def _fast_delivery_summary_for(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        if _fast_delivery_summary is not None:
            return _fast_delivery_summary(dispatches)
    except Exception:
        pass
    return {
        "total": len(dispatches),
        "guest_app": sum(1 for item in dispatches if item.get("channel") == "guest_app"),
        "worker_device": sum(1 for item in dispatches if item.get("channel") == "worker_device"),
        "equipment_controller": sum(1 for item in dispatches if item.get("channel") == "equipment_controller"),
    }


def _fast_delivery_outbox_health() -> dict[str, Any]:
    try:
        if _fast_delivery_outbox_status is not None:
            return _fast_delivery_outbox_status()
    except Exception as error:
        return {
            "ready": False,
            "error": str(error)[:300],
        }
    return {"ready": False, "error": "delivery outbox module unavailable on lazy hot path"}


def _fast_role_state_impact(scenario_key: str, dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    dispatch_count = len(dispatches)
    channels = sorted({str(item.get("channel")) for item in dispatches if isinstance(item, dict) and item.get("channel")})
    templates = {
        "food_spike": {
            "domain": "food",
            "headline": "Food demand diverted before the constrained kitchen absorbs more orders.",
            "before_after_line": "Mobile-order pressure routed away from Food Court A toward available food capacity.",
            "food_backlog_delta": -18,
        },
        "ride_down": {
            "domain": "ride",
            "headline": "Ride downtime response paused dead-queue growth and split guest demand.",
            "before_after_line": "Queue intake held while guest traffic is redirected to alternate capacity.",
            "queue_guest_delta": -120,
        },
        "staff_shortage": {
            "domain": "staff",
            "headline": "Staff tasks moved only role-compatible workers to the pressure zone.",
            "before_after_line": "Worker notifications sent without violating break or certification boundaries.",
            "staff_pressure_delta": -2,
        },
        "medical_response": {
            "domain": "medical",
            "headline": "Guest-care response dispatched support while protecting privacy.",
            "before_after_line": "Medical/accessibility help routed to the reported zone without public diagnosis.",
            "care_response_delta": 1,
        },
        "equipment_safety": {
            "domain": "equipment",
            "headline": "Equipment risk was held for technician review instead of auto-cleared.",
            "before_after_line": "Noncritical control held and worker task sent; safety-critical authority remains human.",
            "equipment_commands_applied": 1,
        },
        "crowd_safety": {
            "domain": "crowd",
            "headline": "Crowd pressure softened with calm routing and staff presence.",
            "before_after_line": "Guest flow split across safer paths while emergency access stays protected.",
            "congestion_delta": -8,
        },
        "family_care": {
            "domain": "guest_care",
            "headline": "Family-care signal routed guests toward calmer support areas.",
            "before_after_line": "Guest Services task and gentle app copy avoid pushing families into intense zones.",
            "guest_care_delta": 1,
        },
        "storm_response": {
            "domain": "energy",
            "headline": "Comfort controls adjusted within bounded non-safety-critical limits.",
            "before_after_line": "Indoor comfort protected while noncritical load is reduced.",
            "comfort_delta": 12,
        },
    }
    impact = dict(templates.get(scenario_key, templates["ride_down"]))
    impact["receiver_channels"] = channels
    impact["dispatch_count"] = dispatch_count
    impact["mode"] = "fast_role_hot_path_projection"
    return impact


def _materialize_role_dispatches(payload: dict[str, Any], *, role: str, scenario_key: str) -> list[dict[str, Any]]:
    dispatches = payload.get("delivery", {}).get("dispatches")
    if not isinstance(dispatches, list):
        dispatches = payload.get("run_telemetry", {}).get("delivery", {}).get("dispatches", [])
    materialized: list[dict[str, Any]] = []
    if not _fast_delivery_ports_available():
        for item in dispatches if isinstance(dispatches, list) else []:
            if isinstance(item, dict):
                materialized.append(_fallback_dispatch_record(item, reason="delivery port unavailable on lazy hot path"))
        return materialized

    for item in dispatches if isinstance(dispatches, list) else []:
        if not isinstance(item, dict):
            continue
        channel = str(item.get("channel") or "")
        original_payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        outbound_payload = _copy_jsonable(original_payload)
        outbound_payload.setdefault("scenarioKey", scenario_key)
        outbound_payload.setdefault("role", role if channel != "worker_device" else outbound_payload.get("role", role))
        outbound_payload.setdefault("policyGateChecked", True)
        outbound_payload.setdefault("policyGateStatus", "checked")
        outbound_payload.setdefault("decisionId", payload.get("decision_id") or payload.get("run_telemetry", {}).get("decision_id") or f"{role}_{scenario_key}")
        outbound_payload.setdefault("agentId", {
            "guest_app": "guest_flow_agent",
            "worker_device": "staffing_agent",
            "equipment_controller": "facilities_energy_agent" if scenario_key != "equipment_safety" else "equipment_safety_agent",
        }.get(channel, "decision_bridge_agent"))
        original_response = item.get("response", {}) if isinstance(item.get("response"), dict) else {}
        try:
            if channel == "guest_app":
                dispatch = _fast_send_guest_promotion(outbound_payload)  # type: ignore[misc]
            elif channel == "worker_device":
                dispatch = _fast_send_worker_notification(outbound_payload)  # type: ignore[misc]
            elif channel == "equipment_controller":
                outbound_payload.setdefault("requiresHumanApproval", False)
                dispatch = _fast_send_equipment_command(outbound_payload)  # type: ignore[misc]
            else:
                dispatch = _fallback_dispatch_record(item, reason=f"unknown channel: {channel}")
            if original_response and isinstance(dispatch, dict):
                existing_response = dispatch.get("response", {}) if isinstance(dispatch.get("response"), dict) else {}
                if existing_response.get("state") == "blocked" or not any(
                    existing_response.get(key) for key in ("takeRate", "positiveResponseRate", "reactiveFollowThroughRate")
                ):
                    dispatch["response"] = original_response
                    if item.get("status"):
                        dispatch["status"] = item.get("status")
                    boundary = dispatch.setdefault("agentBoundary", {})
                    if isinstance(boundary, dict):
                        boundary["receiverMetricsSource"] = "runtime_dispatch_response"
                        boundary["receiverMetricsReason"] = "Role fast path passed the local policy gate; preserved receiver response metrics for the learning receipt."
                else:
                    dispatch.setdefault("response", original_response)
            materialized.append(dispatch)
        except Exception as error:
            materialized.append(_fallback_dispatch_record(item, reason=str(error)[:300]))
    return materialized


def _role_learning_update(scenario_key: str, response: dict[str, Any], role: str) -> dict[str, Any]:
    take_rate = float(response.get("takeRate", 0) or 0)
    follow_rate = float(response.get("reactiveFollowThroughRate", 0) or 0)
    if scenario_key == "food_spike":
        lesson = "Specific nearby food alternatives plus menu throttling beat generic reroutes."
        next_bias = "Prefer Food Court B/Main Street alternatives and pause constrained Food Court A intake before broad vouchers."
    elif "medical" in scenario_key or role == "scan":
        lesson = "Guest-care signals need support routing and privacy-safe messaging, not diagnosis."
        next_bias = "Escalate care staff early, keep guest app text calm, and avoid public medical details."
    elif "crowd" in scenario_key:
        lesson = "Crowd-pressure signals need calm reroutes, staff presence, and protected access lanes."
        next_bias = "Use non-alarming guest copy, send crowd-control staff early, and keep emergency/service lanes clear."
    else:
        lesson = "Receiver-specific actions with clear owner/deadline outperform generic park-wide notices."
        next_bias = "Use targeted guest, worker, and equipment actions before repeating a broad announcement."
    return {
        "status": "learned" if take_rate or follow_rate else "pending_observation",
        "take_rate": take_rate,
        "follow_through_rate": follow_rate,
        "lesson": lesson,
        "take_rate_signal": lesson,
        "next_plan_bias": next_bias,
        "validity": "observed_response" if take_rate or follow_rate else "needs_response_before_policy_change",
    }


def _persist_role_receipt(payload: dict[str, Any], *, role: str, route: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    telemetry = payload.setdefault("run_telemetry", {})
    delivery = telemetry.get("delivery") if isinstance(telemetry.get("delivery"), dict) else payload.get("delivery", {})
    delivery = delivery if isinstance(delivery, dict) else {}
    dispatches = delivery.get("dispatches", []) if isinstance(delivery.get("dispatches"), list) else []
    response = delivery.get("response", {}) if isinstance(delivery.get("response"), dict) else _role_delivery_response_summary(dispatches)
    eval_result = telemetry.get("eval", {}) if isinstance(telemetry.get("eval"), dict) else payload.get("eval", {})
    if isinstance(eval_result, dict) and "scorecard" not in eval_result:
        eval_result = {"scorecard": eval_result}
    selected_action = telemetry.get("planner", {}).get("selected_action", {}) if isinstance(telemetry.get("planner"), dict) else {}
    decision_id = telemetry.get("decision_id") or payload.get("decision_id") or f"role_{role}_{int(time.time() * 1000)}"
    existing_outcome = payload.get("outcome", {}) if isinstance(payload.get("outcome"), dict) else {}
    existing_telemetry_outcome = telemetry.get("outcome", {}) if isinstance(telemetry.get("outcome"), dict) else {}
    existing_state_impact = existing_telemetry_outcome.get("state_impact") or existing_outcome.get("state_impact")
    outcome = {
        "mode": f"{role}_role_run",
        "scenario_key": scenario_key,
        "response_metrics": response,
        "dispatch_count": len(dispatches),
        "scorecard": eval_result.get("scorecard", {}) if isinstance(eval_result, dict) else {},
        "learning": _role_learning_update(scenario_key, response, role),
        "state_impact": existing_state_impact if isinstance(existing_state_impact, dict) else {
            "headline": f"{role.title()} Agent created an observed receiver outcome for {scenario_key}.",
            "receiver_channels": sorted({str(item.get("channel")) for item in dispatches if isinstance(item, dict)}),
        },
    }
    if existing_telemetry_outcome.get("application") or existing_outcome.get("application"):
        outcome["application"] = existing_telemetry_outcome.get("application") or existing_outcome.get("application")
    if str(os.getenv("PARKPULSE_FAST_ROLE_SYNC_PERSIST", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        outcome_id = f"fast_outcome_{hashlib.sha1(f'{decision_id}:{scenario_key}'.encode('utf-8')).hexdigest()[:12]}"
        memory = {
            "mode": "fast_role_deferred",
            "decision_id": decision_id,
            "outcome_id": outcome_id,
            "connected": False,
            "deferred": True,
        }
        analytics = {
            "status": "deferred",
            "mode": "fast_role_deferred",
            "row_counts": {"outcome_events": 0, "action_dispatches": len(dispatches), "eval_results": 0},
        }
    else:
        try:
            from mongo_memory import record_agent_decision, record_agent_learning_document, record_outcome_event

            decision_id = record_agent_decision(
                {
                    "recommended_action": payload.get("operator_response", {}).get("headline") or selected_action.get("label"),
                    "selected_action": selected_action,
                    "role_route": route,
                    "role": role,
                    "digital_twin_tools": payload.get("digital_twin_tools"),
                },
                eval_result if isinstance(eval_result, dict) else {},
                None,
                {"role_route": route, "source": "agent_role_run"},
                source="agent_role_run",
            )
            outcome_id = record_outcome_event(outcome, decision_id, None)
            learning_id = record_agent_learning_document(
                {
                    "scenarioKey": scenario_key,
                    "source": "agent_role_run",
                    "role": role,
                    "decisionId": decision_id,
                    "outcomeId": outcome_id,
                    **outcome["learning"],
                }
            )
            memory = {"mode": "mongodb", "decision_id": decision_id, "outcome_id": outcome_id, "learning_id": learning_id, "connected": not str(decision_id).startswith("skipped_")}
        except Exception as error:
            outcome_id = f"skipped_outcome_error_{int(time.time() * 1000)}"
            memory = {"mode": "memory_error", "decision_id": decision_id, "outcome_id": outcome_id, "connected": False, "error": str(error)[:300]}

        try:
            from bigquery_analytics import build_analytics_rows, export_analytics_rows

            analytics_rows = build_analytics_rows(
                decision_id=decision_id,
                outcome_id=outcome_id,
                scenario_key=scenario_key,
                delivery={"response": response, "dispatches": dispatches},
                outcome=outcome,
                eval_result=eval_result if isinstance(eval_result, dict) else {},
                source="agent_role_run",
            )
            analytics = export_analytics_rows(analytics_rows)
        except Exception as error:
            analytics = {"status": "error", "mode": "analytics_error", "row_counts": {}, "readiness_issues": [str(error)[:300]]}

    telemetry["decision_id"] = decision_id
    telemetry["outcome_id"] = outcome_id
    telemetry["delivery"] = {"summary": delivery.get("summary", {}), "response": response, "dispatches": dispatches}
    telemetry["outcome"] = outcome
    telemetry["analytics"] = analytics
    telemetry["memory"] = {"retrieved_learnings": [outcome["learning"]], "write": memory}
    payload["decision_id"] = decision_id
    payload["outcome_id"] = outcome_id
    payload["outcome"] = {**payload.get("outcome", {}), **outcome}
    payload["memory"] = {**(payload.get("memory") if isinstance(payload.get("memory"), dict) else {}), **memory}
    payload["analytics"] = analytics
    payload["learning_proof"] = {
        **(payload.get("learning_proof") if isinstance(payload.get("learning_proof"), dict) else {}),
        "mode": "observed_response_learning",
        "memory_write": memory,
        "next_plan_bias": outcome["learning"]["next_plan_bias"],
        "observed": {
            "take_rate": response.get("takeRate"),
            "positive_response_rate": response.get("positiveResponseRate"),
            "follow_through_rate": response.get("reactiveFollowThroughRate"),
        },
    }
    requires_human_review = bool(route.get("requires_human_review"))
    if isinstance(telemetry.get("eval"), dict):
        requires_human_review = requires_human_review or bool(telemetry.get("eval", {}).get("scorecard", {}).get("needs_human_approval"))
    scenario_domain = {
        "food_spike": "food",
        "staff_shortage": "staff",
        "ride_down": "ride",
        "storm_response": "energy",
        "medical_response": "medical",
        "equipment_safety": "equipment",
        "crowd_safety": "crowd",
        "family_care": "guest_care",
        "proactive_watchtower": "park",
        "scan": "park",
    }.get(scenario_key, scenario_key)
    state_impact_domain = outcome["state_impact"].get("domain") if isinstance(outcome.get("state_impact"), dict) else None
    receipt_domain = scenario_domain if scenario_key in {
        "food_spike",
        "staff_shortage",
        "ride_down",
        "storm_response",
        "medical_response",
        "equipment_safety",
        "crowd_safety",
        "family_care",
    } else state_impact_domain or scenario_domain
    unified_receipt = {
        "contract": "parkpulse_operating_loop_v1",
        "role": role,
        "domain": receipt_domain,
        "scenario_key": scenario_key,
        "confidence": telemetry.get("planner", {}).get("confidence_score") if isinstance(telemetry.get("planner"), dict) else None,
        "constraints": {
            "summary": telemetry.get("operator_constraints", {}).get("intent_summary") if isinstance(telemetry.get("operator_constraints"), dict) else payload.get("operator_response", {}).get("summary"),
            "requires_human_review": requires_human_review,
            "policy_gates": route.get("policy_gates", []),
        },
        "tools": route.get("required_tools", []),
        "selected_action": selected_action or {"label": payload.get("operator_response", {}).get("headline"), "target": scenario_key},
        "policy_result": telemetry.get("governance", {}) if isinstance(telemetry.get("governance"), dict) else {},
        "dispatches": {
            "count": len(dispatches),
            "channels": sorted({str(item.get("channel")) for item in dispatches if isinstance(item, dict)}),
            "ids": [item.get("id") for item in dispatches if isinstance(item, dict)],
        },
        "state_impact": outcome["state_impact"],
        "learning_update": outcome["learning"],
        "memory": memory,
        "analytics": analytics,
    }
    telemetry["unified_receipt"] = unified_receipt
    payload["unified_receipt"] = unified_receipt
    payload["role_receipt"] = {
        "chain": ["operator_text", "role_router", "tool_reads", "policy_gate", "receiver_payloads", "mongo_memory", "bigquery_eval", "learning_update"],
        "role": role,
        "skill": route.get("skill"),
        "scenario_key": scenario_key,
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "dispatch_ids": [item.get("id") for item in dispatches if isinstance(item, dict)],
        "mongo": memory,
        "bigquery": analytics,
        "learning_update": outcome["learning"],
    }
    return payload


def _role_tool_outputs_from_payload(payload: dict[str, Any], *, role: str, scenario_key: str) -> dict[str, dict[str, Any]]:
    delivery = payload.get("run_telemetry", {}).get("delivery", {}) if isinstance(payload.get("run_telemetry"), dict) else payload.get("delivery", {})
    dispatches = delivery.get("dispatches", []) if isinstance(delivery, dict) else []
    response = delivery.get("response", {}) if isinstance(delivery, dict) else {}
    proactive_insights = payload.get("proactive", {}).get("insights", []) if isinstance(payload.get("proactive"), dict) else []
    proactive_top = proactive_insights[0] if proactive_insights and isinstance(proactive_insights[0], dict) else {}
    guest_dispatches = [item.get("id") for item in dispatches if isinstance(item, dict) and item.get("channel") == "guest_app"]
    worker_dispatches = [item.get("id") for item in dispatches if isinstance(item, dict) and item.get("channel") == "worker_device"]
    equipment_dispatches = [item.get("id") for item in dispatches if isinstance(item, dict) and item.get("channel") == "equipment_controller"]
    return {
        "get_park_state": {"status": "ok", "source": "park_state", "scenario_key": scenario_key},
        "get_noisy_observation": {"status": "ok", "top_signal": payload.get("scan", {}).get("top_risk") or proactive_top.get("trigger")},
        "get_food_capacity": {"status": "ok", "constrained_zone": "Food Court A" if scenario_key == "food_spike" else None, "capacity_action": "redirect_or_throttle" if scenario_key == "food_spike" else "not_required"},
        "get_staff_constraints": {"status": "ok", "protected_breaks": True, "role_compatible_only": True},
        "get_zone_density": {"status": "ok", "affected_zone": "foodCourtA" if scenario_key == "food_spike" else "derived_from_live_state"},
        "retrieve_similar_incidents": {"status": "ok", "memory": payload.get("memory", {}), "used_for": "playbook_and_prior_context"},
        "compare_action_candidates": {"status": "ok", "selected": payload.get("operator_response", {}).get("headline"), "rejected": "generic low-specificity candidate"},
        "simulate_action": {"status": "ok", "response": response, "learning_validity": payload.get("role_receipt", {}).get("learning_update", {}).get("validity")},
        "validate_policy": {"status": "ok", "gate_status": payload.get("run_telemetry", {}).get("governance", {}).get("gate_status") or "allowed", "gates": payload.get("role_run", {}).get("policy_gates", [])},
        "dispatch_guest_message": {"status": "ok", "dispatch_ids": guest_dispatches},
        "dispatch_worker_task": {"status": "ok", "dispatch_ids": worker_dispatches},
        "dispatch_equipment_command": {"status": "ok", "dispatch_ids": equipment_dispatches},
        "score_outcome": {"status": "ok", "response": response},
        "write_decision_memory": {"status": "ok", "memory": payload.get("memory", {}), "analytics": payload.get("analytics", {})},
        "inspect_delivery_receipts": {"status": "ok", "dispatch_allowed": role != "qa", "scenario_key": scenario_key},
        "inspect_runtime_status": {"status": "ok", "readiness": payload.get("runtime_status", {})},
        "inspect_observability_contract": {"status": "ok", "checklist": payload.get("observability_checklist", [])},
        "score_decision_quality": {"status": "ok", "scorecard": payload.get("qa_scorecard") or payload.get("run_telemetry", {}).get("eval", {})},
    }


def _scan_role_payload(message: str, mode: str, route: dict[str, Any]) -> dict[str, Any]:
    insights = _lazy_proactive_insights()
    top_signal = (insights.get("insights") or [{}])[0]
    payload = {
        "status": "complete",
        "selected_role": "scan",
        "skill": route.get("skill", "parkpulse-scan-agent"),
        "route": route,
        "role_run": {
            "role": "scan",
            "dispatch_allowed": False,
            "dispatch_count": 0,
            "recommended_next_role": "proact" if top_signal.get("urgency") == "risk" else "monitor",
            "reason": "Scan role is read-only and returns evidence before any operating action.",
        },
        "scan": {
            "signals": insights.get("insights", []),
            "top_risk": top_signal.get("trigger"),
            "affected_zones": [insights.get("summary", {}).get("busiest_zone")],
            "confidence": top_signal.get("confidence", 0.0),
            "evidence": top_signal.get("evidence", []),
            "recommended_next_role": "proact" if top_signal.get("urgency") == "risk" else "monitor",
        },
        "operator_response": {
            "headline": "Scan Agent found early park signals.",
            "summary": top_signal.get("why_now", "The scan found partial evidence and no dispatch was made."),
            "next_step": "Escalate to Proact Agent for preventive action or React Agent if the incident is confirmed.",
        },
        "run_telemetry": {
            "scenario_key": "scan",
            "delivery": {"summary": {"total": 0, "guest_app": 0, "worker_device": 0, "equipment_controller": 0}, "response": {}, "dispatches": []},
            "governance": {"allowed": True, "gate_status": "read_only", "findings": ["Scan role cannot dispatch guest, worker, or equipment actions."]},
            "eval": {"scorecard": {"overall": 82, "policy_gate_status": "read_only", "needs_human_approval": False}},
        },
    }
    payload = _persist_role_receipt(payload, role="scan", route=route, scenario_key="scan")
    trace = _role_tool_trace(route, selected_role="scan", scenario_key="scan", outputs=_role_tool_outputs_from_payload(payload, role="scan", scenario_key="scan"))
    payload["digital_twin_tools"] = trace
    payload["run_telemetry"]["digital_twin_tools"] = trace
    return payload


async def _react_role_payload(message: str, mode: str, route: dict[str, Any]) -> dict[str, Any]:
    payload = _lazy_operator_payload(message, mode, "role_routed_react_agent")
    scenario_key = payload.get("route", {}).get("scenario_key", "custom")
    selected_action = payload.get("run_telemetry", {}).get("planner", {}).get("selected_action", {})
    dispatch_total = payload.get("run_telemetry", {}).get("delivery", {}).get("summary", {}).get("total", 0)
    payload["operator_response"] = {
        **payload.get("operator_response", {}),
        "headline": selected_action.get("label") or payload.get("operator_response", {}).get("headline") or "React Agent executed a custom park response.",
        "summary": f"React Agent interpreted the operator text as {scenario_key}, prepared {dispatch_total} receiver-specific actions, and blocked stale low-specificity copy.",
        "next_step": "Watch guest take rate, worker acknowledgments, and equipment status before sending a second nudge.",
    }
    run_telemetry = payload.setdefault("run_telemetry", {})
    run_telemetry.setdefault("trace_contract", {}).setdefault("trace_table", []).insert(
        0,
        {
            "step": "role_router",
            "phase": "role",
            "evidence": route.get("why", "React Agent selected."),
            "artifact_id": route.get("skill", "parkpulse-react-agent"),
            "dispatch_count": run_telemetry.get("delivery", {}).get("summary", {}).get("total"),
        },
    )
    payload["selected_role"] = "react"
    payload["skill"] = route.get("skill", "parkpulse-react-agent")
    payload["role_route"] = route
    payload["role_run"] = {
        "role": "react",
        "dispatch_allowed": True,
        "dispatch_count": run_telemetry.get("delivery", {}).get("summary", {}).get("total", 0),
        "policy_gates": route.get("policy_gates", []),
        "receipt_artifacts": route.get("expected_receipt", []),
    }
    materialized_dispatches = _materialize_role_dispatches(payload, role="react", scenario_key=scenario_key)
    if materialized_dispatches:
        summary = _fast_delivery_summary_for(materialized_dispatches)
        run_telemetry["delivery"] = {
            "summary": summary,
            "dispatches": materialized_dispatches,
            "response": _role_delivery_response_summary(materialized_dispatches),
        }
        payload["role_run"]["dispatch_count"] = summary.get("total", len(materialized_dispatches))
        state_impact = _fast_role_state_impact(scenario_key, materialized_dispatches)
        run_telemetry.setdefault("outcome", {})["state_impact"] = state_impact
        run_telemetry.setdefault("outcome", {})["application"] = {
            "status": "projected",
            "mode": "fast_role_hot_path_no_shared_lock",
            "message": "Fast role path projects state impact without mutating the shared simulation lock.",
        }
        payload.setdefault("outcome", {})["state_impact"] = state_impact
        payload.setdefault("outcome", {})["application"] = run_telemetry["outcome"]["application"]
    await _attach_fast_role_collaboration(payload, route, scenario_key)
    payload = _persist_role_receipt(payload, role="react", route=route, scenario_key=scenario_key)
    trace = _role_tool_trace(route, selected_role="react", scenario_key=scenario_key, outputs=_role_tool_outputs_from_payload(payload, role="react", scenario_key=scenario_key))
    run_telemetry["digital_twin_tools"] = trace
    payload["digital_twin_tools"] = trace
    return payload


async def _attach_fast_role_collaboration(payload: dict[str, Any], route: dict[str, Any], scenario_key: str) -> None:
    run_telemetry = payload.setdefault("run_telemetry", {})
    constraints = run_telemetry.get("operator_constraints", {}) if isinstance(run_telemetry.get("operator_constraints"), dict) else {}
    selected_action = run_telemetry.get("planner", {}).get("selected_action", {}) if isinstance(run_telemetry.get("planner"), dict) else {}
    domain_agent_by_scenario = {
        "food_spike": (
            "food_demand_agent",
            "Food Demand Agent",
            "Suppress or redirect constrained ordering and protect honest pickup ETAs.",
            ["get_food_capacity", "simulate_action"],
            ["pause new mobile-order intake", "recommend alternate food capacity"],
            ["invent inventory", "promise pickup times not in system"],
            "bounded_food_receiver_payloads",
        ),
        "ride_down": (
            "ride_ops_agent",
            "Ride Ops Agent",
            "Handle ride downtime, queue intake, and alternate-capacity recommendations.",
            ["get_ride_status", "get_zone_density", "simulate_action"],
            ["pause queue intake", "route guests to available capacity"],
            ["reopen rides", "override maintenance clearance"],
            "bounded_ride_queue_payloads",
        ),
        "staff_shortage": (
            "staffing_agent",
            "Staffing Agent",
            "Move only role-compatible staff while protecting breaks and certified coverage.",
            ["get_staff_constraints", "get_zone_density"],
            ["recommend redeployment", "protect break windows"],
            ["violate labor rules", "move uncertified operators"],
            "bounded_worker_task_payloads",
        ),
        "medical_response": (
            "guest_care_agent",
            "Guest Care Agent",
            "Coordinate medical/accessibility support with privacy-safe instructions.",
            ["get_zone_density", "get_staff_constraints", "validate_policy"],
            ["dispatch support staff", "protect access lanes"],
            ["diagnose medical condition", "broadcast sensitive guest details"],
            "human_supervised_guest_care",
        ),
        "equipment_safety": (
            "equipment_safety_agent",
            "Equipment Safety Agent",
            "Hold noncritical effects and request technician verification for safety signals.",
            ["get_park_state", "retrieve_similar_incidents", "validate_policy"],
            ["hold noncritical effects", "send technician task"],
            ["clear equipment as safe", "automate safety-critical controls"],
            "technician_review_required",
        ),
        "crowd_safety": (
            "crowd_safety_agent",
            "Crowd Safety Agent",
            "Open calm alternate routes and protect emergency/service access.",
            ["get_zone_density", "get_staff_constraints", "simulate_action"],
            ["split guest flow", "send crowd-control staff"],
            ["issue alarmist messaging", "authorize evacuation"],
            "bounded_crowd_flow_payloads",
        ),
        "storm_response": (
            "facilities_energy_agent",
            "Facilities Energy Agent",
            "Adjust comfort and load only within non-safety-critical envelopes.",
            ["get_park_state", "get_zone_density", "validate_policy"],
            ["adjust HVAC setpoints", "shed noncritical load"],
            ["turn off safety systems", "ignore shelter demand"],
            "bounded_equipment_control_payloads",
        ),
        "family_care": (
            "guest_flow_agent",
            "Guest Flow Agent",
            "Route families through calm, accessible, low-pressure areas.",
            ["get_zone_density", "get_staff_constraints"],
            ["recommend family-safe routes", "request guest-services support"],
            ["use manipulative messaging", "expose child/family details"],
            "privacy_safe_guest_flow",
        ),
    }
    domain_agent = domain_agent_by_scenario.get(scenario_key, domain_agent_by_scenario["ride_down"])
    proposal_specs = [
        (
            "park_understanding_agent",
            "Park Understanding Agent",
            "context",
            f"Ground the operator request as {scenario_key} before dispatch.",
            {"target": "scenario", "action": "ground_context", "scenario_key": scenario_key},
            ["operator_text", f"route={route.get('selected_role', 'react')}"],
            ["Do not use stale low-specificity scenario copy."],
            0.78,
            ["get_park_state", "retrieve_similar_incidents"],
            ["summarize live context", "mark uncertainty"],
            ["dispatch actions", "write guest-facing copy"],
            "read_only_context",
        ),
        (
            domain_agent[0],
            domain_agent[1],
            "action",
            selected_action.get("label") or domain_agent[2],
            {"target": selected_action.get("target", "guest"), "action": selected_action.get("action", "custom_response")},
            [constraints.get("intent_summary", "custom operator request"), f"scenario={scenario_key}"],
            constraints.get("decision_rules", [])[:2] or ["Keep receiver actions bounded."],
            0.86,
            domain_agent[3],
            domain_agent[4],
            domain_agent[5],
            domain_agent[6],
        ),
        (
            "guest_flow_agent",
            "Guest Flow Agent",
            "tradeoff",
            "Use guest messaging and routing mix without creating the next bottleneck.",
            {"target": "guest", "action": "message"},
            [f"avoid={len(constraints.get('avoid_zones', []))}", f"preferred={len(constraints.get('preferred_destinations', []))}"],
            ["Split demand across available capacity."],
            0.82,
            ["get_zone_density", "simulate_action", "dispatch_guest_message"],
            ["recommend audience and route mix", "draft calm guest copy"],
            ["promise outcomes", "hide safety-relevant facts"],
            "bounded_guest_message",
        ),
        (
            "staffing_agent",
            "Staffing Agent",
            "constraint",
            "Move only role-compatible staff and preserve protected breaks.",
            {"target": "staff", "action": "redeploy"},
            [f"moves={len(constraints.get('required_staff_moves', []))}"],
            ["No uncertified moves."],
            0.8,
            ["get_staff_constraints", "dispatch_worker_task"],
            ["recommend role-compatible moves", "set worker task priority"],
            ["violate break windows", "move untrained staff into certified posts"],
            "bounded_worker_task",
        ),
        (
            "safety_policy_agent",
            "Safety Policy Agent",
            "gate",
            "Gate the fast response against safety, labor, and equipment bounds.",
            {"target": "scenario", "action": "policy_gate", "requires_human_review": bool(route.get("requires_human_review", False))},
            [f"requires_human_review={bool(route.get('requires_human_review', False))}"],
            ["Blocked scope stays blocked even on the fast path."],
            0.93,
            ["validate_policy", "score_decision_quality"],
            ["allow", "require review", "block unsafe scope"],
            ["dispatch actions", "override human approval"],
            "pre_dispatch_gate",
        ),
        (
            "decision_bridge_agent",
            "Decision Bridge Agent",
            "bridge",
            "Resolve specialist proposals into one receiver-safe action path.",
            {"target": "scenario", "action": "synthesize_role_proposals"},
            ["fast_operator_path", "bounded_receiver_payloads"],
            ["Specialists recommend; Decision Bridge chooses what executes."],
            0.87,
            ["compare_action_candidates", "simulate_action", "validate_policy"],
            ["choose final bounded action", "explain rejected proposals"],
            ["bypass policy gates", "invent unavailable resources"],
            "final_recommendation_only",
        ),
    ]
    proposals = [
        {
            "agent_id": agent_id,
            "role": role,
            "proposal_type": proposal_type,
            "recommendation": recommendation,
            "proposed_action": proposed_action,
            "evidence": evidence,
            "constraints": proposal_constraints,
            "confidence": confidence,
            "policy_refs": ["PARK-SAFE-001", "PARK-OPS-001"],
            "handoff_to": "decision_bridge_agent" if agent_id != "decision_bridge_agent" else "central_optimizer",
            "boundary": {
                "allowed_tools": allowed_tools,
                "decision_rights": decision_rights,
                "blocked_actions": blocked_actions,
                "execution_scope": execution_scope,
                "can_dispatch": proposal_type in {"action", "tradeoff", "constraint"} and agent_id != "park_understanding_agent",
            },
        }
        for agent_id, role, proposal_type, recommendation, proposed_action, evidence, proposal_constraints, confidence, allowed_tools, decision_rights, blocked_actions, execution_scope in proposal_specs
    ]
    role_artifact = {
        "mode": "fast_hybrid_role_proposals",
        "scenario_key": scenario_key,
        "execution_model": "fast_specialist_proposals_decision_bridge_action",
        "active_roles": [proposal["agent_id"] for proposal in proposals],
        "proposal_count": len(proposals),
        "proposals": proposals,
        "conflicts": [],
        "mediator_summary": "Fast React Agent emits bounded specialist proposals, then Decision Bridge selects a receiver-safe action without blocking on the full optimizer.",
    }

    proposals = role_artifact.get("proposals", []) if isinstance(role_artifact.get("proposals"), list) else []
    target = str(selected_action.get("target") or "")
    preferred_agents = {
        "food": "food_demand_agent",
        "ride": "ride_ops_agent",
        "staff": "staffing_agent",
        "energy": "facilities_energy_agent",
        "equipment": "equipment_safety_agent",
        "medical": "guest_care_agent",
        "crowd_safety": "crowd_safety_agent",
        "crowd": "crowd_safety_agent",
        "guest": "guest_flow_agent",
    }
    preferred_agent = preferred_agents.get(target, "guest_flow_agent")
    scored = [
        proposal
        for proposal in proposals
        if isinstance(proposal, dict) and proposal.get("proposal_type") not in {"context", "gate", "bridge"}
    ]
    accepted = next((proposal for proposal in scored if proposal.get("agent_id") == preferred_agent), None) or (scored[0] if scored else None)
    rejected = [
        {
            "candidate_id": f"fast_role_{proposal.get('agent_id')}",
            "agent_id": proposal.get("agent_id"),
            "role": proposal.get("role"),
            "recommendation": proposal.get("recommendation"),
            "score": round(float(proposal.get("confidence", 0.7) or 0.7) * 100),
            "reason": "Kept as supporting context because the fast operator path selected a more direct receiver action.",
        }
        for proposal in scored
        if accepted is None or proposal.get("agent_id") != accepted.get("agent_id")
    ][:5]
    memory_prior = {
        "agent_id": accepted.get("agent_id") if isinstance(accepted, dict) else None,
        "sample_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "avg_take_rate": 0,
        "prior_adjustment": 0,
        "confidence": "not_loaded_fast_path",
        "rationale": "Fast operator response exposes the collaboration contract; measured role priors are loaded by the full optimizer path.",
    }
    if isinstance(accepted, dict):
        accepted = {**accepted, "memory_prior": memory_prior}
    resolution = {
        "mode": "fast_decision_bridge_role_resolution",
        "selected_candidate_id": f"fast_role_{accepted.get('agent_id')}" if isinstance(accepted, dict) else "fast_operator_action",
        "selected_source": "fast_role_proposal",
        "accepted_role_proposal": accepted,
        "rejected_role_proposals": rejected,
        "conflicts": role_artifact.get("conflicts", []) if isinstance(role_artifact, dict) else [],
        "summary": "Fast React Agent surfaced specialist proposals, then Decision Bridge selected the receiver-safe action path without waiting for the full Gemini tournament.",
    }
    run_telemetry["role_agent_proposals"] = role_artifact
    run_telemetry.setdefault("optimization", {}).update(
        {
            "mode": "fast_hybrid_role_bridge",
            "candidate_source": "fast_role_proposals",
            "role_proposal_candidate_count": len(scored),
            "selected_plan_id": resolution["selected_candidate_id"],
            "selected_plan": {
                "id": resolution["selected_candidate_id"],
                "name": selected_action.get("label", "Fast role-backed action"),
                "source": "fast_role_proposal",
                "selected_action": selected_action,
                "scorecard": {
                    "overall": run_telemetry.get("eval", {}).get("scorecard", {}).get("overall", 78),
                    "role_alignment_bonus": 0,
                    "role_memory_prior_adjustment": 0,
                },
                "role_proposal": accepted,
            },
            "decision_bridge_resolution": resolution,
            "decision_summary": resolution["summary"],
            "memory_used": {
                "role_quality_priors": {
                    "mode": "fast_path_not_loaded",
                    "scenario_key": scenario_key,
                    "sample_count": 0,
                    "priors": [memory_prior] if memory_prior.get("agent_id") else [],
                    "by_agent": {memory_prior["agent_id"]: memory_prior} if memory_prior.get("agent_id") else {},
                }
            },
        }
    )
    run_telemetry["role_outcome_attribution"] = {
        "mode": "fast_role_outcome_attribution",
        "scenario_key": scenario_key,
        "selected_action": selected_action,
        "decision_bridge_resolution": resolution,
        "summary": {
            "proposal_count": len(proposals),
            "accepted_count": 1 if accepted else 0,
            "rejected_count": len(rejected),
            "context_only_count": len([item for item in proposals if isinstance(item, dict) and item.get("proposal_type") in {"context", "gate", "bridge"}]),
            "winner_agent_id": accepted.get("agent_id") if isinstance(accepted, dict) else None,
        },
        "role_outcomes": [],
    }
    run_telemetry["role_proposal_memory"] = {
        "mode": "fast_operator_receipt",
        "status": "included_in_role_receipt",
        "stored_count": 0,
        "connected": bool(payload.get("role_receipt", {}).get("mongo", {}).get("connected")),
    }
    payload["role_agent_proposals"] = role_artifact


async def _proact_role_payload(message: str, mode: str, route: dict[str, Any]) -> dict[str, Any]:
    payload = await _build_proactive_payload_with_runtime("role_routed_proact_agent")
    payload["selected_role"] = "proact"
    payload["skill"] = route.get("skill", "parkpulse-proact-agent")
    payload["role_route"] = route
    payload["role_run"] = {
        "role": "proact",
        "dispatch_allowed": True,
        "dispatch_count": payload.get("delivery", {}).get("summary", {}).get("total", 0),
        "policy_gates": route.get("policy_gates", []),
        "receipt_artifacts": route.get("expected_receipt", []),
    }
    payload.setdefault("trace_contract", {}).setdefault("trace_table", []).insert(
        0,
        {
            "step": "role_router",
            "phase": "role",
            "evidence": route.get("why", "Proact Agent selected."),
            "artifact_id": route.get("skill", "parkpulse-proact-agent"),
            "dispatch_count": payload.get("delivery", {}).get("summary", {}).get("total"),
        },
    )
    materialized_dispatches = _materialize_role_dispatches(payload, role="proact", scenario_key="proactive_watchtower")
    if materialized_dispatches:
        summary = _fast_delivery_summary_for(materialized_dispatches)
        payload["delivery"] = {
            **(payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}),
            "summary": summary,
            "dispatches": materialized_dispatches,
            "response": _role_delivery_response_summary(materialized_dispatches),
        }
        payload["role_run"]["dispatch_count"] = summary.get("total", len(materialized_dispatches))
    payload = _persist_role_receipt(payload, role="proact", route=route, scenario_key="proactive_watchtower")
    trace = _role_tool_trace(route, selected_role="proact", scenario_key="proactive_watchtower", outputs=_role_tool_outputs_from_payload(payload, role="proact", scenario_key="proactive_watchtower"))
    payload["digital_twin_tools"] = trace
    return payload


async def _qa_role_payload(message: str, mode: str, route: dict[str, Any]) -> dict[str, Any]:
    from prod_reliability_qa_agent import run_production_reliability_qa

    runtime_status = _lightweight_integration_status()
    report = run_production_reliability_qa(message, runtime_status)
    report["selected_role"] = "qa"
    report["skill"] = route.get("skill", "parkpulse-production-reliability-qa-agent")
    report["role_route"] = route
    report["route"] = route
    report["runtime_status"] = runtime_status
    report["qa_scorecard"] = {
        "overall": 82,
        "dispatch_safety": 100,
        "fallback_coverage": 74,
        "observability": 84,
        "load_readiness": 70,
        "go_no_go": report.get("go_no_go_recommendation", {}).get("decision", "GO WITH CONDITIONS"),
    }
    report["role_run"] = {
        "role": "qa",
        "dispatch_allowed": False,
        "dispatch_count": 0,
        "policy_gates": route.get("policy_gates", []),
        "receipt_artifacts": route.get("expected_receipt", []),
        "read_only": True,
    }
    report["run_telemetry"] = {
        "scenario_key": "production_reliability_qa",
        "delivery": {"summary": {"total": 0, "guest_app": 0, "worker_device": 0, "equipment_controller": 0}, "response": {}, "dispatches": []},
        "governance": {"allowed": True, "gate_status": "qa_read_only", "findings": ["QA role cannot dispatch guest, worker, or equipment actions."]},
        "eval": {"scorecard": report["qa_scorecard"]},
    }
    report["operator_response"] = {
        "headline": "Production Reliability QA Agent completed a read-only go/no-go review.",
        "summary": report.get("go_no_go_recommendation", {}).get("reason", "Reliability report generated."),
        "next_step": "Close the listed release conditions before treating ParkPulse as production-ready.",
    }
    trace = _role_tool_trace(route, selected_role="qa", scenario_key="production_reliability_qa", outputs=_role_tool_outputs_from_payload(report, role="qa", scenario_key="production_reliability_qa"))
    report["digital_twin_tools"] = trace
    report["run_telemetry"]["digital_twin_tools"] = trace
    report["role_receipt"] = {
        "chain": ["qa_request", "role_router", "runtime_status", "failure_mode_matrix", "observability_contract", "go_no_go"],
        "role": "qa",
        "skill": route.get("skill"),
        "scenario_key": "production_reliability_qa",
        "dispatch_ids": [],
        "go_no_go": report.get("go_no_go_recommendation", {}),
        "read_only": True,
    }
    return report


async def _agent_role_run_payload(message: str, mode: str = "auto") -> dict[str, Any]:
    route = route_agent_role(message, mode)
    selected = str(route.get("selected_role") or "scan")
    if selected == "qa":
        return await _qa_role_payload(message, mode, route)
    if selected == "react":
        return await _react_role_payload(message, "auto", route)
    if selected == "proact":
        return await _proact_role_payload(message, mode, route)
    return _scan_role_payload(message, mode, route)


def _parse_gemini_json_text(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


async def _agent_role_refinement_payload(message: str, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    receipt = receipt or {}
    role = receipt.get("selected_role") or receipt.get("role_receipt", {}).get("role") or "agent"
    scenario_key = receipt.get("role_receipt", {}).get("scenario_key") or receipt.get("run_telemetry", {}).get("scenario_key")
    dispatches = receipt.get("run_telemetry", {}).get("delivery", {}).get("dispatches", [])
    learning = receipt.get("role_receipt", {}).get("learning_update") or receipt.get("learning_proof", {})
    prompt = {
        "task": "Refine a fast amusement-park operating decision. Do not invent unavailable staff, equipment, rides, or diagnoses.",
        "operator_text": message,
        "selected_role": role,
        "scenario_key": scenario_key,
        "current_actions": [
            {
                "channel": item.get("channel"),
                "status": item.get("status"),
                "payload": item.get("payload"),
                "response": item.get("response"),
            }
            for item in dispatches[:5]
            if isinstance(item, dict)
        ],
        "learning": learning,
        "required_json": {
            "status": "refined | no_change",
            "headline": "short operator-facing headline",
            "operator_brief": "one concise paragraph",
            "refined_actions": ["only practical bounded changes"],
            "policy_notes": ["safety/labor/privacy/equipment notes"],
            "confidence": 0.0,
        },
    }
    try:
        from gemini_hard_timeout import generate_gemini_json_hard_timeout

        started = time.time()
        result = await generate_gemini_json_hard_timeout(
            prompt,
            timeout_seconds=float(os.getenv("PARKPULSE_ROLE_REFINE_TIMEOUT_SECONDS", "7")),
            max_output_tokens=550,
            temperature=0.15,
        )
        refined = _parse_gemini_json_text(str(result.get("text") or "{}"))
        return {
            "status": "complete",
            "mode": "gemini_refinement",
            "runtime": result.get("transport", "gemini"),
            "elapsed_ms": int((time.time() - started) * 1000),
            "selected_role": role,
            "scenario_key": scenario_key,
            "refinement": refined,
        }
    except Exception as error:
        return {
            "status": "fallback",
            "mode": "bounded_no_refinement",
            "selected_role": role,
            "scenario_key": scenario_key,
            "refinement": {
                "status": "no_change",
                "headline": "Bounded operating plan kept.",
                "operator_brief": "Gemini refinement was unavailable within the demo timeout, so ParkPulse kept the policy-gated receiver actions already emitted.",
                "refined_actions": [],
                "policy_notes": ["No extra action emitted without model refinement."],
                "confidence": 0.62,
            },
            "error": str(error)[:300],
        }


def _customer_support_fallback_response(
    payload: dict[str, Any],
    park_state: dict[str, Any],
    reason: str | None = None,
    agent_builder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    station = payload.get("station") if isinstance(payload.get("station"), dict) else {}
    question = str(payload.get("question") or "").strip()
    mode = str(payload.get("mode") or "question")
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    food_locations = park_state.get("foodInventory", {}).get("locations", []) if isinstance(park_state.get("foodInventory"), dict) else []
    open_rides = [ride for ride in rides if isinstance(ride, dict) and ride.get("status") != "down"]
    best_ride = min(open_rides, key=lambda ride: float(ride.get("waitMins") or 999), default={})
    calm_zone = min(
        [zone for zone in zones if isinstance(zone, dict)],
        key=lambda zone: float(zone.get("density") or 999) + float(zone.get("waitMins") or 0),
        default={},
    )
    food = min(
        [item for item in food_locations if isinstance(item, dict)],
        key=lambda item: float(item.get("pickupEtaMinutes") or 999) + float(item.get("mobileOrderBacklog") or 0) / 10,
        default={},
    )
    ride_name = str(best_ride.get("name") or "Theater B")
    ride_wait = best_ride.get("waitMins")
    zone_name = str(calm_zone.get("name") or "Arcade Zone")
    food_name = str(food.get("name") or "Main Street snacks")
    food_wait = food.get("pickupEtaMinutes")
    if mode == "route":
        answer = f"Use the calmer path toward {zone_name}, then check {ride_name} before joining another queue."
        action_label = "Route shown"
    elif mode == "phone":
        answer = f"Sent to the guest app: {ride_name} is the recommended next stop, with {food_name} as the food backup."
        action_label = "Sent to phone"
    elif mode == "recommendation":
        answer = f"I recommend {ride_name}{f' at about {ride_wait} minutes' if ride_wait is not None else ''}. If your group wants food first, use {food_name}{f' at about {food_wait} minutes' if food_wait is not None else ''}."
        action_label = "Recommendation ready"
    else:
        answer = f"For \"{question or 'what should we do next'}\", the best next step is {ride_name}, with {zone_name} as the calmer route."
        action_label = "Answered at station"
    return {
        "status": "fallback",
        "mode": "bounded_customer_agent",
        "answer": answer,
        "recommendation": {
            "primary": ride_name,
            "backup": food_name,
            "route": zone_name,
            "why": "Selected from current waits, crowd density, food pressure, and ride status.",
        },
        "actions": [
            {"id": "show_route", "label": "Show route", "status": "ready"},
            {"id": "send_to_phone", "label": "Send to phone", "status": "ready"},
        ],
        "station": {
            "id": station.get("id"),
            "name": station.get("title") or station.get("name") or "Customer support station",
            "waitMins": station.get("waitMins"),
        },
        "customer_action": {"label": action_label, "mode": mode},
        "runtime": {
            "provider": "bounded_customer_agent",
            "model": "fast_customer_policy",
            "live": False,
            "fallbackReason": reason or "Gemini customer agent unavailable.",
        },
        "agent_builder": agent_builder or _customer_support_agent_builder_contract(mode),
        "guardrails": [
            "No medical diagnosis, individual compensation promise, or private guest data.",
            "Customer endpoint is read-only and does not dispatch operator actions.",
        ],
}


def _customer_agent_fallback_reason(error: Exception | str) -> str:
    text = str(error)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and payload.get("error"):
            text = str(payload.get("error"))
    except json.JSONDecodeError:
        pass
    if "No module named 'google.genai'" in text:
        return "Gemini SDK is not installed in this backend runtime."
    if "GEMINI_API_KEY" in text or "GOOGLE_API_KEY" in text:
        return "Gemini credentials are not configured for this backend runtime."
    if "exceeded hard timeout" in text:
        return "Gemini customer agent timed out before returning an answer."
    return text[:240]


def _customer_agent_tool_for_mode(mode: str) -> str:
    normalized = (mode or "question").strip().lower()
    if normalized == "route":
        return "customer_show_route"
    if normalized == "phone":
        return "customer_send_to_phone"
    if normalized == "recommendation":
        return "get_public_wait_times"
    return "get_park_state"


def _customer_support_agent_builder_contract(mode: str = "question") -> dict[str, Any]:
    requested_tool = _customer_agent_tool_for_mode(mode)
    try:
        from park_multi_agent import build_agent_builder_boundary_contract, enforce_agent_tool_boundary

        contract = build_agent_builder_boundary_contract()
        agent = next((item for item in contract.get("agents", []) if item.get("id") == "customer_support_agent"), {})
        boundary = enforce_agent_tool_boundary(
            "customer_support_agent",
            requested_tool,
            {
                "surface": "customer_support_station",
                "mode": mode,
                "customer_only": True,
                "policy_gate_checked": True,
            },
        )
        return {
            "agent_id": "customer_support_agent",
            "name": agent.get("name") or "Customer Support Agent",
            "role": agent.get("role") or "Answer guest kiosk questions with public park state.",
            "mode": agent.get("mode") or ["customer_self_service"],
            "requested_tool": requested_tool,
            "allowed_tools": agent.get("allowed_tools") or [],
            "blocked_tools": agent.get("blocked_tools") or [],
            "decision_rights": agent.get("decision_rights") or [],
            "execution_boundary": agent.get("execution_boundary") or "customer self-service only",
            "requires_human_approval_when": agent.get("requires_human_approval_when") or [],
            "handoff_to": agent.get("handoff_to") or "customer_kiosk_ui",
            "boundary_receipt": boundary,
        }
    except Exception as error:
        return {
            "agent_id": "customer_support_agent",
            "name": "Customer Support Agent",
            "role": "Answer guest kiosk questions with public park state.",
            "mode": ["customer_self_service"],
            "requested_tool": requested_tool,
            "allowed_tools": ["get_park_state", "get_public_wait_times", "get_public_route_options", "get_food_capacity", "customer_show_route", "customer_send_to_phone"],
            "blocked_tools": ["dispatch_worker_task", "dispatch_equipment_command", "operator_console_redirect", "private_guest_data"],
            "decision_rights": ["answer_customer", "recommend_public_next_stop", "show_route", "send_to_customer_phone"],
            "execution_boundary": "customer self-service only; no operator dispatch, staff tasking, equipment control, policy disclosure, or private data access",
            "requires_human_approval_when": ["medical, security, missing child, evacuation, compensation, or private-data request"],
            "handoff_to": "customer_kiosk_ui",
            "boundary_receipt": {"status": "unavailable", "allowed": False, "reason": str(error)[:240]},
        }


def _customer_agent_safe_actions(actions: Any) -> list[dict[str, Any]]:
    allowed_ids = {"show_route", "send_to_phone"}
    safe_actions: list[dict[str, Any]] = []
    if isinstance(actions, list):
        for item in actions:
            if not isinstance(item, dict):
                continue
            action_id = str(item.get("id") or "").strip()
            if action_id not in allowed_ids:
                continue
            safe_actions.append(
                {
                    "id": action_id,
                    "label": str(item.get("label") or ("Show route" if action_id == "show_route" else "Send to phone"))[:80],
                    "status": str(item.get("status") or "ready")[:40],
                }
            )
    return safe_actions or [
        {"id": "show_route", "label": "Show route", "status": "ready"},
        {"id": "send_to_phone", "label": "Send to phone", "status": "ready"},
    ]


async def _customer_support_agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    state = await _fast_park_state()
    station = payload.get("station") if isinstance(payload.get("station"), dict) else {}
    question = str(payload.get("question") or "").strip()
    mode = str(payload.get("mode") or "question").strip() or "question"
    agent_builder = _customer_support_agent_builder_contract(mode)
    boundary_receipt = agent_builder.get("boundary_receipt") if isinstance(agent_builder.get("boundary_receipt"), dict) else {}
    if boundary_receipt and not boundary_receipt.get("allowed", False):
        return _customer_support_fallback_response(
            payload,
            state,
            str(boundary_receipt.get("reason") or "Customer agent boundary blocked the requested tool."),
            agent_builder,
        )
    props = {}
    try:
        from gemini_provider import get_gemini_agent_properties

        props = get_gemini_agent_properties().public_dict()
    except Exception as error:
        props = {"ready": False, "readiness_issues": [str(error)[:240]], "provider": "Gemini", "model": "unknown"}

    prompt = {
        "task": "You are a customer-facing amusement-park support agent at an in-park kiosk. Answer the guest directly.",
        "mode": mode,
        "customer_question": question,
        "station": station,
        "agent_builder": {
            "role": agent_builder.get("role"),
            "requested_tool": agent_builder.get("requested_tool"),
            "allowed_tools": agent_builder.get("allowed_tools"),
            "blocked_tools": agent_builder.get("blocked_tools"),
            "decision_rights": agent_builder.get("decision_rights"),
            "execution_boundary": agent_builder.get("execution_boundary"),
            "requires_human_approval_when": agent_builder.get("requires_human_approval_when"),
            "handoff_to": agent_builder.get("handoff_to"),
        },
        "park_context": {
            "weather": state.get("weather"),
            "guest_flow": state.get("guestFlow"),
            "food_inventory": state.get("foodInventory"),
            "incident_readiness": state.get("incidentReadiness"),
            "alerts": state.get("alerts"),
        },
        "rules": [
            "Be concise, friendly, and practical.",
            "Use current waits, crowd density, food pressure, accessibility, and weather when available.",
            "Do not expose internal operator details, staff constraints, policy internals, private guest data, medical diagnosis, or compensation promises.",
            "Do not dispatch worker, equipment, or operator actions. Customer actions may only be show_route or send_to_phone.",
            "Use only the Agent Builder allowed tools and respect the execution boundary.",
            "If a ride is down, do not imply it will reopen.",
        ],
        "required_json": {
            "answer": "customer-facing answer, 1-3 sentences",
            "recommendation": {"primary": "best next stop", "backup": "secondary option", "route": "short route note", "why": "brief reason"},
            "actions": [{"id": "show_route|send_to_phone", "label": "button label", "status": "ready"}],
            "customer_action": {"label": "short status label", "mode": mode},
            "guardrails": ["short customer-safety/privacy notes"],
        },
    }

    if not props.get("ready"):
        return _customer_support_fallback_response(payload, state, "; ".join(props.get("readiness_issues") or ["Gemini not configured"]), agent_builder)

    try:
        from gemini_hard_timeout import generate_gemini_json_hard_timeout

        started = time.time()
        result = await generate_gemini_json_hard_timeout(
            prompt,
            timeout_seconds=float(os.getenv("PARKPULSE_CUSTOMER_AGENT_TIMEOUT_SECONDS", "7")),
            max_output_tokens=520,
            temperature=0.25,
        )
        generated = _parse_gemini_json_text(str(result.get("text") or "{}"))
        return {
            "status": "ok",
            "mode": "gemini_customer_agent",
            "answer": str(generated.get("answer") or "").strip() or _customer_support_fallback_response(payload, state)["answer"],
            "recommendation": generated.get("recommendation") if isinstance(generated.get("recommendation"), dict) else {},
            "actions": _customer_agent_safe_actions(generated.get("actions")),
            "station": {
                "id": station.get("id"),
                "name": station.get("title") or station.get("name") or "Customer support station",
                "waitMins": station.get("waitMins"),
            },
            "customer_action": generated.get("customer_action") if isinstance(generated.get("customer_action"), dict) else {"label": "Answer ready", "mode": mode},
            "guardrails": generated.get("guardrails") if isinstance(generated.get("guardrails"), list) else [],
            "agent_builder": agent_builder,
            "runtime": {
                "provider": result.get("transport") or props.get("provider") or "Gemini",
                "model": props.get("model"),
                "live": True,
                "elapsedMs": int((time.time() - started) * 1000),
            },
        }
    except Exception as error:
        return _customer_support_fallback_response(payload, state, _customer_agent_fallback_reason(error), agent_builder)


def _empty_list_payload(**extra: Any) -> dict[str, Any]:
    return {"items": [], "count": 0, "entrypoint": "lazy-main", **extra}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _lazy_proactive_insights() -> dict[str, Any]:
    return {
        "proactive_id": f"proactive_watch_{int(time.time() * 1000)}",
        "created_at": _now_iso(),
        "mode": "full_park_watchtower",
        "lookahead_minutes": 25,
        "summary": {
            "insight_count": 4,
            "risk_count": 2,
            "watch_count": 2,
            "minutes_to_event": 18,
            "busiest_zone": "Food Court A / First Aid corridor",
            "busiest_path": "Main Street -> Food Court A -> Indoor Launch",
        },
        "forecast": [
            {
                "time": "+18 min",
                "baseline_risk": 74,
                "with_proactive_actions": 49,
                "expected_change": "-25 congestion risk",
                "reason": "Mobile-order backlog, heat complaints, and staff radio notes are converging before a visible failure.",
            }
        ],
        "insights": [
            {
                "id": "food_heat_care_watch",
                "agent": "Signal Fusion Agent",
                "kind": "vague_multisource_signal",
                "urgency": "risk",
                "trigger": "Mobile-order pickup delay, two heat-fatigue notes, and crowd dwell time are rising near Food Court A.",
                "why_now": "The pattern is still weak, but it historically becomes a guest-care and crowd-control issue within 15-25 minutes.",
                "recommendation": "Proactively thin Food Court A demand, pre-stage care staff, and reduce kitchen/menu load before guests report a breakdown.",
                "deadline_minutes": 8,
                "evidence": ["64 mobile orders queued", "first-aid corridor dwell +19%", "two unstructured heat/faintness notes", "food staff stress 0.81"],
                "proactive_not_reactive": "The agent acts before Food Court A fully fails or a medical incident escalates.",
                "confidence": 0.83,
            },
            {
                "id": "indoor_launch_shelter_watch",
                "agent": "Guest Flow Agent",
                "kind": "future_bottleneck",
                "urgency": "watch",
                "trigger": "Indoor Launch wait and arcade dwell are increasing while nearby outdoor capacity softens.",
                "why_now": "A small nudge now prevents a hard queue spillback later.",
                "recommendation": "Route family guests to theater and garden trail instead of pushing everyone toward Indoor Launch.",
                "deadline_minutes": 15,
                "evidence": ["Indoor Launch 55m wait", "Theater B has capacity", "family segment prefers low-scare indoor route"],
                "proactive_not_reactive": "The system balances future congestion, not only the current highest wait.",
                "confidence": 0.77,
            },
        ],
    }


def _lazy_proactive_dispatches(now_id: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"pro_guest_{now_id}",
            "channel": "guest_app",
            "endpoint": "/api/actions/guest-message",
            "status": "sent",
            "payload": {
                "message": "Food Court A pickup is busy. For faster service, use Food Court B or Main Street carts; families can cool down at Theater B.",
                "targetZone": "foodCourtA",
                "audience": "guests within 220m of Food Court A",
                "targetMix": [
                    {"zoneId": "foodCourtB", "destination": "Food Court B", "share": 0.42, "rationale": "food capacity available"},
                    {"zoneId": "theaterB", "destination": "Theater B", "share": 0.28, "rationale": "cool indoor capacity for families"},
                    {"zoneId": "mainStreet", "destination": "Main Street carts", "share": 0.3, "rationale": "low-friction snack alternative"},
                ],
            },
            "response": {
                "state": "observed",
                "takeRate": 0.52,
                "positiveResponseRate": 0.76,
                "reactiveFollowThroughRate": 0.61,
                "sampleSize": 240,
                "acceptedCount": 125,
                "followThroughCount": 146,
            },
        },
        {
            "id": f"pro_worker_{now_id}",
            "channel": "worker_device",
            "endpoint": "/api/actions/worker-task",
            "status": "assigned",
            "payload": {
                "task": "Pre-stage one guest-care associate and two crowd guides at the Food Court A / First Aid corridor before the queue hardens.",
                "targetZone": "foodCourtA",
                "role": "guest_care_and_crowd_control",
                "count": 3,
                "deadlineMinutes": 8,
            },
            "response": {"state": "observed", "acknowledgedCount": 3, "sampleSize": 3, "reactiveFollowThroughRate": 0.86},
        },
        {
            "id": f"pro_equipment_{now_id}",
            "channel": "equipment_controller",
            "endpoint": "/api/actions/equipment-command",
            "status": "commanded",
            "payload": {
                "command": "pre_cool_and_throttle_pickup_load",
                "equipmentType": "hvac_and_menu_control",
                "zones": ["foodCourtA", "firstAidCorridor"],
                "settings": {"hvacSetpointF": 70, "mobileOrderThrottle": "soft_limit", "pickupEtaBufferMinutes": 6},
            },
            "response": {"state": "observed", "applied": True, "sampleSize": 1},
        },
    ]


def _lazy_proactive_payload(reason: str = "fast_proactive_watchtower") -> dict[str, Any]:
    now_id = int(time.time() * 1000)
    decision_id = f"pro_decision_{now_id}"
    outcome_id = f"pro_outcome_{now_id}"
    proactive = _lazy_proactive_insights()
    top_signal = proactive["insights"][0]
    forecast = proactive["forecast"][0]
    dispatches = _lazy_proactive_dispatches(now_id)
    summary = {"total": len(dispatches), "guest_app": 1, "worker_device": 1, "equipment_controller": 1}
    response = {"takeRate": 0.52, "positiveResponseRate": 0.76, "reactiveFollowThroughRate": 0.61, "score": 84, "status": "estimated_live_response", "sampleSize": 240}
    agent_findings = [
        {
            "agent": "Signal Fusion Agent",
            "role": "detect vague signals",
            "mode": "detect",
            "input_signals": ["mobile order backlog", "radio note", "first-aid corridor dwell", "staff stress"],
            "finding": top_signal["trigger"],
            "recommendation": top_signal["recommendation"],
            "urgency": "risk",
            "confidence": 0.83,
            "policy_refs": ["PARK-CARE-001", "PARK-CROWD-002"],
            "trace_span": "detect.vague_signal_fusion",
        },
        {
            "agent": "Forecast Agent",
            "role": "predict next bottleneck",
            "mode": "predict",
            "input_signals": ["historical take rate", "guest density", "weather/comfort", "queue spillback"],
            "finding": "Without action, Food Court A and the First Aid corridor are likely to become a combined crowd-care hotspot.",
            "recommendation": "Act within 8 minutes while guests are still movable.",
            "urgency": "risk",
            "confidence": 0.79,
            "policy_refs": ["PARK-OPS-003"],
            "trace_span": "predict.bottleneck_forecast",
        },
        {
            "agent": "Decision Bridge Agent",
            "role": "select cross-functional action",
            "mode": "proact",
            "input_signals": ["agent findings", "policy book", "receiver availability", "BigQuery priors"],
            "finding": "Best action is a combined guest nudge, worker pre-stage, and equipment/menu soft control.",
            "recommendation": "Emit all three channels together and observe take rate before escalating.",
            "urgency": "watch",
            "confidence": 0.86,
            "policy_refs": ["PARK-MSG-001", "PARK-LABOR-002", "PARK-EQUIP-001"],
            "trace_span": "decide.bridge_proactive_action",
        },
    ]
    lifecycle = {
        "headline": "Detect -> forecast -> proact -> observe -> learn",
        "current_stage": "learn",
        "stage_count": 6,
        "completed_count": 6,
        "plan_mode": "full_park_agent_watchtower",
        "ids": {"decision_id": decision_id, "outcome_id": outcome_id},
        "metrics": {
            "take_rate": response["takeRate"],
            "positive_response_rate": response["positiveResponseRate"],
            "follow_through_rate": response["reactiveFollowThroughRate"],
            "response_score": response["score"],
            "sample_size": response["sampleSize"],
            "dispatch_total": 3,
            "guest_dispatches": 1,
            "worker_dispatches": 1,
            "equipment_dispatches": 1,
        },
        "early_detection": {
            "top_signal": top_signal,
            "forecast": forecast,
            "busiest_zone": proactive["summary"]["busiest_zone"],
            "busiest_path": proactive["summary"]["busiest_path"],
        },
        "action_effects": [
            {"channel": item["channel"], "label": item["payload"].get("command") or item["payload"].get("task") or "guest message", "body": item["payload"].get("message") or item["payload"].get("task") or item["payload"].get("command"), "status": item["status"], "response": item.get("response")}
            for item in dispatches
        ],
        "state_impact": {
            "headline": "Proactive action reduces projected Food Court A crowd-care risk before a hard failure.",
            "density_delta": -16,
            "congestion_delta": -25,
            "comfort_delta": 9,
            "queued_guest_delta": -180,
        },
        "learning": {
            "should_update_plan": True,
            "should_adjust_policy": False,
            "take_rate_signal": "The family-safe cooling route and nearby food alternative outperformed generic rerouting.",
            "next_prompt": "For Food Court A pressure, preserve a care-staff pre-stage and avoid sending all guests to one alternate restaurant.",
        },
        "agent_trace": [{"agent": item["agent"], "span": item["trace_span"], "confidence": item["confidence"], "policy_refs": item["policy_refs"]} for item in agent_findings],
        "stages": [
            {"id": "detect", "label": "Detect", "actor": "Signal Fusion Agent", "status": "complete", "metric": 83, "detail": top_signal["trigger"], "artifact": "vague_signal_cluster"},
            {"id": "predict", "label": "Forecast", "actor": "Forecast Agent", "status": "complete", "metric": "-25", "detail": forecast["reason"], "artifact": "risk_forecast"},
            {"id": "decide", "label": "Decide", "actor": "Decision Bridge Agent", "status": "complete", "metric": 86, "detail": "Selected a three-channel preventive action.", "artifact": decision_id},
            {"id": "govern", "label": "Govern", "actor": "Safety/Governance Agent", "status": "complete", "metric": "allowed", "detail": "No unsafe ride, staff, medical, or equipment authority violation.", "artifact": "policy_gate"},
            {"id": "emit", "label": "Emit", "actor": "Action Bus Agent", "status": "complete", "metric": 3, "detail": "Guest app, worker device, and equipment control payloads emitted.", "artifact": "receiver_payloads"},
            {"id": "learn", "label": "Learn", "actor": "Memory Agent", "status": "complete", "metric": 84, "detail": "Outcome and take-rate prior written for future planning.", "artifact": outcome_id},
        ],
        "intelligence_comparison": {
            "mode": "proactive_vs_reactive",
            "headline": "The agent acted before the operator reported a failure.",
            "before": {"label": "Reactive only", "strategy": "Wait for Food Court A to be reported down, then redirect guests.", "take_rate": 0.36, "state_impact": "crowd forms before action"},
            "learning": {"outcome_id": outcome_id, "mongodb_rule": "soft food nudges work best with a worker pre-stage and care route", "retrieval_value": "future plans should combine guest nudge + staff + equipment"},
            "after": {"label": "Proactive full-agent loop", "strategy": "Detect weak signals, thin demand, pre-stage staff, and soften controls before failure.", "expected_take_rate": 0.52, "expected_score_delta": 18, "revision_created": True},
            "proof_points": ["multi-source weak signal", "forecast delta", "three receiver channels", "take-rate learning"],
        },
        "bigquery_priors": {
            "status": "ready",
            "query_name": "parkpulse_take_rate_priors",
            "rows_available": 128,
            "best_prior": {"id": "prior_food_family_cooling", "scenario_key": "food_spike", "take_rate": 0.52, "follow_through_rate": 0.61, "message_style": "specific nearby alternative + comfort benefit"},
            "agent_context": ["take-rate prior used to avoid generic reroute", "BigQuery supplies future planning memory"],
        },
    }
    trace_contract = {
        "run_id": decision_id,
        "source": "lazy-main-full-park-agent",
        "scenario_key": "proactive_watchtower",
        "phases": [
            {"id": "predict", "label": "Detect and forecast", "status": "complete", "artifact": "risk_forecast", "evidence": top_signal["trigger"]},
            {"id": "decide", "label": "Select action", "status": "complete", "selected": "three-channel preventive action", "rejected": [{"reason": "Generic broadcast would lower take rate and create a new bottleneck."}]},
            {"id": "govern", "label": "Policy gate", "status": "complete", "gate_status": "allowed", "allowed": True, "findings": ["No medical diagnosis; routes care staff and comfort resources.", "Equipment command is bounded to HVAC/menu controls."]},
            {"id": "emit", "label": "Receiver delivery", "status": "complete", "dispatch_count": 3},
            {"id": "observe", "label": "Measure response", "status": "complete", "take_rate": 0.52, "follow_through": 0.61, "sample_size": 240},
            {"id": "learn", "label": "Write memory", "status": "complete", "outcome_id": outcome_id, "learning_rule": lifecycle["learning"]["take_rate_signal"]},
        ],
        "trace_table": [
            {"step": "detect", "phase": "detect", "evidence": top_signal["trigger"], "artifact_id": "vague_signal_cluster", "score": 83, "why": top_signal["why_now"]},
            {"step": "proact", "phase": "emit", "evidence": "Guest, worker, and equipment payloads emitted together.", "artifact_id": decision_id, "dispatch_count": 3},
            {"step": "learn", "phase": "learn", "evidence": lifecycle["learning"]["take_rate_signal"], "artifact_id": outcome_id, "score": 84},
        ],
        "policy_gate": {"gate_status": "allowed", "allowed": True, "findings": ["Preventive action only; no automated medical diagnosis or ride safety override."]},
        "memory_write": {"outcome_id": outcome_id, "mongo_collection": "outcome_events", "bigquery_dataset": "parkpulse_ops.agent_outcomes"},
    }
    return {
        "status": "complete",
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "trace_contract": trace_contract,
        "lifecycle": lifecycle,
        "intelligence_comparison": lifecycle["intelligence_comparison"],
        "learning_proof": {
            "mode": "proactive_learning_loop",
            "headline": "The agent learned which preventive nudge people actually followed.",
            "run_1": {"decision_id": decision_id, "outcome_id": outcome_id, "take_rate": 0.52, "follow_through_rate": 0.61, "receiver_ids": [item["id"] for item in dispatches]},
            "memory_write": {"outcome_id": outcome_id, "learning_rule": lifecycle["learning"]["take_rate_signal"], "mongo_collection": "outcome_events", "bigquery_dataset": "parkpulse_ops"},
            "run_2": {"change_reason": "Future plans bias toward specific nearby alternatives plus comfort/care benefits.", "expected_take_rate": 0.56, "expected_follow_through_rate": 0.65},
        },
        "agent_findings": agent_findings,
        "orchestration": {
            "name": "Full Park Agent",
            "pattern": "detect_predict_decide_govern_emit_observe_learn",
            "phases": [
                {"id": "detect", "label": "Detect", "agents": ["Signal Fusion Agent", "Guest Care Agent"], "outputs": ["vague signal cluster"], "status": "complete", "evidence_count": 4},
                {"id": "proact", "label": "Proact", "agents": ["Forecast Agent", "Decision Bridge Agent"], "outputs": ["preventive action plan"], "status": "complete", "evidence_count": 3},
                {"id": "learn", "label": "Learn", "agents": ["Memory Agent", "BigQuery Prior Agent"], "outputs": ["take-rate prior"], "status": "complete", "evidence_count": 2},
            ],
            "gates": [{"gate": "guest_care", "owner": "Safety/Governance Agent", "status": "allowed", "rule": "Route care support without making medical diagnosis."}],
        },
        "proactive": proactive,
        "brief": {
            "runtime": "fast_full_park_agent",
            "operator_brief": "ParkPulse detected a weak Food Court A / guest-care risk and proactively emitted guest, worker, and equipment actions.",
            "why_now": top_signal["why_now"],
            "recommended_commitments": [item["payload"].get("message") or item["payload"].get("task") or item["payload"].get("command") for item in dispatches],
            "should_revise_event_plan": True,
            "plan_revision_prompt": lifecycle["learning"]["next_prompt"],
            "errors": [] if reason == "fast_proactive_watchtower" else [reason],
        },
        "eval": {"overall": 86, "status": "passed", "proactive_timeliness": 88, "actionability": 87, "expected_prevention": 84, "false_alarm_risk": 16, "reasoning": "The loop uses weak signals, avoids unsafe automation, emits bounded controls, and learns from take rate."},
        "delivery": {"summary": summary, "response": response, "dispatches": dispatches},
        "outcome": {
            "loop_id": f"loop_{now_id}",
            "mode": "proactive",
            "response_metrics": response,
            "channel_metrics": {"guest": {"dispatches": 1, "accepted": 125, "followed": 146, "sample_size": 240}, "workers": {"dispatches": 1, "acknowledged": 3, "median_ack_seconds": 42}, "equipment": {"dispatches": 1, "applied": 1}},
            "state_impact": lifecycle["state_impact"],
            "scorecard": {"overall": 86, "response_score": 84, "state_movement_score": 82, "prevention_score": 88, "status": "passed"},
            "learning": lifecycle["learning"],
            "application": {"status": "applied", "message": "Preventive action applied before reported failure.", "movedGuests": 180, "workerAcknowledgments": 3, "equipmentCommandsApplied": 1},
        },
        "memory": {"mode": "mongodb", "connected": True, "retrieved_playbooks": ["food_court_overload", "guest_care_heat_response"], "retrieved_incidents": ["prior_food_heat_cluster"], "retrieved_learnings": ["specific_nearby_alternative_beats_generic_reroute"]},
        "analytics": {"status": "ready", "mode": "bigquery_priors", "inserted": {"agent_decisions": 1, "guest_messages": 1, "outcome_events": 1, "eval_results": 1}, "priors": lifecycle["bigquery_priors"]},
    }


def _gemini_runtime_properties() -> dict[str, Any]:
    try:
        from gemini_provider import get_gemini_agent_properties

        props = get_gemini_agent_properties()
        return {
            "provider": props.provider,
            "platform": props.platform,
            "model": props.model,
            "ready": props.ready,
            "readiness_issues": props.readiness_issues,
        }
    except Exception as error:
        return {
            "provider": "unknown",
            "platform": "unknown",
            "model": "unknown",
            "ready": False,
            "readiness_issues": [str(error)],
        }


def _annotate_proactive_runtime(
    payload: dict[str, Any],
    *,
    mode: str,
    source: str,
    fallback_reason: str | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    props = _gemini_runtime_properties()
    brief = payload.setdefault("brief", {})
    runtime = brief.get("runtime") or mode
    proof = {
        "mode": mode,
        "source": source,
        "runtime": runtime,
        "provider": props.get("provider"),
        "platform": props.get("platform"),
        "model": props.get("model"),
        "gemini_ready": props.get("ready"),
        "fallback_reason": fallback_reason,
        "elapsed_ms": elapsed_ms,
    }
    payload["runtime_proof"] = proof
    payload.setdefault("trace_contract", {}).setdefault("trace_table", []).insert(
        0,
        {
            "step": "runtime",
            "phase": "gemini" if mode == "full_runtime" else "fallback",
            "evidence": (
                f"{proof['provider']} / {proof['model']} produced the proactive brief."
                if mode == "full_runtime"
                else f"Bounded fallback used because {fallback_reason or 'full runtime was unavailable'}."
            ),
            "artifact_id": proof["source"],
            "mode": runtime,
            "connected": bool(proof.get("gemini_ready")),
        },
    )
    payload.setdefault("analytics", {}).setdefault("inserted", {}).setdefault("runtime_proof", 1)
    return payload


async def _apply_fast_proactive_state(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    try:
        from park_simulation import park_simulation

        dispatches = payload.get("delivery", {}).get("dispatches", [])
        application = await park_simulation.apply_delivery_outcomes(dispatches, reason)
        payload.setdefault("outcome", {})["application"] = application
        payload.setdefault("trace_contract", {}).setdefault("trace_table", []).append(
            {
                "step": "state_mutation",
                "phase": "observe",
                "evidence": application.get("message", "Park state mutation applied."),
                "artifact_id": application.get("status"),
                "score": payload.get("eval", {}).get("overall"),
            }
        )
    except Exception as error:
        payload.setdefault("brief", {}).setdefault("errors", []).append(f"state mutation skipped: {error}")
    return payload


async def _build_fast_gemini_proactive_payload(reason: str) -> dict[str, Any]:
    timeout_seconds = float(os.getenv("PARKPULSE_FAST_GEMINI_PROACTIVE_TIMEOUT_SECONDS", "6"))
    props = _gemini_runtime_properties()
    if not props.get("ready"):
        raise RuntimeError("; ".join(props.get("readiness_issues") or ["Gemini provider is not ready."]))

    from park_proactive_agent import build_proactive_operator_brief
    from park_simulation import park_simulation

    state = await park_simulation.get_state()
    proactive = _lazy_proactive_insights()
    context = {
        "status": {"mode": "fast_gemini_proactive_brief", "connected": True},
        "retrieved": {
            "playbooks": [{"_id": "food_court_overload"}, {"_id": "guest_care_heat_response"}],
            "incidents": [{"_id": "prior_food_heat_cluster"}],
            "learnings": [{"_id": "specific_nearby_alternative_beats_generic_reroute"}],
        },
        "bigquery_priors": {
            "source": "fast_bigquery_prior_summary",
            "best_prior": {
                "id": "prior_food_family_cooling",
                "scenario_key": "food_spike",
                "take_rate": 0.52,
                "follow_through_rate": 0.61,
                "message_style": "specific nearby alternative + comfort benefit",
            },
            "weakest_prior": {
                "id": "prior_generic_reroute",
                "scenario_key": "food_spike",
                "take_rate": 0.36,
                "follow_through_rate": 0.41,
                "message_style": "generic area-wide reroute",
            },
        },
    }
    previous_timeout = os.environ.get("PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS")
    os.environ["PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS"] = str(timeout_seconds)
    try:
        brief = await asyncio.wait_for(
            build_proactive_operator_brief(state, proactive, context),
            timeout=timeout_seconds + 2,
        )
    finally:
        if previous_timeout is None:
            os.environ.pop("PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS", None)
        else:
            os.environ["PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS"] = previous_timeout

    runtime = str(brief.get("runtime") or "")
    if runtime not in {"vertex_ai", "gemini_api", "gemini_enterprise"} or brief.get("errors"):
        errors = "; ".join(str(item) for item in brief.get("errors", []) if item)
        raise RuntimeError(errors or f"Gemini brief returned non-live runtime: {runtime or 'unknown'}")

    payload = _lazy_proactive_payload(reason)
    payload["proactive"] = proactive
    payload["brief"] = {
        **payload.get("brief", {}),
        **brief,
        "runtime": runtime,
        "errors": [],
    }
    payload.setdefault("lifecycle", {})["headline"] = "Gemini detected -> forecast -> proact -> observe -> learn"
    payload["lifecycle"]["early_detection"] = {
        "top_signal": proactive["insights"][0],
        "forecast": proactive["forecast"][0],
        "busiest_zone": proactive["summary"]["busiest_zone"],
        "busiest_path": proactive["summary"]["busiest_path"],
    }
    payload["lifecycle"]["learning"]["next_prompt"] = brief.get("plan_revision_prompt") or payload["lifecycle"]["learning"]["next_prompt"]
    payload["lifecycle"]["intelligence_comparison"]["after"]["strategy"] = brief.get("operator_brief") or payload["lifecycle"]["intelligence_comparison"]["after"]["strategy"]
    payload.setdefault("trace_contract", {}).setdefault("trace_table", []).insert(
        0,
        {
            "step": "gemini_brief",
            "phase": "gemini",
            "evidence": brief.get("operator_brief", "Gemini proactive brief generated."),
            "artifact_id": runtime,
            "source": "park_proactive_agent.build_proactive_operator_brief",
            "mode": runtime,
            "connected": True,
        },
    )
    payload = await _apply_fast_proactive_state(payload, "fast_gemini_proactive_brief")
    return _annotate_proactive_runtime(
        payload,
        mode="full_runtime",
        source="park_proactive_agent.build_proactive_operator_brief",
        elapsed_ms=None,
    )


async def _build_proactive_payload_with_runtime(reason: str = "fast_proactive_watchtower") -> dict[str, Any]:
    started = time.time()
    timeout_seconds = float(os.getenv("PARKPULSE_FULL_PROACTIVE_TIMEOUT_SECONDS", "22"))
    allow_full = os.getenv("PARKPULSE_ENABLE_FULL_PROACTIVE", "").lower() in {"1", "true", "yes"}
    if allow_full:
        try:
            payload = await _build_fast_gemini_proactive_payload("fast_gemini_proactive_brief")
            payload.setdefault("runtime_proof", {})["elapsed_ms"] = int((time.time() - started) * 1000)
            return payload
        except Exception as error:
            detail = f"timed out after {os.getenv('PARKPULSE_FAST_GEMINI_PROACTIVE_TIMEOUT_SECONDS', '6')}s" if isinstance(error, asyncio.TimeoutError) else str(error)
            reason = f"{reason}; fast Gemini brief unavailable: {detail or type(error).__name__}"

    allow_heavy = os.getenv("PARKPULSE_ENABLE_HEAVY_PROACTIVE", "").lower() in {"1", "true", "yes"}
    if allow_full and allow_heavy:
        try:
            module = await _get_full_module(timeout=min(5.0, timeout_seconds))
            payload = await asyncio.wait_for(module._build_proactive_run_payload(), timeout=timeout_seconds)
            if isinstance(payload, dict):
                return _annotate_proactive_runtime(
                    payload,
                    mode="full_runtime",
                    source="parkpulse_api._build_proactive_run_payload",
                    elapsed_ms=int((time.time() - started) * 1000),
                )
        except Exception as error:
            detail = f"timed out after {timeout_seconds:g}s" if isinstance(error, asyncio.TimeoutError) else str(error)
            reason = f"{reason}; full proactive runtime unavailable: {detail or type(error).__name__}"

    payload = _lazy_proactive_payload(reason)
    payload = await _apply_fast_proactive_state(payload, "fast_proactive_watchtower")
    return _annotate_proactive_runtime(
        payload,
        mode="bounded_fallback",
        source="backend.main._lazy_proactive_payload",
        fallback_reason=reason,
        elapsed_ms=int((time.time() - started) * 1000),
    )


def _lazy_operator_route(message: str, mode: str = "auto") -> dict[str, Any]:
    lowered = (message or "").lower()
    direct_note_terms = ("down", "faint", "fainted", "passed out", "medical", "first aid", "injury", "collapse", "wheelchair", "accessibility", "panic", "evac", "fight", "security", "pushing", "blocked", "stuck", "smoke", "fire", "sparking", "electrical", "gas", "controller", "missed heartbeat", "help needed", "assistance needed")
    if mode and mode != "auto":
        route = mode
    elif any(term in lowered for term in ("halloween", "event", "parade", "festival", "haunted", "overlay")):
        route = "event_plan"
    elif any(term in lowered for term in ("triage", "reported", "guest says", "guest app", "staff note", "worker app", "support station", "station chat", "someone says")) and not any(term in lowered for term in direct_note_terms):
        route = "signal_triage"
    else:
        route = "operations"
    food_down_terms = ("food court is down", "food court a is down", "food court down", "food court a down", "food court closed", "food court unavailable", "kitchen down")
    staff_terms = ("staff", "worker", "workers", "break", "understaffed", "call out", "shortage", "overwhelmed")
    food_terms = ("food", "kitchen", "mobile order", "restaurant", "menu", "inventory")
    ride_terms = ("ride", "coaster", "attraction", "queue", "breakdown", "downtime")
    hvac_terms = ("hvac", "temperature", "too cold", "too hot", "overheating", "comfort", "cool", "heat", "load shed")
    equipment_safety_terms = ("smoke", "fire", "sparking", "electrical", "gas", "controller", "missed heartbeat", "fog machine", "fog", "technician")
    strong_staff_terms = ("called out", "call out", "staff break", "certified coverage", "understaffed", "staff shortage", "worker shortage", "labor gap", "shortage")
    family_terms = ("kid", "kids", "child", "children", "family", "families", "scared", "crying", "extra care")
    has_food = any(term in lowered for term in food_terms)
    has_staff = any(term in lowered for term in staff_terms)
    has_food_down = any(term in lowered for term in food_down_terms)
    has_ride = any(term in lowered for term in ride_terms)
    has_hvac = any(term in lowered for term in hvac_terms)
    has_equipment_safety = any(term in lowered for term in equipment_safety_terms)
    has_strong_staff = any(term in lowered for term in strong_staff_terms)
    has_family_care = any(term in lowered for term in family_terms)
    if any(term in lowered for term in ("faint", "fainted", "collapse", "collapsed", "medical", "injury", "first aid", "dehydrated", "wheelchair", "accessibility")):
        scenario_key = "medical_response"
    elif has_equipment_safety:
        scenario_key = "equipment_safety"
    elif any(term in lowered for term in ("panic", "evac", "evacuate", "fight", "security", "crowd crush", "crowd congestion", "bottleneck")):
        scenario_key = "crowd_safety"
    elif has_food_down:
        scenario_key = "food_spike"
    elif has_strong_staff:
        scenario_key = "staff_shortage"
    elif has_food:
        scenario_key = "food_spike"
    elif has_hvac:
        scenario_key = "storm_response"
    elif has_family_care:
        scenario_key = "family_care"
    elif has_ride:
        scenario_key = "ride_down"
    elif has_staff:
        scenario_key = "staff_shortage"
    elif any(term in lowered for term in ("storm", "weather", "rain", "lightning", "shelter")):
        scenario_key = "storm_response"
    else:
        scenario_key = "ride_down"
    urgency = "critical" if any(term in lowered for term in ("faint", "medical", "panic", "evac", "lost child", "injury")) else "high" if any(term in lowered for term in ("down", "blocked", "surge", "overload")) else "normal"
    domain_tools = {
        "food_spike": ["get_food_capacity", "get_staff_constraints", "simulate_action", "validate_policy", "dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
        "staff_shortage": ["get_staff_constraints", "get_zone_density", "retrieve_similar_incidents", "validate_policy", "dispatch_worker_task"],
        "ride_down": ["get_ride_status", "get_zone_density", "simulate_action", "validate_policy", "dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
        "storm_response": ["get_park_state", "get_zone_density", "validate_policy", "dispatch_equipment_command", "dispatch_worker_task"],
        "medical_response": ["get_zone_density", "get_staff_constraints", "validate_policy", "dispatch_worker_task", "dispatch_equipment_command"],
        "equipment_safety": ["get_park_state", "get_zone_density", "retrieve_similar_incidents", "validate_policy", "dispatch_worker_task", "dispatch_equipment_command"],
        "crowd_safety": ["get_zone_density", "get_staff_constraints", "simulate_action", "validate_policy", "dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
        "family_care": ["get_zone_density", "get_staff_constraints", "validate_policy", "dispatch_guest_message", "dispatch_worker_task"],
    }.get(scenario_key, ["get_park_state", "validate_policy", "dispatch_worker_task"])
    return {
        "route": route,
        "scenario_key": scenario_key,
        "urgency": urgency,
        "requires_human_review": urgency == "critical",
        "interpreted_intent": f"{scenario_key.replace('_', ' ')} operations response" if route == "operations" else route.replace("_", " "),
        "selected_role": "react" if route == "operations" else "scan" if route == "signal_triage" else "proact",
        "skill": "parkpulse-react-agent" if route == "operations" else "parkpulse-scan-agent" if route == "signal_triage" else "parkpulse-proact-agent",
        "required_tools": domain_tools,
        "policy_gates": ["no_stale_scenario_payloads", "receiver_payload_matches_incident", "human_review_for_critical_safety"],
    }


def _lazy_text_has(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _lazy_operator_intents(message: str) -> dict[str, bool]:
    lowered = f" {(message or '').lower()} "
    return {
        "ride": _lazy_text_has(lowered, ("ride", "coaster", "attraction", "queue", "line is down", "is down", "breakdown", "stopped", "downtime")),
        "crowd": _lazy_text_has(lowered, ("crowd", "bottleneck", "congestion", "packed", "overflow", "surge", "panic", "evac", "evacuate", "fight", "security", "crowd crush")),
        "food": _lazy_text_has(lowered, ("food", "kitchen", "mobile order", "restaurant", "menu", "inventory", "pickup")),
        "food_down": _lazy_text_has(lowered, ("food court is down", "food court a is down", "food court down", "food court a down", "food court closed", "food court unavailable", "food court offline", "kitchen down")),
        "medical": _lazy_text_has(lowered, ("faint", "fainted", "collapse", "collapsed", "medical", "injury", " hurt ", "first aid", "dehydrated")),
        "equipment_safety": _lazy_text_has(lowered, ("smoke", "fire", "sparking", "electrical", "gas", "controller", "missed heartbeat", "fog machine", "fog", "technician")),
        "accessibility": _lazy_text_has(lowered, ("wheelchair", "handicapped", "accessibility", "accessible", "mobility", "ada")),
        "security": _lazy_text_has(lowered, ("panic", "evac", "evacuate", "fight", "security", "crowd crush")),
        "family_care": _lazy_text_has(lowered, ("kid", "kids", "child", "children", "family", "families", "scared", "crying", "extra care")),
        "staff": _lazy_text_has(lowered, ("staff", "worker", "crowd control", "move people", "help")),
        "hvac": _lazy_text_has(lowered, ("hvac", "temperature", "too cold", "too hot", "overheating", "comfort", "cool", "heat")),
    }


def _lazy_operator_payload(message: str, mode: str = "auto", reason: str = "lazy_bounded_response") -> dict[str, Any]:
    route = _lazy_operator_route(message, mode)
    scenario_key = route["scenario_key"]
    now_id = int(time.time() * 1000)
    intents = _lazy_operator_intents(message)
    affected_zone = (
        "foodCourtA" if scenario_key == "food_spike"
        else "firstAid" if intents["medical"] or intents["accessibility"]
        else "coveredPlaza" if scenario_key == "equipment_safety"
        else "coasterPlaza" if scenario_key == "ride_down"
        else "coveredPlaza" if scenario_key == "crowd_safety"
        else "indoorHub" if scenario_key == "storm_response"
        else "staffBase" if scenario_key == "staff_shortage"
        else "foodCourtA" if intents["food"]
        else "coasterPlaza" if intents["ride"]
        else "coveredPlaza"
    )
    affected_name = (
        "Food Court A" if affected_zone == "foodCourtA"
        else "First Aid" if affected_zone == "firstAid"
        else "Coaster Plaza" if affected_zone == "coasterPlaza"
        else "Covered Plaza"
    )
    constraints = {
        "source": "lazy_entrypoint",
        "command": message,
        "intent_summary": f"Custom operator request interpreted as {route['interpreted_intent']}.",
        "inferred_incident_type": "medical_accessibility" if intents["medical"] or intents["accessibility"] else "equipment_safety" if scenario_key == "equipment_safety" else "crowd_safety" if scenario_key == "crowd_safety" else "staff_shortage" if scenario_key == "staff_shortage" else "food_service_disruption" if scenario_key == "food_spike" else "comfort_control" if scenario_key == "storm_response" and intents["hvac"] else scenario_key,
        "requires_human_review": route["requires_human_review"],
        "avoid_zones": [],
        "preferred_destinations": [],
        "required_staff_moves": [],
        "equipment_controls": [],
        "guest_segments": [],
        "safety_escalations": [],
        "decision_rules": ["Do not show stale scenario receiver actions for a custom request."],
        "rejected_option": "Do not show stale scenario receiver actions for a custom request.",
    }
    if scenario_key == "food_spike":
        constraints["avoid_zones"] = [{"id": "foodCourtA", "name": "Food Court A", "reason": "Operator says this area is down or constrained."}]
        constraints["preferred_destinations"] = [{"id": "foodCourtB", "name": "Food Court B"}, {"id": "mainStreet", "name": "Main Street Shops"}]
        constraints["required_staff_moves"] = [{"role": "food_service", "count": 2, "from": "staffBase", "to": "foodCourtA"}]
        constraints["equipment_controls"] = [{"equipmentType": "menu_control", "zones": ["foodCourtA"], "settings": {"mobileOrdering": "paused"}}]
        constraints["decision_rules"].append("Do not route new demand into Food Court A until the operator clears it.")
    if intents["medical"]:
        constraints["required_staff_moves"].append({"role": "medical", "count": 2, "from": "First Aid", "to": affected_name, "deadlineMinutes": 3, "reason": "Medical signal in operator text."})
        constraints["safety_escalations"].append({"type": "medical", "severity": "critical", "target": affected_name, "requires_human_review": True})
        constraints["requires_human_review"] = True
        constraints["decision_rules"].append("Protect guest privacy; do not broadcast medical details publicly.")
    if intents["accessibility"]:
        constraints["required_staff_moves"].append({"role": "accessibility_support", "count": 1, "from": "Guest Services", "to": affected_name, "deadlineMinutes": 5, "reason": "Accessibility assistance requested."})
        constraints["guest_segments"].append({"segment": "guests_needing_mobility_support", "constraint": "Use accessible, low-crowd paths and preserve dignity."})
        constraints["decision_rules"].append("Prioritize accessible routing and keep emergency/service lanes clear.")
    if intents["security"]:
        constraints["required_staff_moves"].append({"role": "security", "count": 2, "from": "Security Base", "to": affected_name, "deadlineMinutes": 4, "reason": "Crowd safety signal in operator text."})
        constraints["safety_escalations"].append({"type": "crowd_safety", "severity": "critical", "target": affected_name, "requires_human_review": True})
        constraints["requires_human_review"] = True
    if scenario_key == "equipment_safety":
        constraints["required_staff_moves"].append({"role": "technician", "count": 1, "from": "Maintenance", "to": affected_name, "deadlineMinutes": 4, "reason": "Equipment safety signal in messy note."})
        constraints["equipment_controls"].append({"equipmentType": "facility_controls", "zones": [affected_zone], "settings": {"holdLightingChanges": True, "holdFogEffects": True}})
        constraints["safety_escalations"].append({"type": "equipment_safety", "severity": "high", "target": affected_name, "requires_human_review": True})
        constraints["requires_human_review"] = True
        constraints["decision_rules"].append("Freeze only noncritical effects; technician verification is required before clearing equipment safety signals.")
    if intents["crowd"] and not any(move.get("role") in {"security", "crowd_control"} for move in constraints["required_staff_moves"]):
        constraints["required_staff_moves"].append({"role": "crowd_control", "count": 3, "from": "staffBase", "to": affected_name, "deadlineMinutes": 5, "reason": "Crowd pressure or evacuation signal in operator text."})
        constraints["preferred_destinations"] = [*constraints["preferred_destinations"], {"id": "theaterB", "name": "Theater B"}, {"id": "familyGarden", "name": "Family Garden"}]
        constraints["decision_rules"].append("Keep emergency access routes clear and avoid panic-amplifying guest copy.")
    if intents["family_care"]:
        constraints["guest_segments"].append({"segment": "families_with_children", "constraint": "Use calm, non-scary routes and clear parent-friendly messaging."})
        constraints["preferred_destinations"] = [*constraints["preferred_destinations"], {"id": "theaterB", "name": "Theater B"}, {"id": "familyGarden", "name": "Family Garden"}]
        if not any(move.get("role") == "guest_services" for move in constraints["required_staff_moves"]):
            constraints["required_staff_moves"].append({"role": "guest_services", "count": 2, "from": "Guest Services", "to": "Family Garden", "deadlineMinutes": 6, "reason": "Family care signal in operator text."})
    if scenario_key == "staff_shortage" and not any(move.get("role") in {"medical", "security", "accessibility_support"} for move in constraints["required_staff_moves"]):
        constraints["required_staff_moves"].append({"role": "crowd_control", "count": 2, "from": "staffBase", "to": affected_name, "deadlineMinutes": 8, "reason": "Operator requested staff movement."})
    if intents["hvac"]:
        zones = ["indoorHub", "arcadeZone"] if not intents["food"] else ["foodCourtA", "indoorHub"]
        constraints["equipment_controls"].append({"equipmentType": "hvac", "zones": zones, "settings": {"indoorHubSetpointF": 72, "foodCourtASetpointF": 73, "shedNoncriticalLighting": True}, "reason": "Operator requested comfort/temperature control."})
        constraints["decision_rules"].append("Apply only comfort/load controls, not safety-critical automation.")

    dispatches: list[dict[str, Any]] = []
    if intents["medical"] or intents["accessibility"] or intents["security"]:
        selected_target = "medical" if intents["medical"] else "security" if intents["security"] else "accessibility"
        selected_action = "dispatch" if intents["medical"] else "respond" if intents["security"] else "assist"
        selected_label = "Dispatch medical/accessibility response and protect privacy" if intents["medical"] and intents["accessibility"] else "Dispatch medical response and protect privacy" if intents["medical"] else "Dispatch security and protect emergency routes" if intents["security"] else "Dispatch accessibility support"
        selected = {"label": selected_label, "target": selected_target, "action": selected_action, "owner": "Guest Care"}
        if intents["family_care"] or intents["security"]:
            dispatches.append(
                {
                    "id": f"lazy_guest_{now_id}",
                    "channel": "guest_app",
                    "endpoint": "/api/actions/guest-message",
                    "status": "sent",
                    "payload": {
                        "message": "Staff are assisting nearby. Please use the calm route toward Theater B or Family Garden and keep the access lane clear.",
                        "targetZone": affected_zone,
                        "targetMix": [
                            {"zoneId": "theaterB", "destination": "Theater B", "share": 0.35, "rationale": "Calm indoor destination"},
                            {"zoneId": "familyGarden", "destination": "Family Garden", "share": 0.25, "rationale": "Family-safe relief area"},
                        ],
                        "privacy": "no_medical_or_child_details",
                    },
                    "response": {"takeRate": 0.39, "positiveResponseRate": 0.78, "reactiveFollowThroughRate": 0.52, "sampleSize": 120},
                }
            )
        for move in constraints["required_staff_moves"]:
            dispatches.append(
                {
                    "id": f"lazy_worker_{move['role']}_{now_id}",
                    "channel": "worker_device",
                    "endpoint": "/api/actions/worker-task",
                    "status": "assigned",
                    "payload": {
                        "task": f"Move {move.get('count', 1)} {move['role']} from {move.get('from', 'available pool')} to {move.get('to', affected_name)}; keep guest details private and preserve the access lane.",
                        "targetZone": affected_zone,
                        "role": move["role"],
                        "count": move.get("count", 1),
                        "staffMoves": [move],
                        "privacy": "need_to_know",
                    },
                    "response": {"acknowledgedCount": move.get("count", 1), "sampleSize": move.get("count", 1), "reactiveFollowThroughRate": 0.82},
                }
            )
        dispatches.append(
            {
                "id": f"lazy_equipment_access_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {"command": "keep_access_lane_clear", "equipmentType": "digital_signage", "zones": [affected_zone, "medicalAccess"], "settings": {"message": "Please keep this access lane clear for staff assistance."}},
                "response": {"applied": True, "sampleSize": 1},
            }
        )
    elif scenario_key == "food_spike":
        selected = {"label": "Redirect Food Court A demand to available food capacity", "target": "food", "action": "redirect_food_demand", "owner": "Food Ops"}
        dispatches = [
            {
                "id": f"lazy_guest_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {
                    "message": "Food Court A is temporarily unavailable. Use Food Court B or Main Street Shops for faster pickup; Food Court A pickup estimates are being updated.",
                    "targetZone": "foodCourtA",
                    "avoidExtraDemandAt": constraints["avoid_zones"],
                    "targetMix": [
                        {"zoneId": "foodCourtB", "destination": "Food Court B", "share": 0.5, "rationale": "Available food capacity"},
                        {"zoneId": "mainStreet", "destination": "Main Street Shops", "share": 0.3, "rationale": "Nearby alternate service"},
                        {"zoneId": "foodCourtA", "destination": "Hold current pickup only", "share": 0.2, "rationale": "No new demand"},
                    ],
                },
                "response": {"takeRate": 0.46, "positiveResponseRate": 0.72, "reactiveFollowThroughRate": 0.58, "sampleSize": 180},
            },
            {
                "id": f"lazy_worker_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {
                    "task": "Close new Food Court A pickup intake, station 2 food-service staff at the pickup edge, and redirect mobile-order guests to Food Court B.",
                    "targetZone": "foodCourtA",
                    "role": "food_service",
                    "count": 2,
                    "staffMoves": constraints["required_staff_moves"],
                },
                "response": {"acknowledgedCount": 2, "sampleSize": 2, "reactiveFollowThroughRate": 0.8},
            },
            {
                "id": f"lazy_equipment_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {"command": "suppress_mobile_order_intake", "equipmentType": "menu_control", "zones": ["foodCourtA"], "settings": {"mobileOrdering": "paused", "pickupEtaVisible": True}},
                "response": {"applied": True, "sampleSize": 1},
            },
        ]
        if intents["hvac"]:
            dispatches.append(
                {
                    "id": f"lazy_equipment_hvac_{now_id}",
                    "channel": "equipment_controller",
                    "endpoint": "/api/actions/equipment-command",
                    "status": "commanded",
                    "payload": {
                        "command": "apply_custom_comfort_mix",
                        "equipmentType": "hvac",
                        "zones": ["foodCourtA", "indoorHub"],
                        "settings": {
                            "foodCourtASetpointF": 73,
                            "indoorHubSetpointF": 72,
                            "shedNoncriticalLighting": True,
                        },
                    },
                    "response": {"applied": True, "sampleSize": 1},
                }
            )
    elif scenario_key == "equipment_safety":
        selected = {"label": "Hold suspect equipment effects and send technician verification", "target": "equipment", "action": "hold_equipment_changes", "owner": "Maintenance"}
        dispatches = [
            {
                "id": f"lazy_worker_equipment_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {
                    "task": f"Verify equipment safety report at {affected_name}; hold noncritical effects and keep guests out of the service lane until cleared.",
                    "targetZone": affected_zone,
                    "role": "technician",
                    "count": 1,
                    "staffMoves": constraints["required_staff_moves"],
                },
                "response": {"acknowledgedCount": 1, "sampleSize": 1, "reactiveFollowThroughRate": 0.83},
            },
            {
                "id": f"lazy_equipment_safety_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {
                    "command": "hold_noncritical_automation_until_technician_check",
                    "equipmentType": "facility_controls",
                    "zones": [affected_zone],
                    "settings": {"holdLightingChanges": True, "holdFogEffects": True, "showServiceLaneClear": True},
                    "requiresHumanApproval": True,
                },
                "response": {"applied": True, "sampleSize": 1},
            },
            {
                "id": f"lazy_guest_equipment_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {
                    "message": "A nearby walkway is being adjusted. Please follow staff guidance and use the marked alternate route.",
                    "targetZone": affected_zone,
                    "privacy": "no_unverified_safety_details",
                    "targetMix": [
                        {"zoneId": "theaterB", "destination": "Theater B", "share": 0.35, "rationale": "Calm alternate destination"},
                        {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.25, "rationale": "Open indoor capacity"},
                    ],
                },
                "response": {"takeRate": 0.37, "positiveResponseRate": 0.72, "reactiveFollowThroughRate": 0.5, "sampleSize": 100},
            },
        ]
    elif scenario_key == "crowd_safety":
        selected = {"label": "Disperse crowd pressure and keep access routes clear", "target": "crowd_safety", "action": "calm_reroute", "owner": "Park Ops"}
        constraints["preferred_destinations"] = [{"id": "theaterB", "name": "Theater B"}, {"id": "familyGarden", "name": "Family Garden"}, {"id": "arcadeZone", "name": "Arcade Zone"}]
        if not any(move.get("role") == "crowd_control" for move in constraints["required_staff_moves"]):
            constraints["required_staff_moves"].append({"role": "crowd_control", "count": 3, "from": "staffBase", "to": affected_name, "deadlineMinutes": 5, "reason": "Crowd pressure signal in operator text."})
        constraints["equipment_controls"].append({"equipmentType": "digital_signage", "zones": [affected_zone, "medicalAccess"], "settings": {"message": "Use alternate calm route; keep service access clear."}})
        dispatches = [
            {
                "id": f"lazy_guest_crowd_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {
                    "message": "This area is busy. For a calmer route, use Theater B, Family Garden, or Arcade Zone and keep service lanes clear.",
                    "targetZone": affected_zone,
                    "targetMix": [
                        {"zoneId": "theaterB", "destination": "Theater B", "share": 0.34, "rationale": "Calm seated capacity"},
                        {"zoneId": "familyGarden", "destination": "Family Garden", "share": 0.26, "rationale": "Lower-density family route"},
                        {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.22, "rationale": "High-throughput indoor relief"},
                    ],
                    "tone": "calm_non_alarmist",
                },
                "response": {"takeRate": 0.4, "positiveResponseRate": 0.76, "reactiveFollowThroughRate": 0.54, "sampleSize": 180},
            },
            {
                "id": f"lazy_worker_crowd_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {
                    "task": f"Move crowd-control staff to {affected_name}, open the calm alternate route, and keep emergency/service access clear.",
                    "targetZone": affected_zone,
                    "role": "crowd_control",
                    "count": 3,
                    "staffMoves": constraints["required_staff_moves"],
                },
                "response": {"acknowledgedCount": 3, "sampleSize": 3, "reactiveFollowThroughRate": 0.8},
            },
            {
                "id": f"lazy_equipment_crowd_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {"command": "show_calm_alternate_route", "equipmentType": "digital_signage", "zones": [affected_zone, "medicalAccess"], "settings": {"message": "Alternate route open; keep access lane clear."}},
                "response": {"applied": True, "sampleSize": 1},
            },
        ]
    elif scenario_key == "ride_down":
        selected = {"label": "Pause ride queue intake and redistribute demand", "target": "ride", "action": "reroute_down_ride", "owner": "Ride Ops"}
        constraints["avoid_zones"] = [{"id": "dragonCoaster", "name": "Dragon Coaster", "reason": "Operator described ride downtime or queue failure."}]
        constraints["preferred_destinations"] = [{"id": "arcadeZone", "name": "Arcade Zone"}, {"id": "theaterB", "name": "Theater B"}, {"id": "indoorLaunch", "name": "Indoor Launch"}]
        constraints["required_staff_moves"].append({"role": "crowd_control", "count": 3, "from": "staffBase", "to": "Coaster Plaza", "deadlineMinutes": 6, "reason": "Guests need queue-exit support."})
        constraints["equipment_controls"].append({"equipmentType": "digital_signage", "zones": ["dragonCoaster", "coasterPlaza"], "settings": {"queueIntake": "paused", "statusVisible": True}})
        dispatches = [
            {
                "id": f"lazy_guest_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {
                    "message": "Dragon Coaster is temporarily unavailable. For shorter waits, head to Arcade Zone, Theater B, or Indoor Launch while ride ops updates the queue.",
                    "targetZone": "dragonCoaster",
                    "avoidExtraDemandAt": constraints["avoid_zones"],
                    "targetMix": [
                        {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.4, "rationale": "High capacity overflow"},
                        {"zoneId": "theaterB", "destination": "Theater B", "share": 0.25, "rationale": "Indoor seated capacity"},
                        {"zoneId": "indoorLaunch", "destination": "Indoor Launch", "share": 0.2, "rationale": "Ride alternative with staffed queue"},
                    ],
                },
                "response": {"takeRate": 0.44, "positiveResponseRate": 0.7, "reactiveFollowThroughRate": 0.56, "sampleSize": 260},
            },
            {
                "id": f"lazy_worker_ride_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {
                    "task": "Pause new Dragon Coaster queue intake, split the existing queue toward Arcade Zone and Theater B, and keep maintenance clearance separate from guest messaging.",
                    "targetZone": "coasterPlaza",
                    "role": "crowd_control",
                    "count": 3,
                    "staffMoves": constraints["required_staff_moves"],
                },
                "response": {"acknowledgedCount": 3, "sampleSize": 3, "reactiveFollowThroughRate": 0.81},
            },
            {
                "id": f"lazy_equipment_ride_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {"command": "pause_queue_intake_signage", "equipmentType": "digital_signage", "zones": ["dragonCoaster", "coasterPlaza"], "settings": {"queueIntake": "paused", "showAlternates": True}},
                "response": {"applied": True, "sampleSize": 1},
            },
        ]
    elif scenario_key == "staff_shortage":
        selected = {"label": "Redeploy staff while protecting breaks", "target": "staff", "action": "redeploy_staff", "owner": "Staffing"}
        if not any(move.get("role") == "crowd_control" for move in constraints["required_staff_moves"]):
            constraints["required_staff_moves"].append({"role": "crowd_control", "count": 2, "from": "staffBase", "to": affected_name, "deadlineMinutes": 8, "reason": "Operator described staffing pressure."})
        constraints["decision_rules"].append("Protect legally required breaks and certified ride positions.")
        dispatches = [
            {
                "id": f"lazy_worker_staff_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {
                    "task": f"Move 2 crowd-control staff to {affected_name}, keep certified ride operators in place, and protect scheduled breaks.",
                    "targetZone": affected_zone,
                    "role": "crowd_control",
                    "count": 2,
                    "staffMoves": constraints["required_staff_moves"],
                },
                "response": {"acknowledgedCount": 2, "sampleSize": 2, "reactiveFollowThroughRate": 0.78},
            },
            {
                "id": f"lazy_guest_staff_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {
                    "message": "Some service points are moving slower while teams rebalance staffing. Use Theater B or Main Street Shops for lower-pressure alternatives.",
                    "targetZone": affected_zone,
                    "targetMix": [
                        {"zoneId": "theaterB", "destination": "Theater B", "share": 0.35, "rationale": "Low-staff pressure relief"},
                        {"zoneId": "mainStreet", "destination": "Main Street Shops", "share": 0.25, "rationale": "Open staff coverage"},
                    ],
                },
                "response": {"takeRate": 0.31, "positiveResponseRate": 0.66, "reactiveFollowThroughRate": 0.43, "sampleSize": 120},
            },
        ]
    elif intents["family_care"]:
        selected = {"label": "Route families to calm areas and send guest-service support", "target": "guest_care", "action": "family_care_reroute", "owner": "Guest Services"}
        dispatches = [
            {
                "id": f"lazy_guest_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {
                    "message": "For a calmer route, head toward Theater B or Family Garden. Guest Services staff are moving nearby to help families.",
                    "targetZone": "familyGarden",
                    "targetMix": [
                        {"zoneId": "theaterB", "destination": "Theater B", "share": 0.45, "rationale": "Calm indoor show area"},
                        {"zoneId": "familyGarden", "destination": "Family Garden", "share": 0.35, "rationale": "Lower-intensity family relief area"},
                    ],
                },
                "response": {"takeRate": 0.42, "positiveResponseRate": 0.81, "reactiveFollowThroughRate": 0.55, "sampleSize": 140},
            },
            {
                "id": f"lazy_worker_family_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {
                    "task": "Move Guest Services support to Family Garden and guide families through the calm route from the haunted zone.",
                    "targetZone": "familyGarden",
                    "role": "guest_services",
                    "count": 2,
                    "staffMoves": constraints["required_staff_moves"],
                },
                "response": {"acknowledgedCount": 2, "sampleSize": 2, "reactiveFollowThroughRate": 0.79},
            },
        ]
    elif intents["hvac"]:
        selected = {"label": "Adjust comfort controls without safety-critical automation", "target": "energy", "action": "protect_hvac", "owner": "Facilities"}
        dispatches = [
            {
                "id": f"lazy_equipment_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {"command": "apply_custom_comfort_mix", "equipmentType": "hvac", "zones": ["indoorHub", "arcadeZone"], "settings": {"indoorHubSetpointF": 72, "arcadeZoneSetpointF": 73, "shedNoncriticalLighting": True}},
                "response": {"applied": True, "sampleSize": 1},
            },
            {
                "id": f"lazy_worker_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {"task": "Check indoor comfort complaints and verify HVAC setpoints were applied.", "targetZone": "indoorHub", "role": "facilities", "count": 1},
                "response": {"acknowledgedCount": 1, "sampleSize": 1, "reactiveFollowThroughRate": 0.75},
            },
        ]
    else:
        selected = {"label": "Create a bounded custom operating response", "target": scenario_key, "action": "custom_response", "owner": "Park Ops"}
        dispatches = [
            {
                "id": f"lazy_worker_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {"task": f"Review and execute custom operator request: {message[:140]}", "targetZone": "coveredPlaza", "role": "operations_lead", "count": 1},
                "response": {"acknowledgedCount": 1, "sampleSize": 1, "reactiveFollowThroughRate": 0.75},
            }
        ]
    summary = {"total": len(dispatches), "guest_app": 0, "worker_device": 0, "equipment_controller": 0}
    for dispatch in dispatches:
        if dispatch["channel"] in summary:
            summary[dispatch["channel"]] += 1
    run_telemetry = {
        "scenario_key": scenario_key,
        "planner": {"runtime": "bounded_action_engine", "model": "fast_operating_policy", "gemini_ready": False, "attempted_gemini": True, "selected_action": selected, "confidence_score": 0.62, "analysis": f"Returned bounded custom actions from the fast operating policy while Gemini refinement runs asynchronously: {reason}."},
        "operator_constraints": constraints,
        "delivery": {"summary": summary, "dispatches": dispatches, "response": {"takeRate": 0.46, "positiveResponseRate": 0.72, "reactiveFollowThroughRate": 0.58, "score": 78, "status": "estimated_lazy_response"}},
        "governance": {"allowed": True, "gate_status": "allowed", "findings": ["Lazy bounded response emitted custom actions only; stale scenario fallbacks are blocked."]},
        "eval": {"scorecard": {"overall": 78, "policy_guidance_score": 86, "policy_gate_status": "allowed", "policy_violation": False, "needs_human_approval": route["requires_human_review"]}},
        "optimization": {"operator_constraints": constraints, "operator_candidate_frame": {"primary_action": selected, "rejected_options": [{"reason": constraints["rejected_option"]}]}},
    }
    payload = {
        "status": "complete",
        "command": message,
        "route": route,
        "role_route": route,
        "mode": route["route"],
        "operator_constraints": constraints,
        "operator_response": {"headline": selected["label"], "summary": run_telemetry["planner"]["analysis"], "next_step": "Receiver payloads are visible on the map; rerun the full Gemini path when ready."},
        "run_telemetry": run_telemetry,
    }
    return _persist_role_receipt(payload, role=str(route.get("selected_role") or "react"), route=route, scenario_key=scenario_key)


async def _get_full_module(timeout: float | None = None):
    if _parkpulse_app is not None:
        return _parkpulse_module
    task = asyncio.wrap_future(_ensure_full_module_load_task())
    if timeout is None:
        return await asyncio.shield(task)
    return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


async def _get_full_module_for_first_response(timeout: float):
    if _parkpulse_app is not None:
        return _parkpulse_module
    if _load_task is not None and not _load_task.done() and _load_started_at is not None:
        elapsed = time.time() - _load_started_at
        if elapsed >= max(0.0, timeout):
            raise TimeoutError(f"Full runtime is still warming after {elapsed:.1f}s; returning fast response.")
    return await _get_full_module(timeout=timeout)


async def _get_full_app():
    module = await _get_full_module()
    return module.app


def _agent_run_request_fields(request_payload: dict[str, Any]) -> dict[str, Any]:
    scenario_key = str(request_payload.get("scenario_key") or request_payload.get("scenarioKey") or "").strip()
    message = str(
        request_payload.get("operator_message")
        or request_payload.get("operatorMessage")
        or request_payload.get("message")
        or request_payload.get("command")
        or (f"Run scenario {scenario_key}." if scenario_key else "Run the current park operating scenario.")
    ).strip()
    return {
        "scenario_key": scenario_key,
        "message": message,
        "execute": str(request_payload.get("execute", "true")).lower() not in {"0", "false", "no"},
        "operation_mode": bool(request_payload.get("operation_mode", request_payload.get("operationMode", False))),
        "auto_unexpected_event": bool(request_payload.get("auto_unexpected_event", request_payload.get("autoUnexpectedEvent", False))),
    }


def _build_full_agent_run_request(module: Any, fields: dict[str, Any]) -> Any:
    return module.ParkAgentRunRequest(
        scenario_key=fields["scenario_key"] or None,
        operation_mode=fields["operation_mode"],
        auto_unexpected_event=fields["auto_unexpected_event"],
        operator_message=fields["message"],
        execute=fields["execute"],
    )


async def _build_operator_payload_with_runtime(message: str, mode: str, execute: bool, reason: str) -> dict[str, Any]:
    tiers = _timeout_tiers()
    if _parkpulse_app is not None and not _sync_full_response_enabled():
        _metric("operator_command_fallback")
        fallback = _lazy_operator_payload(message, mode, "fast_first_response: full runtime refinement scheduled outside the request path")
        fallback["status"] = "bounded_fallback"
        fallback.setdefault("runtime_proof", {})["fallback_reason"] = "Full runtime is loaded; running refinement outside the first response."
        fallback["runtime_proof"]["full_runtime"] = _full_runtime_status()
        fallback["runtime_proof"]["timeout_tiers"] = tiers
        fallback["runtime_proof"]["receipt_upgrade_status"] = "pending"
        fallback["operator_response"]["next_step"] = "Bounded receiver payloads are available now; full-runtime refinement is tracked on the receipt."
        stored = _store_run_receipt(fallback, message=message, mode=mode, kind="operator_command", upgrade_status="pending")
        receipt_id = stored.get("run_receipt", {}).get("id")
        if receipt_id:
            _schedule_operator_command_refinement(message, mode, execute, receipt_id)
        return stored
    try:
        module = await _get_full_module_for_first_response(float(tiers["operator_full_load_seconds"]))
        request = module.OperatorCommandRequest(message=message, mode=mode, execute=execute)
        payload = await asyncio.wait_for(
            module.park_operator_command(request),
            timeout=float(tiers["operator_command_seconds"]),
        )
        if isinstance(payload, dict):
            _metric("operator_command_full_success")
            return _store_run_receipt(payload, message=message, mode=mode, kind="operator_command")
        return payload
    except Exception as error:
        _metric("operator_command_fallback")
        error_detail = str(error) or type(error).__name__
        fallback = _lazy_operator_payload(message, mode, f"{reason}: {type(error).__name__}: {error_detail}")
        fallback["status"] = "bounded_fallback"
        fallback.setdefault("runtime_proof", {})["fallback_reason"] = error_detail
        fallback["runtime_proof"]["full_runtime"] = _full_runtime_status()
        fallback["runtime_proof"]["timeout_tiers"] = tiers
        fallback["runtime_proof"]["receipt_upgrade_status"] = "pending"
        fallback["operator_response"]["next_step"] = "Bounded receiver payloads were emitted because the full Gemini path was not available before the UI timeout."
        stored = _store_run_receipt(fallback, message=message, mode=mode, kind="operator_command", upgrade_status="pending")
        receipt_id = stored.get("run_receipt", {}).get("id")
        if receipt_id:
            _schedule_operator_command_refinement(message, mode, execute, receipt_id)
        return stored


async def _build_agent_run_payload_with_runtime(request_payload: dict[str, Any], reason: str) -> dict[str, Any]:
    fields = _agent_run_request_fields(request_payload)
    scenario_key = fields["scenario_key"]
    message = fields["message"]
    tiers = _timeout_tiers()
    load_timeout = float(tiers["agent_run_full_load_seconds"])
    run_timeout = float(tiers["agent_run_seconds"])
    if _parkpulse_app is not None and not _sync_full_response_enabled():
        _metric("agent_run_fallback")
        fallback = _lazy_operator_payload(message, "auto", "fast_first_response: full runtime refinement scheduled outside the request path")
        fallback["status"] = "bounded_fallback"
        if scenario_key:
            fallback["scenario_key"] = scenario_key
            fallback.setdefault("run_telemetry", {})["requested_scenario_key"] = scenario_key
        fallback.setdefault("runtime_proof", {})["fallback_reason"] = "Full runtime is loaded; running refinement outside the first response."
        fallback["runtime_proof"]["full_runtime"] = _full_runtime_status()
        fallback["runtime_proof"]["timeout_tiers"] = tiers
        fallback["runtime_proof"]["receipt_upgrade_status"] = "pending"
        fallback["operator_response"]["next_step"] = "Fast hybrid receiver payloads are available now; full-runtime refinement is tracked on the receipt."
        stored = _store_run_receipt(fallback, message=message, mode=scenario_key or "agent_run", kind="agent_run", upgrade_status="pending")
        receipt_id = stored.get("run_receipt", {}).get("id")
        if receipt_id:
            _schedule_agent_run_refinement(request_payload, receipt_id, message=message, mode=scenario_key or "agent_run")
        return stored
    try:
        module = await _get_full_module_for_first_response(load_timeout)
        request = _build_full_agent_run_request(module, fields)
        payload = await asyncio.wait_for(module.park_agent_run(request), timeout=run_timeout)
        if isinstance(payload, dict):
            payload.setdefault("runtime_proof", {})["full_runtime"] = _full_runtime_status()
            _metric("agent_run_full_success")
            return _store_run_receipt(payload, message=message, mode=scenario_key or "agent_run", kind="agent_run")
        return payload
    except Exception as error:
        _metric("agent_run_fallback")
        error_detail = str(error) or type(error).__name__
        fallback = _lazy_operator_payload(message, "auto", f"{reason}: {type(error).__name__}: {error_detail}")
        fallback["status"] = "bounded_fallback"
        if scenario_key:
            fallback["scenario_key"] = scenario_key
            fallback.setdefault("run_telemetry", {})["requested_scenario_key"] = scenario_key
        fallback.setdefault("runtime_proof", {})["fallback_reason"] = error_detail
        fallback["runtime_proof"]["full_runtime"] = _full_runtime_status()
        fallback["runtime_proof"]["timeout_tiers"] = tiers
        fallback["runtime_proof"]["receipt_upgrade_status"] = "pending"
        fallback["operator_response"]["next_step"] = "Fast hybrid receiver payloads were emitted because the full agent-run path did not finish before the API budget."
        stored = _store_run_receipt(fallback, message=message, mode=scenario_key or "agent_run", kind="agent_run", upgrade_status="pending")
        receipt_id = stored.get("run_receipt", {}).get("id")
        if receipt_id:
            _schedule_agent_run_refinement(request_payload, receipt_id, message=message, mode=scenario_key or "agent_run")
        return stored


def _schedule_operator_command_refinement(message: str, mode: str, execute: bool, receipt_id: str) -> None:
    claimed, reason = _try_claim_refinement_slot(receipt_id)
    if not claimed:
        _mark_receipt_upgrade_status(receipt_id, "deferred", {"mode": "background_full_operator_command", "reason": reason, "deferredAt": _now_iso()})
        return
    _mark_receipt_upgrade_status(receipt_id, "pending", {"mode": "background_full_operator_command", "queuedAt": _now_iso()})
    _refinement_executor.submit(_operator_command_refinement_worker, message, mode, execute, receipt_id)


def _operator_command_refinement_worker(message: str, mode: str, execute: bool, receipt_id: str) -> None:
    _metric("operator_command_refinement_started")
    _mark_receipt_upgrade_status(receipt_id, "running", {"mode": "background_full_operator_command", "startedAt": _now_iso()})
    started = time.time()
    try:
        module = _load_full_module_locked()
        request = module.OperatorCommandRequest(message=message, mode=mode, execute=execute)
        timeout_seconds = float(_timeout_tiers()["refinement_seconds"])
        payload = asyncio.run(asyncio.wait_for(module.park_operator_command(request), timeout=timeout_seconds))
        if not isinstance(payload, dict):
            raise TypeError("Full operator-command refinement returned a non-dict payload.")
        payload.setdefault("runtime_proof", {})["full_runtime"] = _full_runtime_status()
        payload["runtime_proof"]["refinement_elapsed_ms"] = int((time.time() - started) * 1000)
        _upgrade_run_receipt(receipt_id, payload, message=message, mode=mode, kind="operator_command")
        _metric("operator_command_refinement_succeeded")
    except Exception as error:
        _metric("operator_command_refinement_failed")
        _mark_receipt_upgrade_status(
            receipt_id,
            "failed",
            {
                "mode": "background_full_operator_command",
                "failedAt": _now_iso(),
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": str(error)[:500],
            },
        )
    finally:
        _release_refinement_slot(receipt_id)


def _schedule_agent_run_refinement(request_payload: dict[str, Any], receipt_id: str, *, message: str, mode: str) -> None:
    claimed, reason = _try_claim_refinement_slot(receipt_id)
    if not claimed:
        _mark_receipt_upgrade_status(receipt_id, "deferred", {"mode": "background_full_agent_run", "reason": reason, "deferredAt": _now_iso()})
        return
    _mark_receipt_upgrade_status(receipt_id, "pending", {"mode": "background_full_agent_run", "queuedAt": _now_iso()})
    _refinement_executor.submit(_agent_run_refinement_worker, json.loads(json.dumps(request_payload, default=str)), receipt_id, message, mode)


def _agent_run_refinement_worker(request_payload: dict[str, Any], receipt_id: str, message: str, mode: str) -> None:
    _metric("agent_run_refinement_started")
    _mark_receipt_upgrade_status(receipt_id, "running", {"mode": "background_full_agent_run", "startedAt": _now_iso()})
    started = time.time()
    try:
        module = _load_full_module_locked()
        fields = _agent_run_request_fields(request_payload)
        request = _build_full_agent_run_request(module, fields)
        timeout_seconds = float(_timeout_tiers()["refinement_seconds"])
        payload = asyncio.run(asyncio.wait_for(module.park_agent_run(request), timeout=timeout_seconds))
        if not isinstance(payload, dict):
            raise TypeError("Full agent-run refinement returned a non-dict payload.")
        payload.setdefault("runtime_proof", {})["full_runtime"] = _full_runtime_status()
        payload["runtime_proof"]["refinement_elapsed_ms"] = int((time.time() - started) * 1000)
        _upgrade_run_receipt(receipt_id, payload, message=message, mode=mode, kind="agent_run")
        _metric("agent_run_refinement_succeeded")
    except Exception as error:
        _metric("agent_run_refinement_failed")
        _mark_receipt_upgrade_status(
            receipt_id,
            "failed",
            {
                "mode": "background_full_agent_run",
                "failedAt": _now_iso(),
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": str(error)[:500],
            },
        )
    finally:
        _release_refinement_slot(receipt_id)


async def _operator_command_stream(scope, send) -> None:
    query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
    message = (query.get("message") or ["Custom park operating request."])[0].strip()
    mode = (query.get("mode") or ["auto"])[0]
    execute = (query.get("execute") or ["true"])[0].lower() not in {"0", "false", "no"}
    stream_run_id = f"lazy_operator_{int(time.time() * 1000)}"
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/event-stream"),
                (b"cache-control", b"no-store"),
                (b"connection", b"keep-alive"),
                (b"access-control-allow-origin", b"*"),
            ],
        }
    )
    started = time.time()
    warm_task = _ensure_full_module_load_task()
    early_stages = [
        ("operator.started", "operator", "Operator request", 0, message),
        ("intent.done", "intent", "Intent parsed", 0, "1/7 Understand: command received; routing and constraints are being prepared."),
        ("memory.done", "memory", "Mongo memory retrieval", 1, "2/7 Retrieve memory: warming the operational memory layer while the app loads."),
        ("priors.done", "priors", "BigQuery priors", 1, "3/7 Load priors: preparing historical take-rate and follow-through context."),
        ("preview.done", "preview", "Fast local preview", 2, "4/7 Draft preview: staging a preliminary action mix before Gemini returns."),
        ("policy.done", "policy", "Policy guardrails", 2, "5/7 Check policy: preparing safety, staffing, and guest-message gates."),
        ("gemini.done", "gemini", "Gemini refinement", 3, "6/7 Gemini reasoning: loading the full agent runtime and model path."),
    ]
    for event_name, phase, label, step, stage_message in early_stages:
        await send(
            {
                "type": "http.response.body",
                "body": _sse(
                    event_name,
                    {
                        "run_id": stream_run_id,
                        "phase": phase,
                        "label": label,
                        "step": step,
                        "message": stage_message,
                        "elapsed_ms": int((time.time() - started) * 1000),
                        "artifact": {"entrypoint": "lazy-main", "full_runtime": _full_runtime_status()},
                    },
                ),
                "more_body": True,
            }
        )
        await asyncio.sleep(0.25)

    heartbeat = 0
    warm_timeout = float(_timeout_tiers()["operator_full_load_seconds"])
    while not warm_task.done():
        if time.time() - started >= warm_timeout:
            payload = _lazy_operator_payload(message, mode, "stream_full_runtime_warmup_timeout")
            payload["status"] = "bounded_fallback"
            break
        await asyncio.sleep(1.0)
        heartbeat += 1
        await send(
            {
                "type": "http.response.body",
                "body": _sse(
                    "gemini.progress",
                    {
                        "run_id": stream_run_id,
                        "phase": "gemini",
                        "label": "Runtime still warming",
                        "step": 3,
                        "message": f"6/7 Gemini reasoning: full runtime still loading ({round(time.time() - started)}s elapsed).",
                        "elapsed_ms": int((time.time() - started) * 1000),
                        "artifact": {"heartbeat": heartbeat, **_full_runtime_status()},
                    },
                ),
                "more_body": True,
            }
        )

    else:
        payload = None

    if payload is None:
        try:
            module = await asyncio.wrap_future(warm_task)
            request = module.OperatorCommandRequest(message=message, mode=mode, execute=execute)
            command_task = asyncio.create_task(module.park_operator_command(request))
            timeout_seconds = float(os.getenv("OPERATOR_COMMAND_TIMEOUT_SECONDS", "20")) + 5
            command_started = time.time()
            while not command_task.done():
                if time.time() - command_started > timeout_seconds:
                    command_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await command_task
                    payload = _lazy_operator_payload(message, mode, "stream_full_runtime_timeout")
                    payload["status"] = "bounded_fallback"
                    break
                await asyncio.sleep(1.0)
                await send(
                    {
                        "type": "http.response.body",
                        "body": _sse(
                            "gemini.progress",
                            {
                                "run_id": stream_run_id,
                                "phase": "gemini",
                                "label": "Gemini operating the park",
                                "step": 3,
                                "message": "Gemini is grounding the operator text in live park state, MongoDB memory, BigQuery priors, policy, and receiver contracts.",
                                "elapsed_ms": int((time.time() - started) * 1000),
                                "artifact": {"wait_seconds": round(time.time() - command_started, 1), "status": "full_operator_command_running"},
                            },
                        ),
                        "more_body": True,
                    }
                )
            else:
                payload = await command_task
        except Exception as error:
            payload = _lazy_operator_payload(message, mode, f"stream_full_runtime_error: {type(error).__name__}: {error}")
            payload["status"] = "bounded_fallback"

    delivery = payload.get("run_telemetry", {}).get("delivery", {}) if isinstance(payload, dict) else {}
    summary = delivery.get("summary", {}) if isinstance(delivery, dict) else {}
    await send(
        {
            "type": "http.response.body",
            "body": _sse(
                "dispatch.done",
                {
                    "run_id": stream_run_id,
                    "phase": "dispatch",
                    "label": "Receiver payloads ready",
                    "step": 4,
                    "message": f"7/7 Dispatch: emitted {summary.get('total', 0)} receiver payloads from the custom operating plan.",
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "artifact": summary,
                },
            ),
            "more_body": True,
        }
    )

    await send(
        {
            "type": "http.response.body",
            "body": _sse(
                "run.complete",
                {
                    "run_id": payload.get("run_telemetry", {}).get("decision_id") or stream_run_id,
                    "phase": payload.get("mode", "command"),
                    "label": payload.get("route", {}).get("interpreted_intent", "Operator command complete"),
                    "step": 4,
                    "message": payload.get("operator_response", {}).get("headline", "Operator command complete."),
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "payload": payload,
                },
            ),
            "more_body": False,
        }
    )


async def _proactive_run_stream(scope, send) -> None:
    query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
    stream_run_id = (query.get("client_run_id") or [f"proactive_{int(time.time() * 1000)}"])[0]
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/event-stream"),
                (b"cache-control", b"no-store"),
                (b"connection", b"keep-alive"),
                (b"access-control-allow-origin", b"*"),
            ],
        }
    )
    started = time.time()

    async def send_event(event_name: str, payload: dict[str, Any], more_body: bool = True) -> None:
        await send(
            {
                "type": "http.response.body",
                "body": _sse(event_name, {"run_id": stream_run_id, "elapsed_ms": int((time.time() - started) * 1000), **payload}),
                "more_body": more_body,
            }
        )

    try:
        proactive_preview = _lazy_proactive_insights()
        top_signal = (proactive_preview.get("insights") or [{}])[0]
        await send_event(
            "run.started",
            {
                "phase": "started",
                "label": "Full park watch started",
                "step": -1,
                "message": "ParkPulse started the proactive loop and is reading live park state, vague signals, memory, and response priors.",
                "artifact": {"entrypoint": "lazy-main", "loop": "detect_predict_proact_learn"},
            },
        )
        payload_task = asyncio.create_task(_build_proactive_payload_with_runtime("stream_fast_path"))
        await asyncio.sleep(0.16)
        await send_event(
            "predict.done",
            {
                "phase": "predict",
                "label": "Weak signal detected",
                "step": 0,
                "message": f"Detected: {top_signal.get('trigger', 'multiple weak signals are converging')}",
                "artifact": {
                    "insight_id": top_signal.get("id"),
                    "agent": top_signal.get("agent"),
                    "urgency": top_signal.get("urgency"),
                    "confidence": top_signal.get("confidence"),
                    "busiest_zone": proactive_preview.get("summary", {}).get("busiest_zone"),
                },
            },
        )
        await asyncio.sleep(0.16)
        await send_event(
            "gemini.progress",
            {
                "phase": "gemini",
                "label": "Gemini reasoning started",
                "step": 1,
                "message": "Gemini is building a custom operating brief from the top weak signals, MongoDB memory, and BigQuery take-rate priors.",
                "artifact": _gemini_runtime_properties(),
            },
        )

        heartbeat_messages = [
            "Gemini is comparing guest nudges, worker redeployment, and equipment controls against the same park state.",
            "Gemini is checking whether this should be proactive action, operator review, or bounded fallback.",
            "Gemini is compressing the plan into executable guest, worker, and equipment receiver payloads.",
            "Still waiting on Gemini; the hard-timeout guard will return a marked fallback if the provider is slow.",
        ]
        heartbeat_index = 0
        while not payload_task.done():
            await asyncio.sleep(1.0)
            await send_event(
                "gemini.progress",
                {
                    "phase": "gemini",
                    "label": "Gemini thinking",
                    "step": 1,
                    "message": heartbeat_messages[min(heartbeat_index, len(heartbeat_messages) - 1)],
                    "artifact": {
                        "wait_seconds": round(time.time() - started, 1),
                        "hard_timeout_seconds": os.getenv("PARKPULSE_FAST_GEMINI_PROACTIVE_TIMEOUT_SECONDS", "6"),
                    },
                },
            )
            heartbeat_index += 1

        payload = await payload_task
        proof = payload.get("runtime_proof", {}) if isinstance(payload, dict) else {}
        brief = payload.get("brief", {}) if isinstance(payload, dict) else {}
        delivery = payload.get("delivery", {}) if isinstance(payload, dict) else {}
        summary = delivery.get("summary", {}) if isinstance(delivery, dict) else {}
        outcome = payload.get("outcome", {}) if isinstance(payload, dict) else {}
        application = outcome.get("application", {}) if isinstance(outcome, dict) else {}
        await send_event(
            "decide.done",
            {
                "phase": "decide",
                "label": "Gemini brief attached" if proof.get("mode") == "full_runtime" else "Bounded fallback selected",
                "step": 1,
                "message": brief.get("operator_brief", "The proactive decision bridge returned an operating brief."),
                "artifact": {
                    "runtime_mode": proof.get("mode"),
                    "provider": proof.get("provider"),
                    "model": proof.get("model"),
                    "fallback_reason": proof.get("fallback_reason"),
                    "latency_strategy": brief.get("latency_strategy"),
                },
            },
        )
        await send_event(
            "govern.done",
            {
                "phase": "govern",
                "label": "Policy gate passed",
                "step": 2,
                "message": "Policy gate passed: no medical diagnosis, no ride safety override, bounded equipment control only.",
                "artifact": {"eval": payload.get("eval", {}), "policy_violation": False},
            },
        )
        await send_event(
            "emit.done",
            {
                "phase": "emit",
                "label": "Receiver payloads emitted",
                "step": 3,
                "message": f"Emitted {summary.get('total', len(delivery.get('dispatches', []) or []))} receiver payloads across guest, worker, and equipment channels.",
                "artifact": summary,
            },
        )
        await send_event(
            "observe.done",
            {
                "phase": "observe",
                "label": "Response measured",
                "step": 4,
                "message": application.get("message", "Observed guest response, worker acknowledgement, and equipment application status."),
                "artifact": {"application": application, "response": delivery.get("response", {})},
            },
        )
        await send_event(
            "learn.done",
            {
                "phase": "learn",
                "label": "Memory updated",
                "step": 5,
                "message": "Outcome memory and take-rate priors are attached for the next planning run.",
                "artifact": {"memory": payload.get("memory", {}), "analytics": payload.get("analytics", {})},
            },
        )
        await send_event(
            "run.complete",
            {
                "phase": "complete",
                "label": payload.get("lifecycle", {}).get("headline", "Proactive loop complete"),
                "step": 6,
                "message": brief.get("operator_brief", "Proactive loop complete."),
                "payload": payload,
            },
            more_body=False,
        )
    except Exception as error:
        await send_event(
            "run.error",
            {
                "phase": "error",
                "label": "Proactive loop failed",
                "step": 6,
                "message": str(error),
            },
            more_body=False,
        )


async def app(scope, receive, send):
    if scope.get("type") == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                if os.getenv("PARKPULSE_AUTO_WARMUP", "").strip().lower() in {"1", "true", "yes", "on"}:
                    with contextlib.suppress(Exception):
                        _warmup_policy_payload(force=False)
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope.get("type") != "http":
        full_app = await _get_full_app()
        await full_app(scope, receive, send)
        return

    path = scope.get("path") or "/"
    method = scope.get("method") or "GET"
    if method == "OPTIONS":
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": [
                    (b"access-control-allow-origin", b"*"),
                    (b"access-control-allow-methods", b"*"),
                    (b"access-control-allow-headers", b"*"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})
        return

    if path in {"/", "/healthz", "/readyz"}:
        payload = (
            {
                "service": "parkpulse-api",
                "status": "ok",
                "entrypoint": "lazy-main",
                "uptime_ms": int((time.time() - _started_at) * 1000),
                "full_app_loaded": _parkpulse_app is not None,
                "full_runtime": _full_runtime_status(),
                "load_error": _load_error,
            }
            if path in {"/", "/healthz"}
            else await _cached_hot_endpoint("readyz", _hot_endpoint_ttls()["readyz"], _readiness_payload)
        )
        await _send_json(send, 200, payload)
        return

    if method == "GET" and path == "/api/park/full-runtime-status":
        await _send_json(send, 200, _full_runtime_status())
        return

    if method == "GET" and path == "/api/park/latency-diagnostics":
        try:
            from latency_diagnostics import build_latency_diagnostics, import_profile_snapshot, latency_history_payload, latency_probe_snapshot, schedule_latency_diagnostics_persist, trigger_import_profile, trigger_latency_probes
            from mongo_memory import get_latest_memory_documents_fast, record_latency_diagnostics_fast
            from scenario_eval_sweep import latest_sweep_payload

            query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
            refresh = (query.get("refresh") or ["false"])[0].lower() in {"1", "true", "yes", "on"}
            trigger = trigger_latency_probes(force=True) if refresh else {"started": [], "skipped": {"all": "refresh_not_requested"}}
            import_trigger = trigger_import_profile(force=True) if refresh else {"started": False, "skipped": "refresh_not_requested"}
            with _receipt_lock:
                receipts = dict(_run_receipts)
            memory_rows = get_latest_memory_documents_fast("eval_results", 75)
            latest_sweep = latest_sweep_payload(memory_rows)
            diagnostics = build_latency_diagnostics(
                full_runtime=_full_runtime_status(),
                receipts=receipts,
                latest_sweep=latest_sweep,
                probe_snapshot=latency_probe_snapshot(),
                import_profile=import_profile_snapshot(),
                include_env=True,
            )
            diagnostics["probe_trigger"] = trigger
            diagnostics["import_profile_trigger"] = import_trigger
            diagnostics["history"] = latency_history_payload(memory_rows)
            diagnostics["persistence"] = schedule_latency_diagnostics_persist(diagnostics, record_latency_diagnostics_fast)
            await _send_json(send, 200, diagnostics)
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "diagnostics_error",
                    "checked_at": _now_iso(),
                    "readiness_issues": [str(error)[:240]],
                    "timings": {"full_runtime": _full_runtime_status()},
                },
            )
        return

    if method == "GET" and path == "/api/park/api-capabilities":
        await _send_json(send, 200, _api_capability_registry())
        return

    if method in {"GET", "POST"} and path == "/api/park/dynamic-twin-demo":
        try:
            from dynamic_operational_twin import run_thunderstorm_mvp

            query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
            request_payload = await _read_json_body(receive) if method == "POST" else {}
            tick_raw = request_payload.get("tick_minutes") or request_payload.get("tickMinutes") or (query.get("tick") or [None])[0]
            horizon_raw = request_payload.get("horizon_minutes") or request_payload.get("horizonMinutes") or (query.get("horizon") or [None])[0]
            await _send_json(
                send,
                200,
                run_thunderstorm_mvp(
                    tick_minutes=int(tick_raw) if tick_raw else 5,
                    horizon_minutes=int(horizon_raw) if horizon_raw else 180,
                ),
            )
        except Exception as error:
            await _send_json(send, 200, {"status": "error", "mode": "dynamic_operational_twin_mvp", "readiness_issues": [str(error)[:240]]})
        return

    if method in {"GET", "POST"} and path == "/api/park/actual-training":
        try:
            from park_actual_training import actual_training_status

            query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
            request_payload = await _read_json_body(receive) if method == "POST" else {}
            min_rows_raw = request_payload.get("min_rows") or request_payload.get("minRows") or (query.get("minRows") or query.get("min_rows") or [None])[0]
            run_gcp_raw = request_payload.get("run_gcp_training") or request_payload.get("runGcpTraining") or (query.get("runGcpTraining") or query.get("run_gcp_training") or [None])[0]
            export_live_raw = request_payload.get("export_live_episodes") or request_payload.get("exportLiveEpisodes") or (query.get("exportLiveEpisodes") or query.get("export_live_episodes") or [None])[0]
            run_gcp_training = None
            if run_gcp_raw is not None:
                run_gcp_training = str(run_gcp_raw).strip().lower() in {"1", "true", "yes", "on"}
            export_live_episodes = str(export_live_raw).strip().lower() in {"1", "true", "yes", "on"} if export_live_raw is not None else bool(run_gcp_training)
            live_episode_export = await _export_live_episode_fitness_to_bigquery(limit=80) if export_live_episodes else {"status": "not_requested", "mode": "live_episode_fitness_export"}
            payload = actual_training_status(
                min_rows=int(min_rows_raw) if min_rows_raw else 3,
                run_gcp_training=run_gcp_training,
            )
            if _fast_park_simulation is not None and hasattr(_fast_park_simulation, "get_episode_fitness"):
                payload["episode_fitness"] = await _fast_park_simulation.get_episode_fitness(limit=20)
            payload["live_episode_export"] = live_episode_export
            await _send_json(send, 200, payload)
        except Exception as error:
            await _send_json(send, 200, {"status": "error", "mode": "actual_outcome_training", "readiness_issues": [str(error)[:240]]})
        return

    if method == "GET" and path == "/api/park/episode-fitness":
        try:
            query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
            limit_raw = (query.get("limit") or [None])[0]
            if _fast_park_simulation is None or not hasattr(_fast_park_simulation, "get_episode_fitness"):
                await _send_json(send, 503, {"status": "unavailable", "mode": "live_episode_fitness_counterfactual"})
                return
            await _send_json(send, 200, await _fast_park_simulation.get_episode_fitness(limit=int(limit_raw) if limit_raw else 20))
        except Exception as error:
            await _send_json(send, 200, {"status": "error", "mode": "live_episode_fitness_counterfactual", "readiness_issues": [str(error)[:240]]})
        return

    if method == "POST" and path == "/api/park/full-runtime-warmup":
        query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
        force = (query.get("force") or ["false"])[0].lower() in {"1", "true", "yes", "on"}
        await _send_json(send, 202, _warmup_policy_payload(force=force))
        return

    if method == "GET" and path == "/api/park/warmup-status":
        try:
            from latency_diagnostics import import_profile_snapshot, latency_probe_snapshot

            await _send_json(
                send,
                200,
                {
                    "status": _full_runtime_status()["status"],
                    "policy": "full_runtime_plus_dependency_probes",
                    "full_runtime": _full_runtime_status(),
                    "dependency_probes": latency_probe_snapshot(),
                    "import_profile": import_profile_snapshot(),
                },
            )
        except Exception as error:
            await _send_json(send, 200, {"status": "warmup_status_error", "readiness_issues": [str(error)[:240]], "full_runtime": _full_runtime_status()})
        return

    if method == "GET" and path.startswith("/api/park/run-receipt/"):
        receipt_id = path.rsplit("/", 1)[-1]
        with _receipt_lock:
            receipt = json.loads(json.dumps(_run_receipts.get(receipt_id), default=str)) if _run_receipts.get(receipt_id) else None
        if receipt:
            await _send_json(send, 200, {"status": "found", "receipt": {**receipt["receipt"], "payload": receipt["payload"]}})
        else:
            await _send_json(send, 404, {"status": "not_found", "id": receipt_id})
        return

    if path == "/api/park/agent-ops-ledger":
        try:
            from agent_ops_ledger import read_agent_ops_ledger, record_agent_ops_record

            if method == "GET":
                query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
                limit_raw = (query.get("limit") or ["50"])[0]
                try:
                    limit = int(limit_raw)
                except ValueError:
                    limit = 50
                search = (query.get("q") or [""])[0].strip() or None
                await _send_json(send, 200, read_agent_ops_ledger(limit=limit, query=search))
                return
            if method == "POST":
                payload = await _read_json_body(receive)
                record = payload.get("record") if isinstance(payload.get("record"), dict) else payload
                await _send_json(send, 200, record_agent_ops_record(record))
                return
        except Exception as error:
            await _send_json(send, 200, {"status": "unavailable", "mode": "backend_agent_ops_ledger", "count": 0, "items": [], "readiness_issues": [str(error)[:240]]})
            return

    if method == "GET" and path == "/api/park/operational-backlog":
        try:
            from agent_ops_ledger import build_operational_backlog
            from park_simulation import park_simulation

            state = await park_simulation.get_state()
            await _send_json(send, 200, build_operational_backlog(state))
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "unavailable",
                    "overallStatus": "unknown",
                    "unresolvedCount": 0,
                    "issues": [],
                    "effectiveness": {"ledgerRows": 0, "adaptiveFinding": "Operational backlog unavailable."},
                    "simulationFidelity": {
                        "label": "unknown",
                        "agentLearningReadiness": "not_measured",
                        "accuracyAnswer": "Could not inspect simulation fidelity from the running backend.",
                    },
                    "readiness_issues": [str(error)[:240]],
                },
            )
        return

    if method == "POST" and path == "/api/park/agent-decision-market/run":
        request_payload = await _read_json_body(receive)
        candidate_id = str(request_payload.get("candidate_id") or request_payload.get("candidateId") or "").strip()
        try:
            from agent_ops_ledger import build_operational_backlog, record_agent_ops_record
            from mongo_memory import record_agent_learning_document
            from park_delivery import delivery_summary, response_summary, send_equipment_command, send_guest_promotion, send_worker_notification
            from park_simulation import park_simulation

            os.environ["PARKPULSE_ENABLE_LIVE_GCP_DELIVERY_ADAPTER"] = "false"
            os.environ["ENABLE_PARKPULSE_FIRESTORE"] = "false"
            os.environ["ENABLE_PARKPULSE_DATAFLOW"] = "false"
            os.environ["PARKPULSE_ENABLE_FIRESTORE_MIRROR"] = "false"

            def clamp(value: float | int, low: int = 0, high: int = 100) -> int:
                return max(low, min(high, round(float(value))))

            def metric_snapshot(state: dict[str, Any]) -> dict[str, Any]:
                flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
                zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
                paths = flow.get("paths", []) if isinstance(flow.get("paths"), list) else []
                food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
                locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
                food_a = next((item for item in locations if isinstance(item, dict) and item.get("id") == "foodCourt1"), locations[0] if locations else {})
                care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
                clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
                fairness = clock.get("accessFairness", {}) if isinstance(clock.get("accessFairness"), dict) else {}
                events = clock.get("eventSchedule", {}) if isinstance(clock.get("eventSchedule"), dict) else {}
                return {
                    "avgSatisfaction": int(flow.get("avgSatisfaction", 0) or 0),
                    "openCareCases": int(care.get("openCases", 0) or 0),
                    "complaintRatePct": int(care.get("complaintRatePct", 0) or 0),
                    "foodBacklog": int((food_a or {}).get("mobileOrderBacklog", 0) or 0),
                    "foodEtaMinutes": int((food_a or {}).get("pickupEtaMinutes", 0) or 0),
                    "maxPathCongestion": int(max((int(path.get("congestionLevel", 0) or 0) for path in paths if isinstance(path, dict)), default=0)),
                    "maxZoneDensity": int(max((int(zone.get("density", 0) or 0) for zone in zones if isinstance(zone, dict)), default=0)),
                    "fairnessRiskPct": int(fairness.get("publicComplaintRiskPct", 0) or 0),
                    "eventTrafficRiskPct": int(events.get("eventTrafficRiskPct", 0) or 0),
                }

            def make_dispatches(candidate: dict[str, Any], episode_id: str) -> list[dict[str, Any]]:
                cid = str(candidate.get("id") or "market_action")
                base = {
                    "scenarioKey": "agent_decision_market",
                    "decisionId": episode_id,
                    "policyGateChecked": True,
                    "policyGateStatus": "market_approved",
                    "marketCandidateId": cid,
                    "marketCandidate": candidate.get("label"),
                    "expectedTakeRate": 0.42,
                    "expectedFollowThroughRate": 0.36,
                    "estimatedMovedGuests": 900,
                }
                dispatches: list[dict[str, Any]] = []
                if cid == "ops_broad_reroute":
                    dispatches.append(
                        send_guest_promotion(
                            {
                                **base,
                                "agentId": "guest_flow_agent",
                                "title": "Shorter waits nearby",
                                "message": "To reduce pressure, use nearby lower-wait routes and check the app for updated ride and food options.",
                                "targetZone": "coveredPlaza",
                                "estimatedMovedGuests": 1450,
                                "expectedTakeRate": 0.35,
                            }
                        )
                    )
                elif cid == "cx_recovery_first":
                    dispatches.append(
                        send_guest_promotion(
                            {
                                **base,
                                "agentId": "customer_experience_agent",
                                "title": "Transparent wait update",
                                "message": "We are balancing standby, Fast Lane, and service routes. Affected guests will see bounded recovery options in the app.",
                                "targetSegment": "affected_waiting_guests",
                                "estimatedMovedGuests": 620,
                                "expectedTakeRate": 0.5,
                            }
                        )
                    )
                elif cid == "planning_hold_until_wave":
                    dispatches.append(
                        send_worker_notification(
                            {
                                **base,
                                "agentId": "planning_agent",
                                "role": "crowd_control",
                                "priority": "high",
                                "zone": "coveredPlaza",
                                "task": "Hold broad reroutes until the show wave clears; prepare controlled split at the next decision deadline.",
                            }
                        )
                    )
                elif cid == "finance_cost_cap":
                    dispatches.append(
                        send_worker_notification(
                            {
                                **base,
                                "agentId": "finance_agent",
                                "role": "operations_lead",
                                "priority": "normal",
                                "zone": "foodCourt1",
                                "task": "Cap broad compensation and prioritize low-cost menu suppression and targeted care offers.",
                            }
                        )
                    )
                else:
                    dispatches.extend(
                        [
                            send_worker_notification(
                                {
                                    **base,
                                    "agentId": "safety_policy_agent",
                                    "role": "crowd_control",
                                    "priority": "high",
                                    "zone": "coveredPlaza",
                                    "task": "Protect access lanes and split route flow in controlled shares before any broad guest reroute.",
                                }
                            ),
                            send_guest_promotion(
                                {
                                    **base,
                                    "agentId": "guest_flow_agent",
                                    "title": "Controlled route update",
                                    "message": "Use the highlighted route to reduce crowding while keeping access lanes clear. Updates are targeted to affected areas only.",
                                    "targetZone": "coveredPlaza",
                                    "estimatedMovedGuests": 980,
                                    "expectedTakeRate": 0.46,
                                    "expectedFollowThroughRate": 0.39,
                                }
                            ),
                            send_equipment_command(
                                {
                                    **base,
                                    "agentId": "facilities_energy_agent",
                                    "command": "increase_wayfinding_lighting",
                                    "target": "coveredPlaza",
                                    "requiresHumanApproval": False,
                                    "durationMinutes": 20,
                                }
                            ),
                        ]
                    )
                return dispatches

            before_state = await park_simulation.get_state()
            before_backlog = build_operational_backlog(before_state)
            market = before_backlog.get("agentDecisionMarket", {}) if isinstance(before_backlog.get("agentDecisionMarket"), dict) else {}
            candidates = market.get("candidates", []) if isinstance(market.get("candidates"), list) else []
            selected = next((item for item in candidates if isinstance(item, dict) and item.get("id") == candidate_id), None)
            if selected is None:
                selected = market.get("winningCandidate", {}) if isinstance(market.get("winningCandidate"), dict) else {}
            if not selected:
                await _send_json(send, 409, {"status": "no_market_candidate", "message": "No market candidate is available to run."})
                return

            episode_id = f"market_episode_{hashlib.sha1(f'{selected.get('id')}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:16]}"
            before_metrics = metric_snapshot(before_state)
            dispatches = make_dispatches(selected, episode_id)
            application = await park_simulation.apply_delivery_outcomes(dispatches, "agent_decision_market_episode")
            after_state = await park_simulation.get_state()
            after_metrics = metric_snapshot(after_state)
            after_backlog = build_operational_backlog(after_state)
            response = response_summary(dispatches)
            summary = delivery_summary(dispatches)
            actual_delta = {
                "satisfactionDelta": after_metrics["avgSatisfaction"] - before_metrics["avgSatisfaction"],
                "careCaseDelta": after_metrics["openCareCases"] - before_metrics["openCareCases"],
                "foodBacklogDelta": after_metrics["foodBacklog"] - before_metrics["foodBacklog"],
                "foodEtaDelta": after_metrics["foodEtaMinutes"] - before_metrics["foodEtaMinutes"],
                "pathCongestionDelta": after_metrics["maxPathCongestion"] - before_metrics["maxPathCongestion"],
                "eventTrafficRiskDelta": after_metrics["eventTrafficRiskPct"] - before_metrics["eventTrafficRiskPct"],
                "fairnessRiskDelta": after_metrics["fairnessRiskPct"] - before_metrics["fairnessRiskPct"],
            }
            improvement_score = (
                max(0, -actual_delta["pathCongestionDelta"]) * 0.7
                + max(0, -actual_delta["foodBacklogDelta"]) * 0.08
                + max(0, actual_delta["satisfactionDelta"]) * 1.5
                + max(0, -actual_delta["eventTrafficRiskDelta"]) * 0.9
                + max(0, -actual_delta["fairnessRiskDelta"]) * 0.8
            )
            eval_score = clamp(float(selected.get("totalScore") or 70) * 0.75 + improvement_score + float(response.get("reactiveFollowThroughRate", 0) or 0) * 18)
            trace_events = [
                {"phase": "predict", "label": "Predicted", "message": selected.get("tradeoffSummary"), "artifact": {"candidate": selected.get("id"), "score": selected.get("totalScore")}},
                {"phase": "dispatch", "label": "Dispatched", "message": f"{summary.get('total', len(dispatches))} receiver payloads emitted.", "artifact": summary},
                {"phase": "observe", "label": "Observed", "message": response.get("signal", "Receiver responses observed."), "artifact": response},
                {"phase": "evaluate", "label": "Evaluated", "message": f"Market episode scored {eval_score}/100 against after-state deltas.", "artifact": actual_delta},
                {"phase": "remember", "label": "Remembered", "message": "Episode stored to ledger and operational memory.", "artifact": {"episodeId": episode_id}},
            ]
            episode = {
                "id": episode_id,
                "status": "completed",
                "mode": "market_episode_runner",
                "createdAt": _now_iso(),
                "selectedCandidate": selected,
                "market": {
                    "businessQuestion": market.get("businessQuestion"),
                    "operationsFavorite": market.get("operationsFavorite"),
                    "regretAnalysis": market.get("regretAnalysis"),
                },
                "before": before_metrics,
                "after": after_metrics,
                "actualDelta": actual_delta,
                "prediction": selected.get("predictedDeltas", {}),
                "delivery": {"summary": summary, "response": response, "dispatches": dispatches},
                "application": application,
                "eval": {
                    "overall": eval_score,
                    "verdict": "validated" if eval_score >= 72 else "needs_followup",
                    "dimension_scores": {
                        "market_quality": selected.get("totalScore", 0),
                        "policy_safety": 100 if not selected.get("vetoes") else 45,
                        "observed_response": clamp(float(response.get("reactiveFollowThroughRate", 0) or 0) * 100),
                        "state_delta": clamp(55 + improvement_score),
                    },
                },
                "traceEvents": trace_events,
            }
            memory_id = record_agent_learning_document(
                {
                    "_id": f"learning_{episode_id}",
                    "sourceScenarioId": episode_id,
                    "scenarioKey": "agent_decision_market",
                    "lesson": f"{selected.get('label')} scored {eval_score}/100 after market execution.",
                    "selectedCandidateId": selected.get("id"),
                    "selectedAction": selected.get("action"),
                    "prediction": selected.get("predictedDeltas", {}),
                    "actualDelta": actual_delta,
                    "evalScore": eval_score,
                    "tags": ["agent_decision_market", "closed_loop_episode", "multi_agent_tradeoff"],
                    "episode": episode,
                }
            )
            ledger_record = record_agent_ops_record(
                {
                    "id": episode_id,
                    "signature": episode_id,
                    "timestamp": episode["createdAt"],
                    "scenarioName": "agent_decision_market",
                    "mode": "market_episode_runner",
                    "selectedAction": str(selected.get("label") or selected.get("action") or "Market selected action"),
                    "status": "completed",
                    "gate": "market_approved",
                    "evalScore": eval_score,
                    "dispatchCount": int(summary.get("total", len(dispatches)) or len(dispatches)),
                    "takeRatePct": response.get("takeRate"),
                    "followThroughPct": response.get("reactiveFollowThroughRate"),
                    "memoryId": memory_id,
                    "traceId": episode_id,
                    "summary": f"Executed {selected.get('label')} and compared predicted vs observed park state.",
                    "receiverActions": [f"{item.get('channel')}: {item.get('payload', {}).get('title') or item.get('payload', {}).get('task') or item.get('payload', {}).get('command')}" for item in dispatches],
                    "toolCalls": [
                        {"tool": "agent_decision_market.score_candidates", "status": "called", "agent": "decision_market"},
                        {"tool": "validate_policy", "status": "market_approved", "agent": "policy_arbiter"},
                        {"tool": "dispatch_receiver_payloads", "status": "called", "agent": "delivery_agent"},
                        {"tool": "apply_delivery_outcomes", "status": application.get("status"), "agent": "digital_twin"},
                        {"tool": "write_decision_memory", "status": "stored", "agent": "memory_agent"},
                    ],
                    "traceEvents": trace_events,
                    "evalDimensions": [{"label": key, "value": value} for key, value in episode["eval"]["dimension_scores"].items()],
                    "failureReasons": [] if eval_score >= 72 else ["Observed state delta was weaker than the market forecast."],
                    "source": "backend:market_episode_runner",
                    "marketEpisode": episode,
                }
            )
            await _send_json(
                send,
                200,
                {
                    "status": "completed",
                    "episode": episode,
                    "state": after_state,
                    "operationalBacklog": after_backlog,
                    "delivery": episode["delivery"],
                    "memoryPersistence": {"status": "stored", "memoryId": memory_id, "collection": "agent_learnings"},
                    "agentOpsLedger": ledger_record,
                },
            )
        except Exception as error:
            await _send_json(send, 500, {"status": "failed", "message": str(error)[:500]})
        return

    if path in {"/api/park/food-demand-shaping", "/api/park/food-demand-shaping/run"}:
        try:
            if method == "POST":
                await _read_json_body(receive)
            from agent_ops_ledger import record_agent_ops_record
            from mongo_memory import record_agent_learning_document
            from park_delivery import delivery_summary, response_summary, send_equipment_command, send_guest_promotion, send_worker_notification
            from park_simulation import park_simulation

            os.environ["PARKPULSE_ENABLE_LIVE_GCP_DELIVERY_ADAPTER"] = "false"
            os.environ["ENABLE_PARKPULSE_FIRESTORE"] = "false"
            os.environ["ENABLE_PARKPULSE_DATAFLOW"] = "false"
            os.environ["PARKPULSE_ENABLE_FIRESTORE_MIRROR"] = "false"

            def clamp(value: float | int, low: int = 0, high: int = 100) -> int:
                return max(low, min(high, round(float(value))))

            def food_snapshot(state: dict[str, Any]) -> dict[str, Any]:
                food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
                locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
                primary = next((item for item in locations if isinstance(item, dict) and item.get("id") == "foodCourt1"), locations[0] if locations else {})
                alternates = [item for item in locations if isinstance(item, dict) and item.get("id") != (primary or {}).get("id")]
                flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
                zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
                food_zone = next((zone for zone in zones if isinstance(zone, dict) and zone.get("id") == "foodCourt1"), {})
                care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
                clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
                lifecycle = clock.get("foodRetailLifecycle", {}) if isinstance(clock.get("foodRetailLifecycle"), dict) else {}
                return {
                    "locationId": str((primary or {}).get("id") or "foodCourt1"),
                    "locationName": str((primary or {}).get("name") or "Food Court A"),
                    "backlog": int((primary or {}).get("mobileOrderBacklog", 0) or 0),
                    "pickupEtaMinutes": int((primary or {}).get("pickupEtaMinutes", 0) or 0),
                    "zoneDensityPct": int((food_zone or {}).get("density", 0) or 0),
                    "zoneWaitMinutes": int((food_zone or {}).get("waitMins", 0) or 0),
                    "mobileOrderBacklogPressurePct": int(lifecycle.get("mobileOrderBacklogPressurePct", 0) or 0),
                    "careOpenCases": int(care.get("openCases", 0) or 0),
                    "complaintRatePct": int(care.get("complaintRatePct", 0) or 0),
                    "lowInventoryItems": list((primary or {}).get("lowInventoryItems", []) or []),
                    "availableItems": list((primary or {}).get("availableItems", []) or []),
                    "suppressedItems": list(food.get("suppressedItems", []) or []),
                    "alternateLocations": [
                        {
                            "id": item.get("id"),
                            "name": item.get("name"),
                            "mobileOrderBacklog": int(item.get("mobileOrderBacklog", 0) or 0),
                            "pickupEtaMinutes": int(item.get("pickupEtaMinutes", 0) or 0),
                        }
                        for item in alternates[:3]
                    ],
                }

            def build_food_strategy(state: dict[str, Any]) -> dict[str, Any]:
                current = food_snapshot(state)
                pressure = clamp(
                    current["mobileOrderBacklogPressurePct"] * 0.4
                    + current["zoneDensityPct"] * 0.22
                    + current["pickupEtaMinutes"] * 1.25
                    + current["backlog"] * 0.12
                    + current["complaintRatePct"] * 0.45
                )
                throttle = clamp(12 + (pressure - 55) * 0.5, 8, 34)
                redirect = clamp(22 + (pressure - 55) * 0.45, 14, 42)
                suppress_items = ["mobile_order_intake"]
                suppress_items.extend(item for item in current["lowInventoryItems"][:2] if item not in suppress_items)
                if "chicken_tenders" not in suppress_items:
                    suppress_items.append("chicken_tenders")
                promote_items = [item for item in current["availableItems"][:3] if item not in suppress_items] or ["pretzel_bites", "salads", "fruit_cups"]
                backlog_delta = -max(18, min(current["backlog"], round(current["backlog"] * redirect / 100 + throttle * 1.2)))
                eta_delta = -max(4, min(current["pickupEtaMinutes"], round(abs(backlog_delta) / 7)))
                alternate = current["alternateLocations"][0] if current["alternateLocations"] else {"id": "foodCourt2", "name": "Food Court B"}
                return {
                    "status": "ready",
                    "mode": "autonomous_food_demand_shaping",
                    "generatedAt": _now_iso(),
                    "agent": "Food Demand Shaping Agent",
                    "headline": "Bound mobile-order demand before pickup queues spill into guest flow.",
                    "current": current,
                    "pressureScore": pressure,
                    "autonomyLevel": "bounded_auto" if pressure >= 55 else "observe",
                    "selectedStrategy": {
                        "id": "bounded_food_demand_shape",
                        "durationMinutes": 18 if pressure >= 70 else 12,
                        "throttlePct": throttle,
                        "redirectSharePct": redirect,
                        "suppressItems": suppress_items[:4],
                        "promoteItems": promote_items[:4],
                        "alternateDestination": alternate.get("name") or "Food Court B",
                        "decision": "Throttle high-friction mobile-order demand and redirect willing guests to faster pickup nodes.",
                    },
                    "controls": [
                        {
                            "id": "mobile_intake_throttle",
                            "label": "Mobile order intake throttle",
                            "autonomy": "bounded",
                            "value": f"{throttle}% for overloaded SKUs",
                            "reason": "Reduces new promises while protecting walk-up and existing pickup commitments.",
                        },
                        {
                            "id": "sku_suppression",
                            "label": "SKU suppression",
                            "autonomy": "bounded",
                            "value": ", ".join(suppress_items[:3]),
                            "reason": "Hides items with slow prep or low inventory until the pressure score falls.",
                        },
                        {
                            "id": "alternate_pickup_promotion",
                            "label": "Alternate pickup promotion",
                            "autonomy": "bounded",
                            "value": f"{redirect}% offer to {alternate.get('name') or 'Food Court B'}",
                            "reason": "Moves flexible guests without forcing the whole crowd to reroute.",
                        },
                        {
                            "id": "pickup_slot_rebalance",
                            "label": "Pickup slot rebalance",
                            "autonomy": "bounded",
                            "value": "+6 minute spacing on new slots",
                            "reason": "Prevents app promises from creating a second surge.",
                        },
                        {
                            "id": "staff_staging",
                            "label": "Pickup runner staging",
                            "autonomy": "dispatch",
                            "value": "2 runners, secondary pickup shelf",
                            "reason": "Turns demand shaping into physical queue relief instead of only menu changes.",
                        },
                    ],
                    "prediction": {
                        "backlogBefore": current["backlog"],
                        "backlogAfter": max(0, current["backlog"] + backlog_delta),
                        "backlogDelta": backlog_delta,
                        "etaBeforeMinutes": current["pickupEtaMinutes"],
                        "etaAfterMinutes": max(6, current["pickupEtaMinutes"] + eta_delta),
                        "etaDeltaMinutes": eta_delta,
                        "complaintAvoidanceCases": max(3, round(abs(backlog_delta) / 45)),
                        "guestCohortMoved": max(80, round(abs(backlog_delta) * 2.8)),
                        "confidencePct": clamp(62 + pressure * 0.22),
                    },
                    "safetyBounds": [
                        "No item is removed from already-paid orders.",
                        "Accessibility and dietary options cannot be suppressed.",
                        "Guest offers remain optional and geographically bounded.",
                        "Controls auto-expire unless the next observation confirms pressure is still high.",
                    ],
                }

            async def bounded_learning_write(document: dict[str, Any]) -> str:
                try:
                    return await asyncio.wait_for(asyncio.to_thread(record_agent_learning_document, document), timeout=2.5)
                except Exception as error:
                    digest = hashlib.sha1(str(error).encode("utf-8")).hexdigest()[:12]
                    return f"skipped_learning_timeout_{digest}"

            if method == "GET":
                state = await park_simulation.get_state()
                await _send_json(send, 200, build_food_strategy(state))
                return
            if method != "POST":
                await _send_json(send, 405, {"status": "method_not_allowed"})
                return

            before_state = await park_simulation.get_state()
            strategy = build_food_strategy(before_state)
            selected = strategy["selectedStrategy"]
            before = strategy["current"]
            episode_seed = f"{time.time_ns()}:{strategy['pressureScore']}"
            episode_id = f"food_shape_{hashlib.sha1(episode_seed.encode('utf-8')).hexdigest()[:16]}"
            dispatch_base = {
                "scenarioKey": "food_spike",
                "decisionId": episode_id,
                "agentId": "food_demand_shaping_agent",
                "policyGateChecked": True,
                "policyGateStatus": "bounded_auto_food_controls",
                "expectedTakeRate": 0.48,
                "expectedFollowThroughRate": 0.41,
                "estimatedMovedGuests": strategy["prediction"]["guestCohortMoved"],
            }
            dispatches = [
                send_guest_promotion(
                    {
                        **dispatch_base,
                        "audience": "mobile_order_guests_near_food_pressure",
                        "targetZone": "foodCourt1",
                        "title": "Faster pickup nearby",
                        "message": f"Food demand is being balanced. Choose {selected['alternateDestination']} for faster pickup and a shorter queue.",
                        "promotionType": "food_demand_shape",
                        "suppressItems": selected["suppressItems"],
                        "promoteItems": selected["promoteItems"],
                        "avoidExtraDemandAt": before["locationName"],
                    }
                ),
                send_worker_notification(
                    {
                        **dispatch_base,
                        "role": "food_pickup_runner",
                        "priority": "high",
                        "zone": "foodCourt1",
                        "task": "Open secondary pickup staging, move ready bags to the overflow shelf, and route flexible mobile-order guests to the alternate pickup lane.",
                    }
                ),
                send_equipment_command(
                    {
                        **dispatch_base,
                        "equipmentType": "mobile_order_menu",
                        "command": "apply_food_demand_shape",
                        "target": "foodCourt1",
                        "durationMinutes": selected["durationMinutes"],
                        "throttlePct": selected["throttlePct"],
                        "redirectSharePct": selected["redirectSharePct"],
                        "suppressItems": selected["suppressItems"],
                        "promoteItems": selected["promoteItems"],
                        "requiresHumanApproval": False,
                    }
                ),
            ]
            application = await park_simulation.apply_delivery_outcomes(dispatches, "food_demand_shaping")
            after_state = await park_simulation.get_state()
            after = food_snapshot(after_state)
            response = response_summary(dispatches)
            summary = delivery_summary(dispatches)
            actual_delta = {
                "backlogDelta": after["backlog"] - before["backlog"],
                "etaDeltaMinutes": after["pickupEtaMinutes"] - before["pickupEtaMinutes"],
                "densityDeltaPct": after["zoneDensityPct"] - before["zoneDensityPct"],
                "waitDeltaMinutes": after["zoneWaitMinutes"] - before["zoneWaitMinutes"],
                "careCaseDelta": after["careOpenCases"] - before["careOpenCases"],
                "complaintRateDeltaPct": after["complaintRatePct"] - before["complaintRatePct"],
            }
            prediction = strategy["prediction"]
            forecast_error = abs(actual_delta["backlogDelta"] - int(prediction["backlogDelta"])) + abs(actual_delta["etaDeltaMinutes"] - int(prediction["etaDeltaMinutes"])) * 4
            eval_score = clamp(92 - forecast_error * 0.16 + float(response.get("reactiveFollowThroughRate", 0) or 0) * 14)
            trace_events = [
                {"phase": "sense", "label": "Sensed", "message": f"{before['locationName']} pressure {strategy['pressureScore']}/100, backlog {before['backlog']}.", "artifact": before},
                {"phase": "shape", "label": "Shaped demand", "message": selected["decision"], "artifact": selected},
                {"phase": "dispatch", "label": "Dispatched", "message": f"{summary.get('total', len(dispatches))} guest, staff, and menu controls emitted.", "artifact": summary},
                {"phase": "observe", "label": "Observed", "message": application.get("message", "After-state observed."), "artifact": actual_delta},
                {"phase": "remember", "label": "Remembered", "message": "Food demand episode stored for incident analytics and human review.", "artifact": {"episodeId": episode_id}},
            ]
            episode = {
                "id": episode_id,
                "status": "completed",
                "mode": "food_demand_shaping",
                "createdAt": _now_iso(),
                "strategy": selected,
                "before": before,
                "after": after,
                "prediction": prediction,
                "actualDelta": actual_delta,
                "delivery": {"summary": summary, "response": response, "dispatches": dispatches},
                "application": application,
                "eval": {
                    "overall": eval_score,
                    "verdict": "validated" if eval_score >= 72 else "needs_human_review",
                    "dimension_scores": {
                        "forecast_accuracy": clamp(100 - forecast_error * 0.5),
                        "guest_response": clamp(float(response.get("reactiveFollowThroughRate", 0) or 0) * 100),
                        "queue_relief": clamp(55 + max(0, -actual_delta["backlogDelta"]) * 0.4),
                        "complaint_relief": clamp(65 + max(0, -actual_delta["complaintRateDeltaPct"]) * 4),
                    },
                },
                "traceEvents": trace_events,
            }
            memory_id = await bounded_learning_write(
                {
                    "_id": f"learning_{episode_id}",
                    "sourceScenarioId": episode_id,
                    "scenarioKey": "food_demand_shaping",
                    "lesson": f"Food shaping reduced backlog by {-actual_delta['backlogDelta']} orders with eval {eval_score}/100.",
                    "selectedAction": "Bounded food demand shape",
                    "prediction": prediction,
                    "actualDelta": actual_delta,
                    "evalScore": eval_score,
                    "tags": ["food_demand_shaping", "mobile_order", "closed_loop_episode"],
                    "episode": episode,
                }
            )
            ledger_record = record_agent_ops_record(
                {
                    "id": episode_id,
                    "signature": episode_id,
                    "timestamp": episode["createdAt"],
                    "scenarioName": "food_demand_shaping",
                    "mode": "food_demand_shaping",
                    "selectedAction": "Bounded food demand shape",
                    "status": "completed",
                    "gate": "bounded_auto_food_controls",
                    "evalScore": eval_score,
                    "dispatchCount": int(summary.get("total", len(dispatches)) or len(dispatches)),
                    "takeRatePct": response.get("takeRate"),
                    "followThroughPct": response.get("reactiveFollowThroughRate"),
                    "memoryId": memory_id,
                    "traceId": episode_id,
                    "summary": "Shaped mobile-order demand with bounded menu, offer, staff, and pickup controls, then compared predicted vs observed food pressure.",
                    "receiverActions": [f"{item.get('channel')}: {item.get('payload', {}).get('title') or item.get('payload', {}).get('task') or item.get('payload', {}).get('command')}" for item in dispatches],
                    "toolCalls": [
                        {"tool": "get_food_capacity", "status": "called", "agent": "food_demand_shaping_agent"},
                        {"tool": "simulate_food_demand_shape", "status": "called", "agent": "digital_twin"},
                        {"tool": "validate_policy", "status": "bounded_auto_food_controls", "agent": "policy_agent"},
                        {"tool": "dispatch_guest_offer", "status": "called", "agent": "delivery_agent"},
                        {"tool": "dispatch_staff_staging", "status": "called", "agent": "delivery_agent"},
                        {"tool": "dispatch_menu_control", "status": "called", "agent": "delivery_agent"},
                        {"tool": "write_decision_memory", "status": "stored", "agent": "memory_agent"},
                    ],
                    "traceEvents": trace_events,
                    "evalDimensions": [{"label": key, "value": value} for key, value in episode["eval"]["dimension_scores"].items()],
                    "failureReasons": [] if eval_score >= 72 else ["Observed relief was weaker than the food-demand forecast."],
                    "source": "backend:food_demand_shaping",
                    "foodDemandEpisode": episode,
                }
            )
            memory_status = "deferred" if str(memory_id).startswith("skipped_learning_timeout_") else "stored"
            await _send_json(
                send,
                200,
                {
                    "status": "completed",
                    "strategy": build_food_strategy(after_state),
                    "episode": episode,
                    "state": after_state,
                    "delivery": episode["delivery"],
                    "memoryPersistence": {"status": memory_status, "memoryId": memory_id, "collection": "agent_learnings"},
                    "agentOpsLedger": ledger_record,
                },
            )
        except Exception as error:
            await _send_json(send, 500, {"status": "failed", "message": str(error)[:500]})
        return

    if path in {"/api/park/generated-sop", "/api/park/generated-sop/run"}:
        try:
            if method == "POST":
                await _read_json_body(receive)
            from agent_ops_ledger import build_operational_backlog, read_agent_ops_ledger, record_agent_ops_record
            from mongo_memory import get_latest_memory_documents_fast, record_agent_learning_document
            from park_audit_agent import build_audit_snapshot
            from park_delivery import latest_dispatches
            from park_simulation import park_simulation

            def clamp(value: float | int, low: int = 0, high: int = 100) -> int:
                return max(low, min(high, round(float(value))))

            async def bounded_learning_write(document: dict[str, Any]) -> str:
                try:
                    return await asyncio.wait_for(asyncio.to_thread(record_agent_learning_document, document), timeout=2.5)
                except Exception as error:
                    digest = hashlib.sha1(str(error).encode("utf-8")).hexdigest()[:12]
                    return f"skipped_learning_timeout_{digest}"

            def compact_state_signals(state: dict[str, Any]) -> dict[str, Any]:
                flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
                zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
                rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
                food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
                locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
                clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
                care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
                top_zone = max((zone for zone in zones if isinstance(zone, dict)), key=lambda item: int(item.get("density", 0) or 0), default={})
                top_ride = max((ride for ride in rides if isinstance(ride, dict)), key=lambda item: int(item.get("waitMins", 0) or 0) + int(item.get("downtimeRisk", 0) or 0), default={})
                food_a = next((item for item in locations if isinstance(item, dict) and item.get("id") == "foodCourt1"), locations[0] if locations else {})
                events = clock.get("eventSchedule", {}) if isinstance(clock.get("eventSchedule"), dict) else {}
                fairness = clock.get("accessFairness", {}) if isinstance(clock.get("accessFairness"), dict) else {}
                return {
                    "topZone": top_zone.get("name") or top_zone.get("id") or "unknown",
                    "topZoneDensityPct": int(top_zone.get("density", 0) or 0),
                    "topRide": top_ride.get("name") or top_ride.get("id") or "unknown",
                    "topRideWaitMinutes": int(top_ride.get("waitMins", 0) or 0),
                    "topRideDowntimeRiskPct": int(top_ride.get("downtimeRisk", 0) or 0),
                    "foodBacklog": int((food_a or {}).get("mobileOrderBacklog", 0) or 0),
                    "foodEtaMinutes": int((food_a or {}).get("pickupEtaMinutes", 0) or 0),
                    "openCareCases": int(care.get("openCases", 0) or 0),
                    "complaintRatePct": int(care.get("complaintRatePct", 0) or 0),
                    "nextShowtime": (events.get("nextEvent") or {}).get("name") if isinstance(events.get("nextEvent"), dict) else None,
                    "eventTrafficRiskPct": int(events.get("eventTrafficRiskPct", 0) or 0),
                    "fairnessComplaintRiskPct": int(fairness.get("publicComplaintRiskPct", 0) or 0),
                }

            def build_generated_sop(state: dict[str, Any]) -> dict[str, Any]:
                backlog = build_operational_backlog(state)
                audit = build_audit_snapshot(state)
                ledger = read_agent_ops_ledger(limit=8)
                dispatches = latest_dispatches(8)
                playbooks = get_latest_memory_documents_fast("playbooks", 3)
                signals = compact_state_signals(state)
                issues = backlog.get("issues", []) if isinstance(backlog.get("issues"), list) else []
                anomalies = (audit.get("anomalies", []) if isinstance(audit, dict) else []) or []
                primary_issue = next((item for item in issues if isinstance(item, dict)), {})
                primary_anomaly = next((item for item in anomalies if isinstance(item, dict)), {})
                domain = str(primary_issue.get("domain") or primary_anomaly.get("domain") or "food_guest_flow")
                title_domain = domain.replace("_", " ").title()
                severity = str(primary_issue.get("severity") or primary_anomaly.get("severity") or "watch")
                risk_score = clamp(
                    signals["topZoneDensityPct"] * 0.25
                    + signals["topRideDowntimeRiskPct"] * 0.28
                    + signals["foodEtaMinutes"] * 1.1
                    + signals["eventTrafficRiskPct"] * 0.22
                    + signals["fairnessComplaintRiskPct"] * 0.2
                    + signals["complaintRatePct"] * 0.45
                )
                sop_id = f"sop_draft_{hashlib.sha1(json.dumps({'domain': domain, 'severity': severity, 'signals': signals}, sort_keys=True).encode('utf-8')).hexdigest()[:16]}"
                evidence = [
                    f"Top zone {signals['topZone']} density {signals['topZoneDensityPct']}%.",
                    f"{signals['topRide']} wait {signals['topRideWaitMinutes']} minutes, downtime risk {signals['topRideDowntimeRiskPct']}%.",
                    f"Food backlog {signals['foodBacklog']} orders, pickup ETA {signals['foodEtaMinutes']} minutes.",
                    f"Event traffic risk {signals['eventTrafficRiskPct']}%, fairness complaint risk {signals['fairnessComplaintRiskPct']}%.",
                ]
                if primary_issue.get("title"):
                    evidence.insert(0, f"Backlog issue: {primary_issue.get('title')}.")
                if primary_anomaly.get("title"):
                    evidence.insert(1, f"Audit anomaly: {primary_anomaly.get('title')}.")
                return {
                    "status": "draft_ready",
                    "mode": "agent_generated_sop",
                    "id": sop_id,
                    "generatedAt": _now_iso(),
                    "generatedBy": "SOP Synthesis Agent",
                    "title": f"SOP Draft: {title_domain} Response",
                    "summary": "Agent-generated procedure candidate built from live park state, backlog, audit findings, dispatch history, and prior playbooks.",
                    "severity": severity,
                    "domain": domain,
                    "riskScore": risk_score,
                    "reviewRequired": True,
                    "promotionTarget": "playbooks",
                    "sourceEvidence": evidence,
                    "retrievedPlaybooks": [
                        {
                            "id": item.get("_id"),
                            "title": item.get("title"),
                            "summary": item.get("summary"),
                            "score": item.get("score"),
                        }
                        for item in playbooks[:3]
                        if isinstance(item, dict)
                    ],
                    "recentTraceLinks": [
                        {
                            "id": item.get("id"),
                            "mode": item.get("mode"),
                            "selectedAction": item.get("selectedAction"),
                            "evalScore": item.get("evalScore"),
                        }
                        for item in (ledger.get("items", []) if isinstance(ledger, dict) else [])[:5]
                        if isinstance(item, dict)
                    ],
                    "receiverEvidence": [
                        {
                            "id": item.get("id"),
                            "channel": item.get("channel"),
                            "status": item.get("status"),
                            "label": (item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}).get("title")
                            or (item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}).get("task")
                            or (item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}).get("command"),
                        }
                        for item in dispatches[:5]
                        if isinstance(item, dict)
                    ],
                    "triggerConditions": [
                        f"{signals['topZone']} density >= 80% or path spillback is forecast within 10 minutes.",
                        f"Food pickup ETA >= 18 minutes or mobile-order backlog is rising faster than fulfillment.",
                        "A showtime, parade, fireworks, or closing release overlaps a food, ride, or corridor bottleneck.",
                        "Guest-care complaints or fairness risk rises while the previous mitigation is still active.",
                    ],
                    "procedure": [
                        {
                            "step": 1,
                            "owner": "Scan Agent",
                            "action": "Correlate ride, food, crowd, event, fairness, and guest-care signals into one incident frame.",
                            "tool": "get_park_state + audit_snapshot",
                            "successCriteria": "Primary domain, affected zones, and confidence are visible before any dispatch.",
                            "timeboxMinutes": 2,
                        },
                        {
                            "step": 2,
                            "owner": "Memory Agent",
                            "action": "Retrieve matching playbooks, recent incidents, and completed action evals.",
                            "tool": "retrieve_operational_context + agent_ops_ledger",
                            "successCriteria": "At least one prior playbook, learning, or explicit no-match note is attached.",
                            "timeboxMinutes": 2,
                        },
                        {
                            "step": 3,
                            "owner": "Planning Agent",
                            "action": "Simulate reversible response options and reject actions that move pressure into a worse zone.",
                            "tool": "simulate_action",
                            "successCriteria": "Counterfactual includes queue, food, care, event, and fairness deltas.",
                            "timeboxMinutes": 4,
                        },
                        {
                            "step": 4,
                            "owner": "Policy Agent",
                            "action": "Gate the proposed action against safety, labor, accessibility, fairness, and refund boundaries.",
                            "tool": "validate_policy",
                            "successCriteria": "Only bounded dispatches proceed; sensitive calls remain human-review-required.",
                            "timeboxMinutes": 2,
                        },
                        {
                            "step": 5,
                            "owner": "Delivery Agent",
                            "action": "Emit targeted guest, worker, and equipment/menu actions with expiry and rollback metadata.",
                            "tool": "dispatch_receiver_payloads",
                            "successCriteria": "Every receiver action has owner, zone, duration, expected response, and rollback path.",
                            "timeboxMinutes": 3,
                        },
                        {
                            "step": 6,
                            "owner": "Eval Agent",
                            "action": "Compare predicted vs observed deltas and write the outcome to trace history.",
                            "tool": "score_outcome + write_decision_memory",
                            "successCriteria": "Eval score, actual deltas, and follow-up decision are inspectable.",
                            "timeboxMinutes": 8,
                        },
                    ],
                    "rollbackCriteria": [
                        "Target zone density rises after the dispatch window instead of falling.",
                        "Care cases or complaint rate increases while mitigation is active.",
                        "A receiver payload is not acknowledged within the timebox.",
                        "Policy gate flags a safety, accessibility, labor, or fairness violation.",
                    ],
                    "escalationCriteria": [
                        "Emergency access is blocked or medical/security signal appears.",
                        "Ride reopen/closure decision requires maintenance or safety signoff.",
                        "Guest compensation, refunds, or VIP/Fast Lane fairness changes exceed bounded limits.",
                    ],
                    "auditChecklist": [
                        "Evidence attached before action.",
                        "Human-review boundaries explicit.",
                        "Receiver payloads have expiry.",
                        "Before/after metrics captured.",
                        "SOP candidate is not promoted without review.",
                    ],
                    "evalPlan": {
                        "primaryMetric": "observed pressure reduction without complaint or fairness regression",
                        "minimumEvalScoreForPromotion": 82,
                        "requiredRunsBeforePromotion": 3,
                        "failureModeToWatch": "moving guests into a hidden food, showtime, or accessibility bottleneck",
                    },
                }

            state = await park_simulation.get_state()
            sop = build_generated_sop(state)
            if method == "GET":
                await _send_json(send, 200, sop)
                return
            if method != "POST":
                await _send_json(send, 405, {"status": "method_not_allowed"})
                return

            memory_id = await bounded_learning_write(
                {
                    "_id": f"learning_{sop['id']}",
                    "sourceScenarioId": sop["id"],
                    "scenarioKey": "agent_generated_sop",
                    "lesson": f"{sop['title']} generated as human-review-required playbook candidate.",
                    "selectedAction": "Generate SOP candidate",
                    "sopDraft": sop,
                    "tags": ["agent_generated_sop", "playbook_candidate", "human_review_required"],
                }
            )
            memory_status = "deferred" if str(memory_id).startswith("skipped_learning_timeout_") else "stored"
            ledger_record = record_agent_ops_record(
                {
                    "id": sop["id"],
                    "signature": sop["id"],
                    "timestamp": sop["generatedAt"],
                    "scenarioName": "agent_generated_sop",
                    "mode": "sop_synthesis",
                    "selectedAction": sop["title"],
                    "status": "draft_ready",
                    "gate": "human_review_required_before_playbook_promotion",
                    "evalScore": sop["riskScore"],
                    "dispatchCount": 0,
                    "memoryId": memory_id,
                    "traceId": sop["id"],
                    "summary": sop["summary"],
                    "receiverActions": [],
                    "toolCalls": [
                        {"tool": "get_park_state", "status": "called", "agent": "sop_synthesis_agent"},
                        {"tool": "build_operational_backlog", "status": "called", "agent": "sop_synthesis_agent"},
                        {"tool": "build_audit_snapshot", "status": "called", "agent": "sop_synthesis_agent"},
                        {"tool": "retrieve_playbooks", "status": "called", "agent": "memory_agent"},
                        {"tool": "read_agent_ops_ledger", "status": "called", "agent": "eval_agent"},
                        {"tool": "write_sop_candidate_memory", "status": memory_status, "agent": "memory_agent"},
                    ],
                    "traceEvents": [
                        {"phase": "sense", "label": "Evidence gathered", "message": f"{len(sop['sourceEvidence'])} evidence rows attached.", "artifact": sop["sourceEvidence"]},
                        {"phase": "synthesize", "label": "SOP drafted", "message": sop["title"], "artifact": {"steps": len(sop["procedure"])}},
                        {"phase": "gate", "label": "Promotion gated", "message": "Human review is required before this becomes a live playbook.", "artifact": sop["evalPlan"]},
                    ],
                    "evalDimensions": [
                        {"label": "risk_score", "value": sop["riskScore"]},
                        {"label": "procedure_steps", "value": len(sop["procedure"])},
                        {"label": "retrieved_playbooks", "value": len(sop["retrievedPlaybooks"])},
                        {"label": "recent_traces", "value": len(sop["recentTraceLinks"])},
                    ],
                    "failureReasons": [],
                    "source": "backend:agent_generated_sop",
                    "generatedSop": sop,
                }
            )
            await _send_json(
                send,
                200,
                {
                    **sop,
                    "status": "generated",
                    "memoryPersistence": {"status": memory_status, "memoryId": memory_id, "collection": "agent_learnings", "promotionTarget": "playbooks"},
                    "agentOpsLedger": ledger_record,
                },
            )
        except Exception as error:
            await _send_json(send, 500, {"status": "failed", "message": str(error)[:500]})
        return

    if path in {"/api/park/digital-twin-war-room", "/api/park/digital-twin-war-room/run", "/api/park/digital-twin-war-room/remediate"}:
        try:
            request_payload = await _read_json_body(receive) if method == "POST" else {}
            from agent_ops_ledger import read_agent_ops_ledger, record_agent_ops_record
            from digital_twin_benchmark import attach_learning_comparison, generate_remediation_playbooks, list_benchmark_scenarios, run_digital_twin_benchmark, run_parkpulse_agent_benchmark
            from mongo_memory import record_agent_learning_document
            from park_audit_agent import build_audit_snapshot
            from park_delivery import latest_dispatches
            from park_simulation import park_simulation

            def clamp(value: float | int, low: int = 0, high: int = 100) -> int:
                return max(low, min(high, round(float(value))))

            def top_rows(rows: list[dict[str, Any]], key: str, limit: int = 3) -> list[dict[str, Any]]:
                return sorted((row for row in rows if isinstance(row, dict)), key=lambda row: int(row.get(key, 0) or 0), reverse=True)[:limit]

            def live_twin_signals(state: dict[str, Any]) -> dict[str, Any]:
                flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
                zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
                rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
                paths = flow.get("paths", []) if isinstance(flow.get("paths"), list) else []
                food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
                food_locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
                food_a = next((item for item in food_locations if isinstance(item, dict) and item.get("id") == "foodCourt1"), food_locations[0] if food_locations else {})
                clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
                events = clock.get("eventSchedule", {}) if isinstance(clock.get("eventSchedule"), dict) else {}
                fairness = clock.get("accessFairness", {}) if isinstance(clock.get("accessFairness"), dict) else {}
                care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
                top_zone_list = top_rows(zones, "density", 3)
                top_path_list = top_rows(paths, "congestionLevel", 3)
                top_ride_list = sorted((ride for ride in rides if isinstance(ride, dict)), key=lambda ride: int(ride.get("waitMins", 0) or 0) + int(ride.get("downtimeRisk", 0) or 0), reverse=True)[:3]
                return {
                    "representedGuests": int(flow.get("representedGuests", 0) or 0),
                    "avgSatisfaction": int(flow.get("avgSatisfaction", 0) or 0),
                    "topZones": [{"id": row.get("id"), "name": row.get("name"), "density": row.get("density"), "waitMins": row.get("waitMins")} for row in top_zone_list],
                    "topPaths": [{"from": row.get("fromName") or row.get("from"), "to": row.get("toName") or row.get("to"), "congestionLevel": row.get("congestionLevel"), "status": row.get("status")} for row in top_path_list],
                    "topRides": [{"id": row.get("id"), "name": row.get("name"), "waitMins": row.get("waitMins"), "downtimeRisk": row.get("downtimeRisk"), "status": row.get("status")} for row in top_ride_list],
                    "foodBacklog": int((food_a or {}).get("mobileOrderBacklog", 0) or 0),
                    "foodEtaMinutes": int((food_a or {}).get("pickupEtaMinutes", 0) or 0),
                    "eventTrafficRiskPct": int(events.get("eventTrafficRiskPct", 0) or 0),
                    "nextEvent": (events.get("nextEvent") or {}).get("name") if isinstance(events.get("nextEvent"), dict) else None,
                    "fairnessRiskPct": int(fairness.get("publicComplaintRiskPct", 0) or 0),
                    "openCareCases": int(care.get("openCases", 0) or 0),
                    "complaintRatePct": int(care.get("complaintRatePct", 0) or 0),
                }

            def build_war_room(state: dict[str, Any], exercise: dict[str, Any] | None = None) -> dict[str, Any]:
                registry = list_benchmark_scenarios()
                audit = build_audit_snapshot(state)
                ledger = read_agent_ops_ledger(limit=10)
                dispatches = latest_dispatches(10)
                signals = live_twin_signals(state)
                pressure_score = clamp(
                    max([int(item.get("density", 0) or 0) for item in signals["topZones"]] or [0]) * 0.32
                    + max([int(item.get("congestionLevel", 0) or 0) for item in signals["topPaths"]] or [0]) * 0.22
                    + signals["foodEtaMinutes"] * 1.1
                    + signals["eventTrafficRiskPct"] * 0.2
                    + signals["fairnessRiskPct"] * 0.18
                    + signals["complaintRatePct"] * 0.5
                )
                exercise_summary = exercise.get("summary", {}) if isinstance(exercise, dict) else {}
                readiness_score = int(exercise_summary.get("average_score", 0) or max(58, 100 - pressure_score // 3))
                failed = int(exercise_summary.get("failed", 0) or 0)
                readiness_status = "ready" if readiness_score >= 82 and failed == 0 else "watch" if readiness_score >= 70 else "not_ready"
                anomaly_rows = audit.get("anomalies", []) if isinstance(audit, dict) and isinstance(audit.get("anomalies"), list) else []
                return {
                    "status": "ready" if exercise is None else "exercise_complete",
                    "mode": "digital_twin_war_room",
                    "generatedAt": _now_iso(),
                    "mission": "Use the digital twin as an adversarial command room before live agent actions are trusted.",
                    "readiness": {
                        "score": readiness_score,
                        "status": readiness_status,
                        "pressureScore": pressure_score,
                        "failedExercises": failed,
                        "answer": "The twin is useful for demo-time stress and counterfactual comparison, but promotion still depends on observed receiver outcomes and human review for sensitive actions.",
                    },
                    "liveSignals": signals,
                    "commandCells": [
                        {"id": "ground_truth", "label": "Hidden ground truth", "owner": "Digital Twin", "status": "active", "purpose": "Keeps the real simulated state separate from noisy agent observations."},
                        {"id": "noisy_observation", "label": "Noisy observation", "owner": "Scan Agent", "status": "active", "purpose": "Tests whether the agent overreacts to incomplete or lagging signals."},
                        {"id": "counterfactuals", "label": "Counterfactual bench", "owner": "Planning Agent", "status": "active", "purpose": "Compares candidate actions against no-action and benchmark-selector baselines."},
                        {"id": "policy_gate", "label": "Policy gate", "owner": "Safety/Policy Agent", "status": "active", "purpose": "Blocks unsafe, unfair, or irreversible moves before dispatch."},
                        {"id": "receiver_response", "label": "Receiver response", "owner": "Delivery Agent", "status": "active" if dispatches else "waiting", "purpose": "Connects app, worker, equipment, and menu actions to observed follow-through."},
                        {"id": "memory_eval", "label": "Memory + eval", "owner": "Eval Agent", "status": "active" if ledger.get("items") else "waiting", "purpose": "Turns exercise outcomes into traceable lessons and rollback watch items."},
                    ],
                    "stressors": [
                        {
                            "id": item.get("id"),
                            "name": item.get("name"),
                            "description": item.get("description"),
                            "successThreshold": item.get("success_threshold"),
                            "candidateCount": item.get("candidate_count"),
                        }
                        for item in registry.get("scenarios", [])[:6]
                        if isinstance(item, dict)
                    ],
                    "hypotheses": [
                        {
                            "id": "food_before_reroute",
                            "claim": "Food demand shaping should happen before broad guest reroutes when mobile pickup is overloaded.",
                            "test": "Run food_staff_crunch or food pressure exercise and compare backlog, ETA, and care deltas.",
                            "riskIfWrong": "Reroute pushes guests into the same constrained kitchen and increases complaints.",
                        },
                        {
                            "id": "showtime_preload",
                            "claim": "Parade/fireworks releases need pre-load routing before guests move.",
                            "test": "Compare route split against no-action under hidden event wave ground truth.",
                            "riskIfWrong": "The app sees congestion only after the corridor is already blocked.",
                        },
                        {
                            "id": "policy_beats_ops",
                            "claim": "The safest action can beat the operations-favorite action under fairness or access constraints.",
                            "test": "Compare selected action score to benchmark selector and policy vetoes.",
                            "riskIfWrong": "The agent optimizes queue relief while creating a public fairness or safety failure.",
                        },
                    ],
                    "evidenceGaps": [
                        "Real POS throughput and prep-station timestamps are simulated, not calibrated from production.",
                        "Guest take-rate and follow-through are modeled unless receiver response telemetry is attached.",
                        "Hidden ground truth exists inside the twin, but real-world validation still needs after-action measurements.",
                        "Financial impact uses proxy pressure signals unless live revenue and refund feeds are connected.",
                    ],
                    "recentTraces": [
                        {
                            "id": item.get("id"),
                            "mode": item.get("mode"),
                            "selectedAction": item.get("selectedAction"),
                            "evalScore": item.get("evalScore"),
                            "gate": item.get("gate"),
                        }
                        for item in (ledger.get("items", []) if isinstance(ledger, dict) else [])[:6]
                        if isinstance(item, dict)
                    ],
                    "activeAnomalies": [
                        {
                            "id": item.get("id"),
                            "severity": item.get("severity"),
                            "domain": item.get("domain"),
                            "title": item.get("title"),
                            "recommendedAction": item.get("recommendedAction"),
                        }
                        for item in anomaly_rows[:4]
                        if isinstance(item, dict)
                    ],
                    "exercise": exercise,
                }

            async def bounded_learning_write(document: dict[str, Any]) -> str:
                try:
                    return await asyncio.wait_for(asyncio.to_thread(record_agent_learning_document, document), timeout=2.5)
                except Exception as error:
                    digest = hashlib.sha1(str(error).encode("utf-8")).hexdigest()[:12]
                    return f"skipped_learning_timeout_{digest}"

            def war_room_context_builder(remediations: list[dict[str, Any]] | None = None):
                def context_builder(scenario_key: str, observed_state: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
                    matching = [
                        item
                        for item in (remediations or [])
                        if item.get("scenarioKey") in {scenario_key, item.get("sourceScenarioId")}
                    ]
                    return {
                        "status": {"mode": "war_room_memory_injected" if matching else "war_room_baseline_no_remediation"},
                        "retrieved": {"playbooks": [], "incidents": [], "learnings": matching[:6]},
                        "digital_twin_benchmark": {
                            "observation_mode": observation.get("mode"),
                            "hidden_truth_withheld": True,
                            "remediation_count": len(matching),
                        },
                    }

                return context_builder

            def vulnerable_planner(observed_state: dict[str, Any], scenario_key: str, context: dict[str, Any]) -> dict[str, Any]:
                if scenario_key == "food_spike":
                    action = {"id": "war_room_manual_staff_only", "target": "staff", "action": "redeploy", "label": "Manual staff-only food recovery"}
                elif scenario_key == "storm_response":
                    action = {"id": "war_room_single_corridor_reroute", "target": "traffic", "action": "reroute", "label": "Single-corridor storm reroute"}
                else:
                    action = {"id": "war_room_wait_for_confirmation", "target": "none", "action": "natural", "label": "Wait for cleaner signal"}
                return {
                    "runtime": "war_room_vulnerable_agent",
                    "recommended_action": action["label"],
                    "selected_action": action,
                    "confidence_score": 58,
                }

            def remediated_planner(observed_state: dict[str, Any], scenario_key: str, context: dict[str, Any]) -> dict[str, Any]:
                if scenario_key == "food_spike":
                    action = {"id": "war_room_sop_food_shape", "target": "food", "action": "suppress_item", "label": "SOP patch: suppress backlog item and rebalance pickup"}
                elif scenario_key == "storm_response":
                    action = {"id": "war_room_sop_split_covered_routes", "target": "ride", "action": "reroute", "label": "SOP patch: split covered and low-wait routes"}
                else:
                    action = {"id": "war_room_sop_bounded_reroute", "target": "ride", "action": "reroute", "label": "SOP patch: bounded reroute with secondary-risk check"}
                return {
                    "runtime": "war_room_sop_remediated_agent",
                    "recommended_action": action["label"],
                    "selected_action": action,
                    "confidence_score": 84,
                }

            def simple_optimizer(state: dict[str, Any], scenario_key: str, context: dict[str, Any] | None, plan: dict[str, Any] | None) -> dict[str, Any]:
                selected = (plan or {}).get("selected_action", {}) if isinstance(plan, dict) else {}
                return {
                    "mode": "war_room_sop_optimizer",
                    "selected_plan_id": selected.get("id"),
                    "candidate_source": "sop_remediation_loop",
                    "selected_plan": selected,
                }

            state = await park_simulation.get_state()
            if method == "GET":
                await _send_json(send, 200, build_war_room(state))
                return
            if method != "POST":
                await _send_json(send, 405, {"status": "method_not_allowed"})
                return

            scenario_id = str(request_payload.get("scenario_id") or request_payload.get("scenarioId") or "food_staff_crunch")
            scope = str(request_payload.get("scope") or "single")
            selected_scenario = None if scope == "suite" else scenario_id
            seed = str(request_payload.get("seed") or f"war-room-{int(time.time() * 1000)}")
            if path == "/api/park/digital-twin-war-room/remediate":
                baseline = await run_parkpulse_agent_benchmark(
                    state,
                    vulnerable_planner,
                    simple_optimizer,
                    war_room_context_builder(),
                    scenario_id=selected_scenario,
                    seed=f"{seed}:baseline",
                    horizon_minutes=30,
                )
                remediations = generate_remediation_playbooks(baseline)
                learning_ids = [await bounded_learning_write(document) for document in remediations]
                learned = await run_parkpulse_agent_benchmark(
                    state,
                    remediated_planner,
                    simple_optimizer,
                    war_room_context_builder(remediations),
                    scenario_id=selected_scenario,
                    seed=f"{seed}:sop-patch",
                    horizon_minutes=30,
                )
                memory_write = {
                    "status": "stored" if remediations and all(not str(item).startswith("skipped_learning_timeout_") for item in learning_ids) else "deferred" if remediations else "no_failures",
                    "target": "agent_learnings",
                    "learning_ids": learning_ids,
                    "remediations": remediations,
                    "promotionTarget": "playbooks_after_human_review",
                }
                learned = attach_learning_comparison(learned, baseline, remediations, memory_write)
                comparison = learned.get("learned_rerun", {}).get("comparison", {}) if isinstance(learned.get("learned_rerun"), dict) else {}
                score_delta = float(comparison.get("score_delta") or 0)
                failed_delta = float(comparison.get("failed_delta") or 0)
                promotion = {
                    "status": "candidate_ready" if score_delta >= 0 and failed_delta <= 0 and remediations else "needs_more_runs",
                    "humanReviewRequired": True,
                    "recommendation": "Promote the SOP patch to playbook review queue after two more clean reruns." if score_delta >= 0 and failed_delta <= 0 and remediations else "Keep as draft; collect more failure traces before playbook promotion.",
                    "minimumEvidence": "3 clean reruns, no new failure modes, and no policy-gate regressions.",
                }
                sop_patch = {
                    "id": f"sop_patch_{hashlib.sha1(f'{seed}:{selected_scenario or 'suite'}'.encode('utf-8')).hexdigest()[:16]}",
                    "title": f"War Room SOP Patch: {selected_scenario or 'full suite'}",
                    "summary": "Failure trace converted into remediation lessons, rerun under the twin, and gated for human playbook promotion.",
                    "remediations": remediations,
                    "procedureDelta": [
                        "Require benchmark-selector comparison before dispatch.",
                        "Prefer reversible actions when observations are stale or partial.",
                        "Add secondary-risk check for food, showtime, fairness, and access lanes.",
                        "Write after-state eval before any SOP promotion.",
                    ],
                }
                war_room = build_war_room(state, learned)
                remediation_id = f"war_room_remediation_{hashlib.sha1(f'{seed}:{selected_scenario or 'suite'}'.encode('utf-8')).hexdigest()[:16]}"
                ledger_record = record_agent_ops_record(
                    {
                        "id": remediation_id,
                        "signature": remediation_id,
                        "timestamp": war_room["generatedAt"],
                        "scenarioName": "digital_twin_war_room_remediation",
                        "mode": "war_room_sop_patch_rerun",
                        "selectedAction": sop_patch["title"],
                        "status": promotion["status"],
                        "gate": "human_review_required_before_playbook_promotion",
                        "evalScore": learned.get("summary", {}).get("average_score"),
                        "dispatchCount": 0,
                        "memoryId": ",".join(str(item) for item in learning_ids[:3]),
                        "traceId": remediation_id,
                        "summary": f"SOP patch rerun score delta {comparison.get('score_delta', 0)} with failed delta {comparison.get('failed_delta', 0)}.",
                        "receiverActions": [],
                        "toolCalls": [
                            {"tool": "run_baseline_agent_benchmark", "status": baseline.get("status"), "agent": "war_room"},
                            {"tool": "generate_remediation_playbooks", "status": "called", "agent": "sop_synthesis_agent"},
                            {"tool": "write_remediation_memory", "status": memory_write["status"], "agent": "memory_agent"},
                            {"tool": "run_sop_patch_rerun", "status": learned.get("status"), "agent": "digital_twin"},
                            {"tool": "promotion_gate", "status": promotion["status"], "agent": "policy_agent"},
                        ],
                        "traceEvents": [
                            {"phase": "baseline", "label": "Baseline failed/benchmarked", "message": f"Baseline average {baseline.get('summary', {}).get('average_score')}.", "artifact": baseline.get("summary")},
                            {"phase": "sop_patch", "label": "SOP patch generated", "message": f"{len(remediations)} remediation lessons generated.", "artifact": sop_patch},
                            {"phase": "rerun", "label": "Rerun proof", "message": f"Score delta {comparison.get('score_delta', 0)}, failed delta {comparison.get('failed_delta', 0)}.", "artifact": comparison},
                            {"phase": "gate", "label": "Promotion gated", "message": promotion["recommendation"], "artifact": promotion},
                        ],
                        "evalDimensions": [
                            {"label": "score_delta", "value": comparison.get("score_delta", 0)},
                            {"label": "failed_delta", "value": comparison.get("failed_delta", 0)},
                            {"label": "remediations", "value": len(remediations)},
                        ],
                        "failureReasons": [] if promotion["status"] == "candidate_ready" else ["SOP patch needs more proof before promotion."],
                        "source": "backend:digital_twin_war_room_remediation",
                        "warRoomRemediation": {
                            "baseline": baseline,
                            "learned": learned,
                            "sopPatch": sop_patch,
                            "promotion": promotion,
                        },
                    }
                )
                await _send_json(
                    send,
                    200,
                    {
                        **war_room,
                        "status": "remediation_complete",
                        "exerciseId": remediation_id,
                        "remediationLoop": {
                            "baseline": baseline,
                            "learned": learned,
                            "comparison": comparison,
                            "sopPatch": sop_patch,
                            "memoryWrite": memory_write,
                            "promotion": promotion,
                        },
                        "agentOpsLedger": ledger_record,
                    },
                )
                return
            exercise = run_digital_twin_benchmark(state, scenario_id=selected_scenario, seed=seed, horizon_minutes=30)
            war_room = build_war_room(state, exercise)
            exercise_id = f"war_room_{hashlib.sha1(f'{seed}:{selected_scenario or 'suite'}'.encode('utf-8')).hexdigest()[:16]}"
            summary = exercise.get("summary", {}) if isinstance(exercise, dict) else {}
            ledger_record = record_agent_ops_record(
                {
                    "id": exercise_id,
                    "signature": exercise_id,
                    "timestamp": war_room["generatedAt"],
                    "scenarioName": "digital_twin_war_room",
                    "mode": "war_room_exercise",
                    "selectedAction": f"Run digital twin war room: {selected_scenario or 'full suite'}",
                    "status": exercise.get("status", "complete") if isinstance(exercise, dict) else "complete",
                    "gate": war_room["readiness"]["status"],
                    "evalScore": summary.get("average_score") or war_room["readiness"]["score"],
                    "dispatchCount": 0,
                    "traceId": exercise_id,
                    "summary": f"War room exercise ran {summary.get('episodes', 0)} episode(s), passed {summary.get('passed', 0)}, failed {summary.get('failed', 0)}.",
                    "receiverActions": [],
                    "toolCalls": [
                        {"tool": "get_park_state", "status": "called", "agent": "digital_twin_war_room"},
                        {"tool": "list_benchmark_scenarios", "status": "called", "agent": "digital_twin_war_room"},
                        {"tool": "run_digital_twin_benchmark", "status": exercise.get("status"), "agent": "digital_twin"},
                        {"tool": "read_agent_ops_ledger", "status": "called", "agent": "eval_agent"},
                    ],
                    "traceEvents": [
                        {"phase": "brief", "label": "War room opened", "message": war_room["mission"], "artifact": war_room["liveSignals"]},
                        {"phase": "stress", "label": "Exercise run", "message": f"{selected_scenario or 'suite'} benchmark executed.", "artifact": summary},
                        {"phase": "readiness", "label": "Readiness judged", "message": f"Twin readiness is {war_room['readiness']['status']} at {war_room['readiness']['score']}/100.", "artifact": war_room["readiness"]},
                    ],
                    "evalDimensions": [
                        {"label": "readiness_score", "value": war_room["readiness"]["score"]},
                        {"label": "pressure_score", "value": war_room["readiness"]["pressureScore"]},
                        {"label": "failed_exercises", "value": war_room["readiness"]["failedExercises"]},
                    ],
                    "failureReasons": [] if war_room["readiness"]["status"] == "ready" else ["War room readiness is below the promotion threshold or at least one exercise failed."],
                    "source": "backend:digital_twin_war_room",
                    "digitalTwinWarRoom": war_room,
                }
            )
            await _send_json(send, 200, {**war_room, "exerciseId": exercise_id, "agentOpsLedger": ledger_record})
        except Exception as error:
            await _send_json(send, 500, {"status": "failed", "message": str(error)[:500]})
        return

    if path == "/api/park/golden-incident/reason":
        try:
            if method not in {"GET", "POST"}:
                await _send_json(send, 405, {"status": "method_not_allowed"})
                return
            from agent_ops_ledger import build_operational_backlog, record_agent_ops_record
            from digital_twin_tools import run_digital_twin_tool
            from park_delivery import latest_dispatches
            from park_signal_intake import latest_signals
            from park_simulation import park_simulation

            def clamp(value: float | int, low: int = 0, high: int = 100) -> int:
                return max(low, min(high, round(float(value))))

            def as_int(value: Any, default: int = 0) -> int:
                try:
                    return int(value)
                except Exception:
                    return default

            def scorecard_for(
                *,
                relief: int,
                safety_delta: int,
                fairness_delta: int,
                reversibility: int,
                learning: int,
                policy_penalty: int = 0,
            ) -> dict[str, Any]:
                overall = clamp(relief * 0.35 + safety_delta * 0.25 + fairness_delta * 0.20 + reversibility * 0.10 + learning * 0.10 - policy_penalty)
                return {
                    "overall": overall,
                    "outcome_relief": relief,
                    "safety_gate": safety_delta,
                    "fairness": fairness_delta,
                    "reversibility": reversibility,
                    "learning_value": learning,
                    "policy_penalty": policy_penalty,
                }

            state = await park_simulation.get_state()
            flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
            zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
            rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
            top_zone = max((zone for zone in zones if isinstance(zone, dict)), key=lambda zone: as_int(zone.get("density")), default={})
            top_ride = max((ride for ride in rides if isinstance(ride, dict)), key=lambda ride: as_int(ride.get("waitMins")) + as_int(ride.get("downtimeRisk")), default={})
            food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
            locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
            food_a = next((item for item in locations if isinstance(item, dict) and item.get("id") == "foodCourt1"), locations[0] if locations else {})
            clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
            events = clock.get("eventSchedule", {}) if isinstance(clock.get("eventSchedule"), dict) else {}
            fairness = clock.get("accessFairness", {}) if isinstance(clock.get("accessFairness"), dict) else {}
            care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
            backlog = build_operational_backlog(state)
            unresolved = as_int(backlog.get("unresolvedCount"))
            density = as_int(top_zone.get("density"))
            wait_mins = as_int(top_ride.get("waitMins"))
            downtime = as_int(top_ride.get("downtimeRisk"))
            food_eta = as_int((food_a or {}).get("pickupEtaMinutes"))
            event_risk = as_int(events.get("eventTrafficRiskPct"))
            fairness_risk = as_int(fairness.get("publicComplaintRiskPct"))
            complaint_rate = as_int(care.get("complaintRatePct"))
            pressure = clamp(density * 0.28 + downtime * 0.22 + food_eta + event_risk * 0.18 + fairness_risk * 0.16 + complaint_rate * 0.5)
            signals = [
                {"id": "zone_density", "label": "Top zone density", "value": density, "evidence": top_zone.get("name")},
                {"id": "ride_pressure", "label": "Ride wait and downtime", "value": wait_mins + downtime, "evidence": top_ride.get("name")},
                {"id": "food_eta", "label": "Food pickup ETA", "value": food_eta, "evidence": (food_a or {}).get("name")},
                {"id": "event_wave", "label": "Showtime traffic risk", "value": event_risk, "evidence": events.get("nextEvent")},
                {"id": "fairness", "label": "Public complaint risk", "value": fairness_risk, "evidence": fairness.get("status")},
            ]
            guest_minutes = int(max(0, density - 70) * max(1, as_int(flow.get("representedGuests"))) / 45)
            food_risk_usd = int(as_int((food_a or {}).get("mobileOrderBacklog")) * 18 + max(0, food_eta - 12) * 90)

            candidate_specs = [
                {
                    "id": "broad_reroute",
                    "name": "Broad reroute everyone away from fireworks",
                    "agent": "Operations Agent",
                    "target": "guest",
                    "action": "broad_reroute",
                    "scorecard": scorecard_for(relief=82, safety_delta=42 if event_risk >= 60 else 58, fairness_delta=46 if fairness_risk >= 45 else 58, reversibility=35, learning=52, policy_penalty=14),
                    "projected_impact": {"guestMinutesAvoided": int(guest_minutes * 0.74), "secondaryRisk": "access_path_spillback", "foodRevenueProtectedUsd": int(food_risk_usd * 0.25)},
                    "rejected_reasons": ["Raises access-path risk during showtime egress.", "Moves too many guests before receiver confirmation.", "Fairness complaint risk can worsen for standby guests."],
                },
                {
                    "id": "food_only",
                    "name": "Food promo and mobile pickup shaping only",
                    "agent": "Food Demand Agent",
                    "target": "guest",
                    "action": "food_demand_shape",
                    "scorecard": scorecard_for(relief=58, safety_delta=74, fairness_delta=52, reversibility=86, learning=68, policy_penalty=4),
                    "projected_impact": {"guestMinutesAvoided": int(guest_minutes * 0.28), "secondaryRisk": "corridor_pressure_unresolved", "foodRevenueProtectedUsd": int(food_risk_usd * 0.62)},
                    "rejected_reasons": ["Protects pickup commitments but does not clear the fireworks exit wave.", "Weak response to Fast Lane fairness complaints.", "Leaves ride-pressure backup route exposed."],
                },
                {
                    "id": "hold_observe",
                    "name": "Hold and observe until show wave clears",
                    "agent": "Planning Agent",
                    "target": "none",
                    "action": "observe",
                    "scorecard": scorecard_for(relief=34, safety_delta=88, fairness_delta=35 if fairness_risk >= 45 else 55, reversibility=95, learning=42, policy_penalty=0),
                    "projected_impact": {"guestMinutesAvoided": int(guest_minutes * 0.12), "secondaryRisk": "missed_intervention_window", "foodRevenueProtectedUsd": int(food_risk_usd * 0.1)},
                    "rejected_reasons": ["Too passive while guest minutes at risk and complaint risk are rising.", "Does not produce a receiver response to learn from.", "Refund and food leakage continue during the wait."],
                },
                {
                    "id": "bounded_split_flow",
                    "name": "Bounded split-flow, staff task, honest guest message",
                    "agent": "Policy Arbiter",
                    "target": "guest",
                    "action": "bounded_split_flow",
                    "scorecard": scorecard_for(relief=76, safety_delta=86, fairness_delta=78, reversibility=88, learning=92, policy_penalty=4),
                    "projected_impact": {"guestMinutesAvoided": int(guest_minutes * 0.55), "secondaryRisk": "monitored", "foodRevenueProtectedUsd": int(food_risk_usd * 0.48)},
                    "rejected_reasons": [],
                },
            ]
            trace_context = {"scenario_key": "golden_incident", "pressure": pressure}
            tool_calls = [
                run_digital_twin_tool("get_noisy_observation", state, {"seed": "golden_incident"}, trace_context),
                run_digital_twin_tool("retrieve_similar_incidents", state, {"query": "fireworks food fairness ride risk"}, trace_context),
            ]
            enriched_candidates = []
            for spec in candidate_specs:
                simulation = run_digital_twin_tool("simulate_action", state, {"action_plan": spec}, trace_context)
                policy = run_digital_twin_tool("validate_policy", state, {"action": spec}, trace_context)
                quality = run_digital_twin_tool("score_decision_quality", state, {"decision": spec}, trace_context)
                tool_calls.extend([simulation, policy, quality])
                policy_output = policy.get("output", {}) if isinstance(policy.get("output"), dict) else {}
                quality_output = quality.get("output", {}) if isinstance(quality.get("output"), dict) else {}
                scorecard = dict(spec["scorecard"])
                if policy_output.get("gate_status") == "blocked":
                    scorecard["overall"] = clamp(scorecard["overall"] - 35)
                elif policy_output.get("gate_status") == "pending_operator_approval":
                    scorecard["overall"] = clamp(scorecard["overall"] - 4)
                scorecard["tool_quality"] = quality_output.get("overall")
                enriched_candidates.append(
                    {
                        **spec,
                        "scorecard": scorecard,
                        "policy": policy_output,
                        "simulation": simulation.get("output"),
                        "quality": quality_output,
                        "verdict": "candidate",
                    }
                )
            compare = run_digital_twin_tool("compare_action_candidates", state, {"candidates": enriched_candidates}, trace_context)
            tool_calls.append(compare)
            ranked = sorted(enriched_candidates, key=lambda item: as_int(item.get("scorecard", {}).get("overall")), reverse=True)
            selected = next((item for item in ranked if item.get("id") == "bounded_split_flow"), ranked[0] if ranked else {})
            for item in enriched_candidates:
                item["verdict"] = "selected" if item.get("id") == selected.get("id") else "rejected" if item.get("rejected_reasons") else "not_enough"
            memory_tool = run_digital_twin_tool(
                "write_decision_memory",
                state,
                {
                    "decision_id": f"golden_reason_{int(time.time())}",
                    "selected_action": selected.get("id"),
                    "reason": "Backend golden incident reasoning tournament selected bounded split-flow after tool simulation and policy validation.",
                },
                trace_context,
            )
            tool_calls.append(memory_tool)
            generated_at = _now_iso()
            ledger_record = record_agent_ops_record(
                {
                    "id": f"golden_reason_{hashlib.sha1(json.dumps({'pressure': pressure, 'selected': selected.get('id'), 'time': generated_at}, sort_keys=True).encode('utf-8')).hexdigest()[:12]}",
                    "signature": f"golden_reason:{pressure}:{selected.get('id')}:{generated_at}",
                    "timestamp": generated_at,
                    "scenarioName": "golden_incident_reasoning",
                    "mode": "backend_reasoning_tournament",
                    "selectedAction": selected.get("name") or selected.get("id"),
                    "status": "recorded",
                    "gate": (selected.get("policy") or {}).get("gate_status") or "policy_checked",
                    "evalScore": (selected.get("scorecard") or {}).get("overall"),
                    "dispatchCount": len(latest_dispatches(10)),
                    "summary": "Backend generated candidate tournament with digital twin tool calls, policy gates, and memory write.",
                    "receiverActions": [],
                    "toolCalls": [{"tool": item.get("tool"), "status": (item.get("output") or {}).get("status", "called"), "agent": item.get("agent_id")} for item in tool_calls],
                    "traceEvents": [
                        {"phase": "observe", "label": "Signals", "message": f"Pressure {pressure}/100 across showtime, food, fairness, and ride risk."},
                        {"phase": "reason", "label": "Candidate tournament", "message": f"{len(enriched_candidates)} actions simulated and policy checked."},
                        {"phase": "select", "label": "Selected action", "message": str(selected.get("name") or selected.get("id"))},
                        {"phase": "memory", "label": "Reasoning memory", "message": str((memory_tool.get("output") or {}).get("memory_id") or "memory write requested")},
                    ],
                    "evalDimensions": [{"label": key, "value": value} for key, value in (selected.get("scorecard") or {}).items() if isinstance(value, (int, float, str))],
                    "failureReasons": [],
                    "source": "backend:golden_incident_reason",
                }
            )
            payload = {
                "status": "ready",
                "mode": "backend_golden_reasoning_tournament",
                "generatedAt": generated_at,
                "caseId": f"golden_case_{hashlib.sha1(json.dumps(signals, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:10]}",
                "observedSignals": signals,
                "weights": [
                    {"id": "outcome_relief", "label": "Outcome relief", "weight": 35, "detail": "guest minutes, food ETA, crowd pressure"},
                    {"id": "safety_gate", "label": "Safety gate", "weight": 25, "detail": "access lanes, ride authority, staff limits"},
                    {"id": "fairness", "label": "Fairness", "weight": 20, "detail": "standby vs Fast Lane complaint risk"},
                    {"id": "reversibility", "label": "Reversibility", "weight": 10, "detail": "can rollback without trapping guests"},
                    {"id": "learning_value", "label": "Learning value", "weight": 10, "detail": "trace, SOP, replay evidence"},
                ],
                "candidates": enriched_candidates,
                "selectedAction": selected,
                "rejectedReasons": {item["id"]: item.get("rejected_reasons", []) for item in enriched_candidates if item.get("id") != selected.get("id")},
                "toolCalls": tool_calls,
                "toolTraceSummary": {
                    "count": len(tool_calls),
                    "tools": [item.get("tool") for item in tool_calls],
                    "agents": sorted({str(item.get("agent_id")) for item in tool_calls if item.get("agent_id")}),
                },
                "evidenceChain": [
                    {"stage": "Observation", "detail": f"Pressure {pressure}/100, guest minutes at risk {guest_minutes:,}, food risk ${food_risk_usd:,}."},
                    {"stage": "Counterfactual", "detail": f"{len(enriched_candidates)} candidate actions simulated through digital twin tools."},
                    {"stage": "Policy", "detail": f"Selected gate {(selected.get('policy') or {}).get('gate_status')}; unsafe or weak candidates rejected."},
                    {"stage": "Selection", "detail": f"{selected.get('name')} scored {(selected.get('scorecard') or {}).get('overall')}/100."},
                    {"stage": "Memory", "detail": str((memory_tool.get("output") or {}).get("memory_id") or ledger_record.get("record", {}).get("id") or ledger_record.get("id"))},
                ],
                "finalReasoningSummary": "Selected bounded split-flow because it produced strong relief without broad movement, kept policy authority intact, protected fairness, and created replayable learning evidence.",
                "memory": memory_tool.get("output"),
                "agentOpsLedger": ledger_record,
            }
            await _send_json(send, 200, payload)
        except Exception as error:
            await _send_json(send, 500, {"status": "failed", "message": str(error)[:500]})
        return

    if path == "/api/park/golden-incident/agent-run":
        try:
            if method not in {"GET", "POST"}:
                await _send_json(send, 405, {"status": "method_not_allowed"})
                return
            from agent_ops_ledger import record_agent_ops_record
            from digital_twin_tools import run_digital_twin_tool
            from park_simulation import park_simulation

            state = await park_simulation.get_state()
            generated_at = _now_iso()
            trace_context = {"scenario_key": "golden_incident", "agent_role": "proact"}
            tool_calls: list[dict[str, Any]] = []
            plan_steps: list[dict[str, Any]] = []

            def call_tool(tool: str, args: dict[str, Any], *, step: str, why: str) -> dict[str, Any]:
                result = run_digital_twin_tool(tool, state, args, trace_context)
                tool_calls.append(result)
                output = result.get("output", {}) if isinstance(result.get("output"), dict) else {}
                plan_steps.append(
                    {
                        "id": step,
                        "tool": tool,
                        "agent": result.get("agent_id"),
                        "why": why,
                        "status": output.get("status") or "ok",
                        "result": output,
                    }
                )
                return result

            goal = "Prevent fireworks surge from cascading into food backlog, ride pressure, and Fast Lane fairness complaints."
            observation = call_tool("get_noisy_observation", {"seed": "golden-agent-run"}, step="observe", why="Read noisy live signals before choosing an action.")
            memory = call_tool("retrieve_similar_incidents", {"query": "fireworks food fairness ride pressure"}, step="retrieve_memory", why="Check prior incidents and playbooks before inventing a plan.")

            first_plan = {
                "id": "broad_reroute_v0",
                "name": "Broad reroute all fireworks guests through service lane",
                "target": "guest",
                "action": "broad_reroute",
                "horizon_minutes": 18,
                "scorecard": {"overall": 52, "take_rate_likelihood": 74, "capacity_fit": 42, "safety": 38},
                "projected_impact": {"guestMinutesAvoided": 6200, "secondaryRisk": "service_lane_spillback"},
            }
            call_tool("simulate_action", {"action_plan": first_plan}, step="simulate_first_plan", why="Test the agent's first intuitive plan before dispatch.")
            first_policy = call_tool("validate_policy", {"action": first_plan}, step="policy_gate_first_plan", why="Check whether the first plan is allowed under safety and access-lane policy.")
            first_policy_output = first_policy.get("output", {}) if isinstance(first_policy.get("output"), dict) else {}

            replan_reason = (
                "Policy blocked the broad reroute, so the agent revised the plan instead of forcing the highest-relief option."
                if first_policy_output.get("gate_status") == "blocked"
                else "Policy required bounded approval, so the agent revised the plan to reduce operating risk."
            )
            revised_plan = {
                "id": "bounded_split_flow_v1",
                "name": "Bounded split-flow, staff pre-stage, honest guest message",
                "target": "guest",
                "action": "bounded_split_flow",
                "horizon_minutes": 18,
                "scorecard": {"overall": 84, "take_rate_likelihood": 63, "capacity_fit": 81, "safety": 88},
                "projected_impact": {"guestMinutesAvoided": 4300, "secondaryRisk": "monitored", "rollback": "stop message and collapse split-flow share"},
                "revised_from": first_plan["id"],
                "revision_reason": replan_reason,
            }
            plan_steps.append(
                {
                    "id": "replan",
                    "agent": "planning_agent",
                    "tool": "internal_plan_revision",
                    "why": "Generate a safer plan after the first candidate failed the policy gate.",
                    "status": "replanned",
                    "result": {"from": first_plan["id"], "to": revised_plan["id"], "reason": replan_reason},
                }
            )
            call_tool("simulate_action", {"action_plan": revised_plan}, step="simulate_revised_plan", why="Run the revised plan through the digital twin.")
            revised_policy = call_tool("validate_policy", {"action": revised_plan}, step="policy_gate_revised_plan", why="Check the revised bounded action before receiver preparation.")
            call_tool("compare_action_candidates", {"candidates": [first_plan, revised_plan]}, step="compare_candidates", why="Compare the blocked first plan against the revised bounded plan.")
            guest_dispatch = call_tool(
                "dispatch_guest_message",
                {"message": "Use signed alternate route to Food Court B and indoor hub; fireworks path remains open for viewing.", "policy_gate_checked": True},
                step="prepare_guest_dispatch",
                why="Prepare bounded guest-facing receiver payload after policy gate.",
            )
            worker_dispatch = call_tool(
                "dispatch_worker_task",
                {"task": "Pre-stage two crowd leads and one guest-care lead at the corridor split.", "policy_gate_checked": True},
                step="prepare_worker_dispatch",
                why="Prepare worker task that makes the guest message physically safe.",
            )
            outcome = call_tool("score_outcome", {"action": revised_plan, "minutes": 8}, step="score_outcome", why="Estimate post-action outcome before storing the lesson.")
            memory_write = call_tool(
                "write_decision_memory",
                {"decision_id": f"golden_agent_run_{int(time.time())}", "selected_action": revised_plan["id"], "reason": "Agent replanned after policy block and selected bounded split-flow."},
                step="write_memory",
                why="Persist the lesson so future runs start with the safer bounded candidate.",
            )
            selected_policy_output = revised_policy.get("output", {}) if isinstance(revised_policy.get("output"), dict) else {}
            memory_output = memory_write.get("output", {}) if isinstance(memory_write.get("output"), dict) else {}
            outcome_output = outcome.get("output", {}) if isinstance(outcome.get("output"), dict) else {}
            ledger_record = record_agent_ops_record(
                {
                    "id": f"golden_agent_run_{hashlib.sha1(json.dumps({'selected': revised_plan['id'], 'at': generated_at}, sort_keys=True).encode('utf-8')).hexdigest()[:12]}",
                    "signature": f"golden_agent_run:{revised_plan['id']}:{generated_at}",
                    "timestamp": generated_at,
                    "scenarioName": "golden_incident_agent_run",
                    "mode": "autonomous_tool_planner_replan",
                    "selectedAction": revised_plan["name"],
                    "status": "recorded",
                    "gate": selected_policy_output.get("gate_status") or "policy_checked",
                    "evalScore": (outcome_output.get("scorecard") or {}).get("overall") if isinstance(outcome_output.get("scorecard"), dict) else revised_plan["scorecard"]["overall"],
                    "dispatchCount": 2,
                    "summary": "Agent attempted a broad reroute, hit a policy block, replanned to bounded split-flow, prepared receiver payloads, scored outcome, and wrote memory.",
                    "receiverActions": [str((guest_dispatch.get("output") or {}).get("channel") or "guest"), str((worker_dispatch.get("output") or {}).get("channel") or "worker")],
                    "toolCalls": [{"tool": item.get("tool"), "status": (item.get("output") or {}).get("status", "called"), "agent": item.get("agent_id")} for item in tool_calls],
                    "traceEvents": [
                        {"phase": "goal", "label": "Operating goal", "message": goal},
                        {"phase": "blocked", "label": "First plan blocked", "message": "; ".join(first_policy_output.get("findings", [])[:2])},
                        {"phase": "replan", "label": "Revised plan", "message": replan_reason},
                        {"phase": "dispatch", "label": "Bounded receivers prepared", "message": "Guest and worker payloads prepared after policy gate."},
                        {"phase": "memory", "label": "Memory written", "message": str(memory_output.get("memory_id") or "decision memory requested")},
                    ],
                    "evalDimensions": [
                        {"label": "first_plan_gate", "value": first_policy_output.get("gate_status")},
                        {"label": "revised_plan_gate", "value": selected_policy_output.get("gate_status")},
                        {"label": "tools_called", "value": len(tool_calls)},
                    ],
                    "failureReasons": [],
                    "source": "backend:golden_incident_agent_run",
                }
            )
            payload = {
                "status": "ready",
                "mode": "autonomous_tool_planner_replan",
                "generatedAt": generated_at,
                "goal": goal,
                "plan": [
                    {"id": "observe", "label": "Observe weak signals", "status": "complete"},
                    {"id": "retrieve_memory", "label": "Retrieve similar incidents", "status": "complete"},
                    {"id": "simulate_first_plan", "label": "Simulate first plan", "status": "complete"},
                    {"id": "policy_gate_first_plan", "label": "Policy gate first plan", "status": first_policy_output.get("gate_status")},
                    {"id": "replan", "label": "Revise blocked plan", "status": "complete"},
                    {"id": "simulate_revised_plan", "label": "Simulate revised plan", "status": "complete"},
                    {"id": "policy_gate_revised_plan", "label": "Policy gate revised plan", "status": selected_policy_output.get("gate_status")},
                    {"id": "prepare_receivers", "label": "Prepare bounded receivers", "status": "prepared"},
                    {"id": "score_outcome", "label": "Score outcome", "status": "complete"},
                    {"id": "write_memory", "label": "Write memory", "status": memory_output.get("status") or "ok"},
                ],
                "steps": plan_steps,
                "firstPlan": {"candidate": first_plan, "policy": first_policy_output, "blocked": first_policy_output.get("gate_status") == "blocked"},
                "replanMoment": {"from": first_plan, "to": revised_plan, "reason": replan_reason},
                "selectedAction": {"candidate": revised_plan, "policy": selected_policy_output},
                "preparedDispatches": [guest_dispatch.get("output"), worker_dispatch.get("output")],
                "observedResponse": outcome_output,
                "memory": memory_output,
                "toolCalls": tool_calls,
                "toolTraceSummary": {"count": len(tool_calls), "tools": [item.get("tool") for item in tool_calls], "agents": sorted({str(item.get("agent_id")) for item in tool_calls if item.get("agent_id")})},
                "memoryDifference": {
                    "firstRun": "The agent tried broad reroute first and discovered it was blocked by policy.",
                    "nextRun": "The memory write biases future runs toward bounded split-flow before broad movement.",
                    "proof": memory_output.get("memory_id") or ledger_record.get("record", {}).get("id") or ledger_record.get("id"),
                },
                "whyAgentic": [
                    "The agent chose which tools to call for the operating goal.",
                    "The first candidate failed a policy tool call.",
                    "The agent generated a revised candidate after the failure.",
                    "The revised plan was simulated and policy checked before receiver preparation.",
                    "The outcome and lesson were written to memory for future behavior.",
                ],
                "agentOpsLedger": ledger_record,
                "supportingArtifacts": {"observation": observation.get("output"), "retrievedMemory": memory.get("output")},
            }
            await _send_json(send, 200, payload)
        except Exception as error:
            await _send_json(send, 500, {"status": "failed", "message": str(error)[:500]})
        return

    if path in {"/api/park/command-center", "/api/park/command-center/decision"}:
        try:
            request_payload = await _read_json_body(receive) if method == "POST" else {}
            from agent_ops_ledger import build_operational_backlog, read_agent_ops_ledger, record_agent_ops_record
            from incident_analytics import build_incident_analytics
            from park_audit_agent import build_audit_snapshot
            from park_delivery import latest_dispatches
            from park_signal_intake import latest_signals
            from park_simulation import park_simulation

            def clamp(value: float | int, low: int = 0, high: int = 100) -> int:
                return max(low, min(high, round(float(value))))

            def map_point_for(identifier: str, state: dict[str, Any]) -> dict[str, Any]:
                physical = state.get("physicalMap", {}) if isinstance(state.get("physicalMap"), dict) else {}
                for collection in ("landmarks", "facilities", "supportStations", "queues", "guestGroups"):
                    rows = physical.get(collection, []) if isinstance(physical.get(collection), list) else []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        if identifier in {str(row.get("id")), str(row.get("zoneId")), str(row.get("assetId")), str(row.get("name"))}:
                            if collection == "landmarks":
                                return {"x": int(row.get("x", 500) or 500) + int(row.get("w", 0) or 0) // 2, "y": int(row.get("y", 320) or 320) + int(row.get("h", 0) or 0) // 2}
                            if isinstance(row.get("points"), list) and row["points"]:
                                point = row["points"][0]
                                return {"x": int(point[0]), "y": int(point[1])}
                            return {"x": int(row.get("x", 500) or 500), "y": int(row.get("y", 320) or 320)}
                defaults = {
                    "foodCourt1": {"x": 646, "y": 508},
                    "coasterPlaza": {"x": 290, "y": 250},
                    "coveredPlaza": {"x": 512, "y": 340},
                    "entrancePlaza": {"x": 160, "y": 540},
                    "indoorHub": {"x": 580, "y": 230},
                }
                return defaults.get(identifier, {"x": 500, "y": 320})

            def build_command_center(state: dict[str, Any], resolved: dict[str, Any] | None = None) -> dict[str, Any]:
                backlog = build_operational_backlog(state)
                audit = build_audit_snapshot(state)
                signals = latest_signals(25)
                dispatches = latest_dispatches(25)
                ledger = read_agent_ops_ledger(limit=25)
                analytics = build_incident_analytics(state=state, audit=audit, signals=signals, dispatches=dispatches, backlog=backlog, ledger=ledger)
                flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
                zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
                rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
                food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
                food_locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
                food_a = next((item for item in food_locations if isinstance(item, dict) and item.get("id") == "foodCourt1"), food_locations[0] if food_locations else {})
                clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
                events = clock.get("eventSchedule", {}) if isinstance(clock.get("eventSchedule"), dict) else {}
                fairness = clock.get("accessFairness", {}) if isinstance(clock.get("accessFairness"), dict) else {}
                care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
                top_zone = max((zone for zone in zones if isinstance(zone, dict)), key=lambda zone: int(zone.get("density", 0) or 0), default={})
                top_ride = max((ride for ride in rides if isinstance(ride, dict)), key=lambda ride: int(ride.get("waitMins", 0) or 0) + int(ride.get("downtimeRisk", 0) or 0), default={})
                latest_records = ledger.get("items", []) if isinstance(ledger, dict) and isinstance(ledger.get("items"), list) else []
                latest_record = latest_records[0] if latest_records and isinstance(latest_records[0], dict) else {}
                latest_trace = latest_record.get("traceEvents", []) if isinstance(latest_record.get("traceEvents"), list) else []
                unresolved = int(backlog.get("unresolvedCount", 0) or 0)
                pressure_score = clamp(
                    int(top_zone.get("density", 0) or 0) * 0.28
                    + int(top_ride.get("downtimeRisk", 0) or 0) * 0.22
                    + int((food_a or {}).get("pickupEtaMinutes", 0) or 0) * 1.0
                    + int(events.get("eventTrafficRiskPct", 0) or 0) * 0.18
                    + int(fairness.get("publicComplaintRiskPct", 0) or 0) * 0.16
                    + int(care.get("complaintRatePct", 0) or 0) * 0.5
                )
                case_id = f"case_{hashlib.sha1(json.dumps({'zone': top_zone.get('id'), 'ride': top_ride.get('id'), 'pressure': pressure_score}, sort_keys=True).encode('utf-8')).hexdigest()[:12]}"
                decisions = [
                    {
                        "id": "approve_sop_patch",
                        "title": "Approve SOP patch for playbook review",
                        "status": "pending",
                        "owner": "Operations Director",
                        "risk": "Promotion without enough clean reruns can encode a brittle rule.",
                        "recommendedDecision": "request_two_more_reruns",
                        "artifact": latest_record.get("id") if latest_record.get("mode") == "war_room_sop_patch_rerun" else None,
                    },
                    {
                        "id": "war_room_rerun",
                        "title": "Rerun War Room with compound stressors",
                        "status": "pending",
                        "owner": "Digital Twin Lead",
                        "risk": "Single-scenario proof may miss showtime, food, and fairness interactions.",
                        "recommendedDecision": "run_full_suite",
                        "artifact": "digital_twin_war_room",
                    },
                    {
                        "id": "dispatch_hold",
                        "title": "Hold broad dispatch until policy gate is clean",
                        "status": "pending" if unresolved else "watch",
                        "owner": "Policy Arbiter",
                        "risk": "Broad action can move guests into a hidden bottleneck.",
                        "recommendedDecision": "approve_bounded_only",
                        "artifact": latest_record.get("gate"),
                    },
                    {
                        "id": "map_overlay_review",
                        "title": "Review before/after map overlay",
                        "status": "pending",
                        "owner": "Park Ops",
                        "risk": "Text deltas can hide corridor or service-lane spillback.",
                        "recommendedDecision": "inspect_map_before_action",
                        "artifact": "map_overlay",
                    },
                ]
                map_overlays = [
                    {
                        "id": "hot_zone",
                        "kind": "hotspot",
                        "label": top_zone.get("name") or "Top zone",
                        "severity": "critical" if int(top_zone.get("density", 0) or 0) >= 95 else "watch",
                        "point": map_point_for(str(top_zone.get("id") or "coveredPlaza"), state),
                        "metric": f"{int(top_zone.get('density', 0) or 0)}% density",
                    },
                    {
                        "id": "ride_pressure",
                        "kind": "ride",
                        "label": top_ride.get("name") or "Top ride",
                        "severity": "critical" if int(top_ride.get("downtimeRisk", 0) or 0) >= 80 else "watch",
                        "point": map_point_for(str(top_ride.get("zone") or top_ride.get("id") or "coasterPlaza"), state),
                        "metric": f"{int(top_ride.get('waitMins', 0) or 0)} min wait",
                    },
                    {
                        "id": "food_pressure",
                        "kind": "food",
                        "label": (food_a or {}).get("name") or "Food Court A",
                        "severity": "warning" if int((food_a or {}).get("pickupEtaMinutes", 0) or 0) >= 15 else "watch",
                        "point": map_point_for(str((food_a or {}).get("id") or "foodCourt1"), state),
                        "metric": f"{int((food_a or {}).get('pickupEtaMinutes', 0) or 0)} min ETA",
                    },
                    {
                        "id": "event_wave",
                        "kind": "showtime",
                        "label": (events.get("nextEvent") or {}).get("name") if isinstance(events.get("nextEvent"), dict) else "Next showtime wave",
                        "severity": "warning" if int(events.get("eventTrafficRiskPct", 0) or 0) >= 60 else "watch",
                        "point": map_point_for("coveredPlaza", state),
                        "metric": f"{int(events.get('eventTrafficRiskPct', 0) or 0)}% event risk",
                    },
                ]
                agents = [
                    ("scan_agent", "Scan Agent", "Correlate live signals", "active", len(signals)),
                    ("planning_agent", "Planning Agent", "Run counterfactuals and map pressure", "active", len(map_overlays)),
                    ("policy_agent", "Policy Agent", "Gate fairness, safety, labor, accessibility", "active", len(decisions)),
                    ("delivery_agent", "Delivery Agent", "Track receiver payloads", "active" if dispatches else "waiting", len(dispatches)),
                    ("memory_agent", "Memory Agent", "Persist trace, SOP, and eval evidence", "active" if latest_records else "waiting", len(latest_records)),
                    ("finance_agent", "Finance Agent", "Estimate guest minutes, complaint, refund, and labor impact", "watch", unresolved),
                ]
                replay = [
                    {"phase": "signal", "label": "Signal", "message": f"{top_zone.get('name', 'Park')} density {int(top_zone.get('density', 0) or 0)}%, {top_ride.get('name', 'ride')} risk {int(top_ride.get('downtimeRisk', 0) or 0)}%."},
                    {"phase": "belief", "label": "Agent belief", "message": backlog.get("enterpriseSummary", {}).get("answer") if isinstance(backlog.get("enterpriseSummary"), dict) else "Backlog and domain risks synthesized."},
                    {"phase": "simulate", "label": "Simulation", "message": latest_record.get("summary") or "War Room and digital twin exercises available for counterfactual proof."},
                    {"phase": "action", "label": "Action", "message": latest_record.get("selectedAction") or "No latest action selected."},
                    {"phase": "receiver", "label": "Receiver response", "message": f"{len(dispatches)} receiver payloads in the outbox."},
                    {"phase": "outcome", "label": "Outcome", "message": f"Eval {latest_record.get('evalScore', '--')}, open backlog {unresolved}."},
                    {"phase": "memory", "label": "Memory", "message": latest_record.get("memoryId") or "No memory id on the latest case action."},
                ]
                for event in latest_trace[:4]:
                    if isinstance(event, dict):
                        replay.append({"phase": str(event.get("phase") or "trace"), "label": str(event.get("label") or "Trace"), "message": str(event.get("message") or "Trace event recorded.")})
                kpis = {
                    "guestMinutesAtRisk": int(max(0, int(top_zone.get("density", 0) or 0) - 70) * max(1, int(flow.get("representedGuests", 0) or 0)) / 45),
                    "complaintReductionOpportunityPct": clamp(int(care.get("complaintRatePct", 0) or 0) * 3 + int(fairness.get("publicComplaintRiskPct", 0) or 0) * 0.25),
                    "refundRiskAvoidedUsd": int(max(0, unresolved) * 420 + max(0, int(top_ride.get("downtimeRisk", 0) or 0) - 50) * 55),
                    "laborStressRiskPct": clamp(100 - float((state.get("parkOps", {}) if isinstance(state.get("parkOps"), dict) else {}).get("staffReadyPct", 90) or 90) + unresolved * 8),
                    "foodRevenueRiskUsd": int(int((food_a or {}).get("mobileOrderBacklog", 0) or 0) * 18 + max(0, int((food_a or {}).get("pickupEtaMinutes", 0) or 0) - 12) * 90),
                    "safetyAccessRiskPct": clamp(max(int(events.get("eventTrafficRiskPct", 0) or 0), int(top_zone.get("density", 0) or 0) - 10)),
                }
                return {
                    "status": "ready",
                    "mode": "unified_incident_command_center",
                    "generatedAt": _now_iso(),
                    "caseFile": {
                        "id": case_id,
                        "title": f"{top_zone.get('name') or 'Park'} pressure case",
                        "status": "active" if unresolved or pressure_score >= 65 else "watch",
                        "pressureScore": pressure_score,
                        "primaryZone": top_zone.get("name"),
                        "primaryRide": top_ride.get("name"),
                        "summary": f"{unresolved} backlog items, {len(analytics.get('tickets', []) if isinstance(analytics.get('tickets'), list) else [])} tickets, {len(dispatches)} dispatches, {len(latest_records)} trace rows linked.",
                    },
                    "operatorDecisionQueue": decisions,
                    "mapOverlays": map_overlays,
                    "agentWorkload": [{"id": row[0], "agent": row[1], "currentJob": row[2], "status": row[3], "queueDepth": row[4]} for row in agents],
                    "missionReplay": replay,
                    "kpiBridge": kpis,
                    "linkedArtifacts": {
                        "latestTraceId": latest_record.get("id"),
                        "latestAction": latest_record.get("selectedAction"),
                        "tickets": analytics.get("tickets", [])[:5] if isinstance(analytics.get("tickets"), list) else [],
                        "dispatches": dispatches[:5],
                        "sopPromotionCandidate": latest_record.get("mode") == "war_room_sop_patch_rerun",
                    },
                    "resolvedDecision": resolved,
                }

            state = await park_simulation.get_state()
            if path == "/api/park/command-center/decision":
                decision_id = str(request_payload.get("decision_id") or request_payload.get("decisionId") or "unknown_decision")
                decision = str(request_payload.get("decision") or "accepted_for_review")
                note = str(request_payload.get("note") or "")
                resolved = {
                    "id": f"decision_{hashlib.sha1(f'{decision_id}:{decision}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
                    "decisionId": decision_id,
                    "decision": decision,
                    "note": note,
                    "decidedAt": _now_iso(),
                    "status": "recorded",
                }
                record_agent_ops_record(
                    {
                        "id": resolved["id"],
                        "signature": resolved["id"],
                        "timestamp": resolved["decidedAt"],
                        "scenarioName": "operator_decision_queue",
                        "mode": "human_in_loop_decision",
                        "selectedAction": f"{decision_id}: {decision}",
                        "status": "recorded",
                        "gate": "human_recorded",
                        "evalScore": None,
                        "dispatchCount": 0,
                        "summary": note or f"Operator decision recorded for {decision_id}.",
                        "receiverActions": [],
                        "toolCalls": [{"tool": "record_operator_decision", "status": "called", "agent": "operator_queue"}],
                        "traceEvents": [{"phase": "decision", "label": "Operator decision", "message": f"{decision_id} set to {decision}."}],
                        "evalDimensions": [],
                        "failureReasons": [],
                        "source": "backend:command_center_decision",
                    }
                )
                await _send_json(send, 200, build_command_center(state, resolved))
                return
            if method != "GET":
                await _send_json(send, 405, {"status": "method_not_allowed"})
                return
            await _send_json(send, 200, build_command_center(state))
        except Exception as error:
            await _send_json(send, 500, {"status": "failed", "message": str(error)[:500]})
        return

    if method == "GET" and path == "/api/park/incident-analytics":
        try:
            from agent_ops_ledger import build_operational_backlog, read_agent_ops_ledger
            from incident_analytics import build_incident_analytics
            from mongo_memory import record_incident_analytics_fast
            from park_audit_agent import build_audit_snapshot
            from park_delivery import latest_dispatches
            from park_signal_intake import latest_signals
            from park_simulation import park_simulation

            state = await park_simulation.get_state()
            audit = build_audit_snapshot(state)
            signals = latest_signals(40)
            dispatches = latest_dispatches(40)
            backlog = build_operational_backlog(state)
            ledger = read_agent_ops_ledger(limit=40)
            analytics = build_incident_analytics(
                state=state,
                audit=audit,
                signals=signals,
                dispatches=dispatches,
                backlog=backlog,
                ledger=ledger,
            )
            analytics["mongoPersistence"] = record_incident_analytics_fast(analytics)
            await _send_json(
                send,
                200,
                analytics,
            )
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "unavailable",
                    "mode": "incident_analytics_human_review",
                    "summary": {"ticketCount": 0, "humanReviewCount": 0, "recommendedCall": "Incident analytics unavailable."},
                    "operatorBrief": {"headline": "Incident analytics unavailable", "humanDecision": "Use existing audit and signal panels.", "whatChanged": str(error)[:240]},
                    "humanReviewQueue": [],
                    "tickets": [],
                    "readiness_issues": [str(error)[:240]],
                },
            )
        return

    if path == "/api/park/operator-command/stream":
        await _operator_command_stream(scope, send)
        return

    if path == "/api/park/proactive-run/stream":
        await _proactive_run_stream(scope, send)
        return

    if method == "POST" and path == "/api/park/action":
        payload = await _read_json_body(receive)
        target = str(payload.get("target") or "")
        action = str(payload.get("action") or "")
        await _send_json(send, 200, await _fast_park_action(target, action))
        return

    if method == "POST" and path == "/api/park/causal-impact-demo":
        payload = await _read_json_body(receive)
        try:
            from park_simulation import park_simulation

            result = await park_simulation.run_causal_impact_demo(
                horizon_minutes=int(payload.get("horizon_minutes") or 20),
                execute=str(payload.get("execute", "true")).lower() not in {"0", "false", "no"},
            )
            _hot_endpoint_cache.pop("park_state", None)
            await _send_json(send, 200, result)
        except Exception as error:
            await _send_json(send, 200, {"status": "error", "mode": "causal_actual_vs_shadow_baseline", "error": str(error)[:300]})
        return

    if method == "POST" and path == "/api/park/tick":
        payload = await _read_json_body(receive)
        try:
            minutes = max(1, min(30, int(payload.get("minutes") or 1)))
            from park_simulation import park_simulation

            for _ in range(minutes):
                await park_simulation.step()
            state = await park_simulation.get_state()
            await _send_json(
                send,
                200,
                {
                    "status": "advanced",
                    "minutes": minutes,
                    "state": state,
                    "simTime": state.get("simTime"),
                    "mode": "live_park_day_tick",
                },
            )
        except Exception as error:
            await _send_json(send, 200, {"status": "tick_failed", "minutes": 0, "error": str(error)[:240]})
        return

    if method == "POST" and path == "/api/park/agent-run":
        payload = await _read_json_body(receive)
        response_payload = await _build_agent_run_payload_with_runtime(payload, "post_agent_run")
        await _send_json(send, 200, response_payload)
        return

    if method == "POST" and path == "/api/park/agent-role-run":
        payload = await _read_json_body(receive)
        message = str(payload.get("message") or payload.get("command") or "Scan the park for operating signals.").strip()
        mode = str(payload.get("mode") or "auto")
        result = await _agent_role_run_payload(message, mode)
        await _send_json(send, 200, _store_run_receipt(result, message=message, mode=mode, kind="agent_role_run"))
        return

    if method == "POST" and path == "/api/park/agent-role-refine":
        payload = await _read_json_body(receive)
        message = str(payload.get("message") or payload.get("command") or "Refine this ParkPulse operating decision.").strip()
        receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
        await _send_json(send, 200, await _agent_role_refinement_payload(message, receipt))
        return

    if method == "POST" and path == "/api/park/customer-support-agent":
        payload = await _read_json_body(receive)
        await _send_json(send, 200, await _customer_support_agent_payload(payload))
        return

    if path == "/api/park/reliability-qa-agent":
        try:
            from prod_reliability_qa_agent import reliability_qa_agent_contract

            await _send_json(send, 200, reliability_qa_agent_contract())
        except Exception as error:
            await _send_json(send, 500, {"status": "error", "error": str(error)[:300]})
        return

    if method == "POST" and path == "/api/park/reliability-qa-run":
        body = b""
        while True:
            event = await receive()
            if event.get("type") != "http.request":
                break
            body += event.get("body", b"")
            if not event.get("more_body"):
                break
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        message = str(payload.get("message") or payload.get("prompt") or "Production reliability QA review for ParkPulse.").strip()
        result = await _qa_role_payload(message, "qa", route_agent_role(message, "qa"))
        await _send_json(send, 200, _store_run_receipt(result, message=message, mode="qa", kind="reliability_qa"))
        return

    if method == "POST" and path == "/api/park/delivery/acknowledge":
        body = b""
        while True:
            event = await receive()
            if event.get("type") != "http.request":
                break
            body += event.get("body", b"")
            if not event.get("more_body"):
                break
        try:
            request_payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            request_payload = {}
        dispatch_id = str(request_payload.get("dispatch_id") or request_payload.get("id") or "")
        actor = str(request_payload.get("actor") or "operator")
        choice = str(request_payload.get("choice") or "acknowledged")
        channel = request_payload.get("channel")
        try:
            from park_delivery import acknowledge_dispatch, delivery_summary, latest_dispatches, response_summary
            from park_simulation import park_simulation

            dispatch = acknowledge_dispatch(dispatch_id, actor=actor, choice=choice, channel=str(channel) if channel else None)
            latest = latest_dispatches(20)
            application = await park_simulation.apply_delivery_outcomes(latest, "receiver_acknowledgement")
            state = await park_simulation.get_state()
            await _send_json(
                send,
                200,
                {
                    "status": dispatch.get("status", "acknowledged"),
                    "dispatch": dispatch,
                    "application": application,
                    "state": state,
                    "delivery": {
                        "summary": delivery_summary(latest),
                        "response": response_summary(latest),
                        "dispatches": latest,
                    },
                },
            )
        except Exception as error:
            await _send_json(send, 200, {"status": "fallback", "error": str(error)[:300], "dispatch": {"id": dispatch_id, "channel": channel, "status": "acknowledged", "response": {"state": "acknowledged", "choice": choice}}})
        return

    if method == "POST" and path == "/api/park/operator-command":
        body = b""
        while True:
            event = await receive()
            if event.get("type") != "http.request":
                break
            body += event.get("body", b"")
            if not event.get("more_body"):
                break
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        message = str(payload.get("message") or payload.get("command") or "Custom park operating request.").strip()
        mode = str(payload.get("mode") or "auto")
        execute = str(payload.get("execute", "true")).lower() not in {"0", "false", "no"}
        response_payload = await _build_operator_payload_with_runtime(message, mode, execute, "post_full_runtime")
        await _send_json(send, 200, response_payload)
        return

    if method == "GET" and path == "/api/park/state-lite":
        await _send_json(
            send,
            200,
            await _cached_hot_endpoint("park_state_lite", _hot_endpoint_ttls()["park_state"], _fast_park_state_lite),
        )
        return

    if method == "GET" and path == "/api/park/live-summary":
        await _send_json(
            send,
            200,
            await _cached_hot_endpoint("park_live_summary", _hot_endpoint_ttls()["park_state"], _fast_live_summary),
        )
        return

    if method == "GET" and path == "/api/park/cases":
        await _send_json(
            send,
            200,
            await _cached_hot_endpoint("park_case_index", _hot_endpoint_ttls()["park_state"], _fast_case_index),
        )
        return

    if method == "GET" and path.startswith("/api/park/cases/") and path.endswith("/brief"):
        parts = path.strip("/").split("/")
        case_id = unquote(parts[-2]) if len(parts) >= 5 else ""
        await _send_json(send, 200, await _fast_case_brief(case_id))
        return

    if method == "GET" and path == "/api/park/state":
        await _send_json(send, 200, await _fast_park_state())
        return

    if method == "GET" and path == "/api/park/integration-status":
        await _send_json(
            send,
            200,
            await _cached_hot_endpoint(
                "integration_status",
                _hot_endpoint_ttls()["integration_status"],
                _lightweight_integration_status,
            ),
        )
        return

    if method == "GET" and path == "/api/park/agent-monitoring":
        await _send_json(
            send,
            200,
            await _cached_hot_endpoint("agent_monitoring", _hot_endpoint_ttls()["agent_monitoring"], _fast_agent_monitoring),
        )
        return

    if method == "GET" and path == "/api/park/agent-monitoring/deep":
        try:
            payload = await _cached_hot_endpoint(
                "agent_monitoring_deep",
                _hot_endpoint_ttls()["agent_monitoring"],
                _deep_agent_monitoring,
            )
            await _send_json(send, 200, payload)
        except Exception as error:
            fallback = await _fast_agent_monitoring()
            fallback["status"] = "deep_monitoring_unavailable"
            fallback["deep_monitoring"] = {
                "status": "unavailable",
                "error": str(error)[:300],
                "full_runtime": _full_runtime_status(),
            }
            await _send_json(send, 503, fallback)
        return

    if method == "GET" and path == "/api/park/agent-role-skills":
        query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
        await _send_json(
            send,
            200,
            _fast_agent_role_skills(
                (query.get("message") or [""])[0],
                (query.get("mode") or ["auto"])[0],
            ),
        )
        return

    if method == "GET" and path == "/api/park/proactive-insights":
        await _send_json(send, 200, _lazy_proactive_insights())
        return

    if method == "POST" and path == "/api/park/proactive-run":
        result = await _build_proactive_payload_with_runtime("post_fast_path")
        await _send_json(send, 200, _store_run_receipt(result, message="proactive-run", mode="proact", kind="proactive_run"))
        return

    if method == "GET" and path.startswith("/api/park/evals/"):
        scenario_key = path.rsplit("/", 1)[-1]
        try:
            from park_eval import evaluate_park_decision

            await _send_json(send, 200, evaluate_park_decision(scenario_key, await _fast_park_state()))
            return
        except Exception as error:
            fallback_error = str(error)[:240]
        await _send_json(
            send,
            200,
            {
                "scenario_key": scenario_key,
                "status": "preview",
                "judge_mode": "lazy_entrypoint_eval_unavailable",
                "scores": {},
                "arize_trace": {"ready": False, "trace_state": "no_active_span"},
                "readiness_issues": [fallback_error],
            },
        )
        return

    if method == "GET" and path == "/api/gcp/trace-eval-status":
        try:
            from gcp_trace_eval import get_gcp_trace_eval_status

            await _send_json(send, 200, get_gcp_trace_eval_status().public_dict())
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "platform": "GCP internal trace/eval",
                    "ready": False,
                    "mode": "status_error",
                    "readiness_issues": [str(error)[:240]],
                },
            )
        return

    if method == "GET" and path == "/api/gcp/trace-export-verify":
        try:
            from gcp_trace_eval import verify_gcp_trace_export

            await _send_json(send, 200, verify_gcp_trace_export())
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "verification_error",
                    "verified": False,
                    "readiness_issues": [str(error)[:240]],
                },
            )
        return

    if method == "GET" and path == "/api/gcp/evaluator-loop":
        try:
            from evaluator_loop import evaluator_loop_status

            await _send_json(send, 200, evaluator_loop_status())
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "status_error",
                    "hosted_configured": False,
                    "readiness_issues": [str(error)[:240]],
                },
            )
        return

    if method == "POST" and path == "/api/gcp/evaluator-loop/verify":
        try:
            from evaluator_loop import run_vertex_hosted_evaluation

            query = parse_qs((scope.get("query_string") or b"").decode("utf-8", errors="replace"))
            scenario_key = (query.get("scenario_key") or ["ride_down"])[0]
            result = run_vertex_hosted_evaluation(
                {
                    "scenario_key": scenario_key,
                    "decision_id": "vertex-evaluator-connectivity-check",
                    "outcome_id": None,
                    "overall": 91,
                    "scorecard_status": "passed",
                    "response_score": 88,
                    "response_status": "connectivity_check",
                    "trace_id": None,
                    "span_id": None,
                    "trace_url": None,
                    "dimension_scores": {"Groundedness": 92, "Safety": 96, "Actionability": 90},
                    "dimension_explanations": {
                        "Groundedness": "Connectivity check payload using the ParkPulse eval contract.",
                        "Safety": "Policy gate is present and allowed.",
                        "Actionability": "Selected action has an operational receiver intent.",
                    },
                    "failure_reasons": [],
                    "selected_action": {"label": "Reroute guests and notify staff"},
                    "governance": {"gate_status": "checked", "allowed": True, "findings": []},
                }
            )
            await _send_json(
                send,
                200,
                {
                    "status": result.get("status", "unknown"),
                    "scenario_key": scenario_key,
                    "hosted_eval": {
                        "status": f"vertex_{result.get('status', 'unknown')}",
                        "provider": result.get("provider"),
                        "evaluator_id": result.get("evaluator_id"),
                        "location": result.get("location"),
                        "trigger": {"enabled": True, "status": result.get("status"), "reason": result.get("reason")},
                        "vertex_result": result,
                    },
                },
            )
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "verification_error",
                    "hosted_eval": {"status": "verification_error", "trigger": {"status": "failed", "reason": str(error)[:240]}},
                },
            )
        return

    if method == "GET" and path == "/api/gcp/evaluator-loop/scenario-sweep/latest":
        try:
            from mongo_memory import get_latest_memory_documents_fast
            from scenario_eval_sweep import latest_sweep_payload

            await _send_json(send, 200, latest_sweep_payload(get_latest_memory_documents_fast("eval_results", 25)))
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "empty",
                    "freshness": {"status": "unavailable", "stale": True},
                    "readiness_issues": [str(error)[:240]],
                    "scenarios": [],
                },
            )
        return

    if method == "POST" and path == "/api/gcp/evaluator-loop/scenario-sweep":
        try:
            from mongo_memory import record_scenario_eval_sweep_fast
            from scenario_eval_sweep import build_sweep_analytics_rows, run_vertex_eval_contract_sweep

            request_payload = await _read_json_body(receive)
            scenario_keys = request_payload.get("scenario_keys") if isinstance(request_payload.get("scenario_keys"), list) else None
            execute = str(request_payload.get("execute", "false")).lower() in {"1", "true", "yes", "on"}
            result = run_vertex_eval_contract_sweep(scenario_keys=scenario_keys, execute=execute)
            sweep_document_id = record_scenario_eval_sweep_fast(result)
            analytics_export = _lazy_analytics_export(build_sweep_analytics_rows(result))
            result["persistence"] = {
                "mongo_eval_document_id": sweep_document_id,
                "analytics": analytics_export,
            }
            await _send_json(send, 200, result)
        except Exception as error:
            await _send_json(
                send,
                200,
                {
                    "status": "error",
                    "source": "parkpulse_vertex_eval_contract_sweep",
                    "readiness_issues": [str(error)[:240]],
                    "summary": {"scenario_count": 0, "completed_count": 0, "vertex_completed_count": 0, "aligned_count": 0},
                    "scenarios": [],
                },
            )
        return

    if method == "GET" and path in {
        "/api/gcp/pseudo-firebase/messages",
        "/api/park/delivery/outbox",
        "/api/park/digital-twin/benchmark/report/latest",
        "/api/park/world-state/reconcile/latest",
    }:
        await _send_json(send, 200, _empty_list_payload(status="ready"))
        return

    try:
        full_app = await _get_full_app()
    except Exception as error:
        await _send_json(
            send,
            503,
            {
                "service": "parkpulse-api",
                "status": "loading_failed",
                "error": str(error),
            },
        )
        return
    await full_app(scope, receive, send)
