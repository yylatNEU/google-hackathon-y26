from __future__ import annotations

import os
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


bigquery = None
_bigquery_import_error: str | None = None


def _load_bigquery_module() -> Any | None:
    global bigquery, _bigquery_import_error
    if bigquery is not None:
        return bigquery
    if _bigquery_import_error is not None:
        return None
    try:
        from google.cloud import bigquery as bigquery_module
    except Exception as error:  # pragma: no cover - exercised when optional dependency is unavailable
        _bigquery_import_error = str(error)
        return None
    bigquery = bigquery_module
    return bigquery


ANALYTICS_TABLES = [
    {
        "name": "agent_decisions",
        "purpose": "Historical decision quality, selected actions, agents involved, and score trends.",
        "agent_use": "Find which decision patterns score well for a scenario before choosing a new plan.",
    },
    {
        "name": "action_dispatches",
        "purpose": "Guest, worker, and equipment action payloads with delivery status.",
        "agent_use": "Compare which channels and message styles actually produce response.",
    },
    {
        "name": "outcome_events",
        "purpose": "Take rate, follow-through, worker acknowledgments, equipment success, and state movement.",
        "agent_use": "Retrieve aggregate outcome priors such as expected take rate by zone, scenario, and action type.",
    },
    {
        "name": "eval_results",
        "purpose": "GCP/local judge scores and failure modes across runs.",
        "agent_use": "Tune prompts and policies from repeated low-scoring eval dimensions.",
    },
    {
        "name": "event_plan_versions",
        "purpose": "Temporary event plans, revisions, staffing estimates, equipment moves, and judge deltas.",
        "agent_use": "Learn which event layouts reduce bottlenecks or improve revenue without raising staff stress.",
    },
    {
        "name": "training_episodes",
        "purpose": "Signal patterns, state-before snapshots, agent actions, policy gates, outcomes, and labels for retrieval/eval.",
        "agent_use": "Retrieve prior episodes that match the current signal mix and prefer actions with better observed outcomes.",
    },
    {
        "name": "dream_eval_results",
        "purpose": "Archived retired AutoDream counterfactual lessons, confidence, review status, and promotion outcomes.",
        "agent_use": "Archive-only inspection; retired dream-generated lessons are not promoted into live use.",
    },
]

ANALYTICS_TABLE_SCHEMAS = {
    "action_dispatches": [
        ("exported_at", "TIMESTAMP"),
        ("decision_id", "STRING"),
        ("outcome_id", "STRING"),
        ("scenario_key", "STRING"),
        ("source", "STRING"),
        ("dispatch_id", "STRING"),
        ("channel", "STRING"),
        ("target_system", "STRING"),
        ("status", "STRING"),
        ("take_rate", "FLOAT"),
        ("positive_response_rate", "FLOAT"),
        ("follow_through_rate", "FLOAT"),
    ],
    "outcome_events": [
        ("exported_at", "TIMESTAMP"),
        ("decision_id", "STRING"),
        ("outcome_id", "STRING"),
        ("scenario_key", "STRING"),
        ("source", "STRING"),
        ("take_rate", "FLOAT"),
        ("positive_response_rate", "FLOAT"),
        ("follow_through_rate", "FLOAT"),
        ("response_score", "FLOAT"),
        ("overall_eval_score", "FLOAT"),
        ("learning_signal", "STRING"),
        ("state_impact", "STRING"),
    ],
    "eval_results": [
        ("exported_at", "TIMESTAMP"),
        ("decision_id", "STRING"),
        ("outcome_id", "STRING"),
        ("scenario_key", "STRING"),
        ("source", "STRING"),
        ("overall", "FLOAT"),
        ("response_score", "FLOAT"),
        ("status", "STRING"),
        ("trace_id", "STRING"),
        ("span_id", "STRING"),
        ("trace_url", "STRING"),
        ("trace_state", "STRING"),
        ("judge_mode", "STRING"),
        ("evaluation_status", "STRING"),
        ("hosted_evaluator_id", "STRING"),
        ("vertex_score", "FLOAT"),
        ("vertex_status", "STRING"),
        ("vertex_transport", "STRING"),
        ("vertex_explanation", "STRING"),
        ("policy_gate_status", "STRING"),
        ("needs_human_approval", "BOOLEAN"),
        ("dimensions_json", "STRING"),
        ("dimension_scores_json", "STRING"),
        ("dimension_explanations_json", "STRING"),
        ("failure_reasons_json", "STRING"),
    ],
    "training_episodes": [
        ("exported_at", "TIMESTAMP"),
        ("episode_id", "STRING"),
        ("incident_type", "STRING"),
        ("zone", "STRING"),
        ("risk_level", "STRING"),
        ("confidence", "FLOAT"),
        ("source_count", "INTEGER"),
        ("good_escalation", "BOOLEAN"),
        ("false_alarm", "BOOLEAN"),
        ("actionable", "BOOLEAN"),
        ("grounded", "BOOLEAN"),
    ],
    "dream_eval_results": [
        ("exported_at", "TIMESTAMP"),
        ("dream_run_id", "STRING"),
        ("dream_learning_id", "STRING"),
        ("scenario_key", "STRING"),
        ("outcome_label", "STRING"),
        ("confidence", "FLOAT"),
        ("prior_source", "STRING"),
        ("review_status", "STRING"),
        ("promoted", "BOOLEAN"),
        ("lesson", "STRING"),
        ("rule", "STRING"),
    ],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _client_status() -> tuple[Any | None, list[str]]:
    issues: list[str] = []
    bigquery_module = _load_bigquery_module()
    if bigquery_module is None:
        issues.append(_bigquery_import_error or "google-cloud-bigquery is not importable.")
        return None, issues

    project = os.getenv("BIGQUERY_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    dataset = os.getenv("BIGQUERY_DATASET", "parkpulse_analytics")
    if not project:
        issues.append("BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT is not set.")
    if not dataset:
        issues.append("BIGQUERY_DATASET is not set.")
    if issues:
        return None, issues

    try:
        return bigquery_module.Client(project=project), []
    except Exception as error:  # pragma: no cover - depends on local credentials
        return None, [str(error)]


def bigquery_status() -> dict[str, Any]:
    project = os.getenv("BIGQUERY_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    dataset = os.getenv("BIGQUERY_DATASET", "parkpulse_analytics")
    enabled = _env_bool("ENABLE_BIGQUERY_ANALYTICS")
    client, issues = _client_status() if enabled else (None, ["ENABLE_BIGQUERY_ANALYTICS is not enabled."])
    return {
        "platform": "BigQuery",
        "role": "historical analytics and aggregate learning, not real-time operational memory",
        "enabled": enabled,
        "ready": enabled and client is not None,
        "project": project,
        "dataset": dataset,
        "location": os.getenv("BIGQUERY_LOCATION", "US"),
        "auto_create_tables": _env_bool("BIGQUERY_AUTO_CREATE_TABLES", True),
        "mode": "bigquery" if enabled and client is not None else "analytics_fallback",
        "tables": deepcopy(ANALYTICS_TABLES),
        "readiness_issues": issues,
        "agent_operation_fit": [
            "MongoDB/Firestore holds live state and short-term memory.",
            "BigQuery stores many runs for trend analysis and prompt/eval improvement.",
            "Agents use BigQuery summaries as priors, not as the millisecond decision store.",
        ],
    }


def online_improvement_status() -> dict[str, Any]:
    provider = os.getenv("PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER", "gcp").strip().lower() or "gcp"
    bq = bigquery_status()
    vertex_eval_enabled = _env_bool("ENABLE_VERTEX_GENAI_EVAL")
    ready = provider == "gcp" and bq["ready"]
    return {
        "provider": provider,
        "primary_path": "gcp_bigquery",
        "ready": ready,
        "mode": "online_gcp" if ready else "local_scorecard_with_gcp_export_preview",
        "blocking": False,
        "bigquery": bq,
        "vertex_genai_evaluation": {
            "enabled": vertex_eval_enabled,
            "mode": "available_for_batch_agent_eval" if vertex_eval_enabled else "not_enabled",
            "role": "batch and regression evaluation; local scorecards remain the request-time guardrail",
        },
        "arize_policy": {
            "role": "optional external trace sink",
            "blocking": False,
            "default_for_online_improvement": False,
        },
        "loop": [
            "Store each decision, dispatch, outcome, and local scorecard in operational memory.",
            "Mirror compact analytics rows to BigQuery when credentials and tables are available.",
            "Retrieve aggregate outcome priors from memory/BigQuery summaries for future planning.",
            "Use Vertex Gen AI Evaluation for batch agent-quality checks when enabled.",
        ],
        "readiness_issues": [] if ready else bq["readiness_issues"],
    }


def _flatten_metric(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_column(value: Any, limit: int = 50000) -> str | None:
    if value in (None, "", [], {}):
        return None
    try:
        text = json.dumps(value, default=str, sort_keys=True)
    except Exception:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 16] + "...[truncated]"


def build_analytics_rows(
    *,
    decision_id: str,
    outcome_id: str | None,
    scenario_key: str,
    delivery: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
    eval_result: dict[str, Any] | None,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    delivery = delivery or {}
    outcome = outcome or {}
    eval_result = eval_result or {}
    response = delivery.get("response", {}) if isinstance(delivery.get("response"), dict) else {}
    scorecard = eval_result.get("scorecard", {}) if isinstance(eval_result.get("scorecard"), dict) else {}
    eval_trace = eval_result.get("gcp_trace_eval", {}) if isinstance(eval_result.get("gcp_trace_eval"), dict) else {}
    judge = eval_result.get("judge", {}) if isinstance(eval_result.get("judge"), dict) else {}
    hosted_eval = eval_result.get("hosted_eval", {}) if isinstance(eval_result.get("hosted_eval"), dict) else {}
    dimension_scores = eval_result.get("dimension_scores")
    if not isinstance(dimension_scores, dict):
        dimension_scores = {
            item.get("label"): item.get("score")
            for item in eval_result.get("evals", [])
            if isinstance(item, dict) and item.get("label")
        }
    dimension_explanations = eval_result.get("dimension_explanations")
    if not isinstance(dimension_explanations, dict):
        dimension_explanations = {
            item.get("label"): item.get("detail")
            for item in eval_result.get("evals", [])
            if isinstance(item, dict) and item.get("label")
        }
    failure_reasons = scorecard.get("failure_reasons") or eval_result.get("failure_reasons")
    if not isinstance(failure_reasons, list):
        failure_reasons = []
    vertex_result = hosted_eval.get("vertex_result", {}) if isinstance(hosted_eval.get("vertex_result"), dict) else {}
    vertex_metric = vertex_result.get("result", {}) if isinstance(vertex_result.get("result"), dict) else {}
    hosted_trigger = hosted_eval.get("trigger", {}) if isinstance(hosted_eval.get("trigger"), dict) else {}
    now = _now_iso()
    dispatch_rows = []
    for dispatch in delivery.get("dispatches", []) if isinstance(delivery.get("dispatches"), list) else []:
        if not isinstance(dispatch, dict):
            continue
        dispatch_response = dispatch.get("response", {}) if isinstance(dispatch.get("response"), dict) else {}
        dispatch_rows.append(
            {
                "exported_at": now,
                "decision_id": decision_id,
                "outcome_id": outcome_id,
                "scenario_key": scenario_key,
                "source": source,
                "dispatch_id": dispatch.get("id"),
                "channel": dispatch.get("channel"),
                "target_system": dispatch.get("targetSystem"),
                "status": dispatch.get("status"),
                "take_rate": _flatten_metric(dispatch_response.get("takeRate")),
                "positive_response_rate": _flatten_metric(dispatch_response.get("positiveResponseRate")),
                "follow_through_rate": _flatten_metric(dispatch_response.get("reactiveFollowThroughRate")),
            }
        )

    return {
        "outcome_events": [
            {
                "exported_at": now,
                "decision_id": decision_id,
                "outcome_id": outcome_id,
                "scenario_key": scenario_key,
                "source": source,
                "take_rate": _flatten_metric(response.get("takeRate")),
                "positive_response_rate": _flatten_metric(response.get("positiveResponseRate")),
                "follow_through_rate": _flatten_metric(response.get("reactiveFollowThroughRate")),
                "response_score": _flatten_metric(response.get("score")),
                "overall_eval_score": _flatten_metric(scorecard.get("overall") or eval_result.get("overall")),
                "learning_signal": (outcome.get("learning", {}) if isinstance(outcome.get("learning"), dict) else {}).get("take_rate_signal"),
                "state_impact": (outcome.get("state_impact", {}) if isinstance(outcome.get("state_impact"), dict) else {}).get("headline"),
            }
        ],
        "action_dispatches": dispatch_rows,
        "eval_results": [
            {
                "exported_at": now,
                "decision_id": decision_id,
                "outcome_id": outcome_id,
                "scenario_key": scenario_key,
                "source": source,
                "overall": _flatten_metric(scorecard.get("overall") or eval_result.get("overall")),
                "response_score": _flatten_metric(scorecard.get("response_score") or response.get("score")),
                "status": scorecard.get("status") or eval_result.get("status"),
                "trace_id": eval_trace.get("trace_id"),
                "span_id": eval_trace.get("span_id"),
                "trace_url": eval_trace.get("trace_url"),
                "trace_state": eval_trace.get("trace_state"),
                "judge_mode": judge.get("mode") or hosted_eval.get("runtime"),
                "evaluation_status": eval_trace.get("evaluation_status") or hosted_eval.get("status"),
                "hosted_evaluator_id": hosted_eval.get("evaluator_id"),
                "vertex_score": _flatten_metric(vertex_metric.get("score")),
                "vertex_status": vertex_result.get("status") or hosted_trigger.get("status"),
                "vertex_transport": vertex_result.get("transport"),
                "vertex_explanation": vertex_metric.get("explanation"),
                "policy_gate_status": scorecard.get("policy_gate_status"),
                "needs_human_approval": scorecard.get("needs_human_approval"),
                "dimensions_json": _json_column(eval_trace.get("dimensions") or list(dimension_scores.keys())),
                "dimension_scores_json": _json_column(dimension_scores),
                "dimension_explanations_json": _json_column(dimension_explanations),
                "failure_reasons_json": _json_column(failure_reasons),
            }
        ],
    }


def build_dream_analytics_rows(dream_result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    now = _now_iso()
    dream_run = dream_result.get("dream_run", {}) if isinstance(dream_result.get("dream_run"), dict) else {}
    priors = dream_run.get("bigqueryPriors", {}) if isinstance(dream_run.get("bigqueryPriors"), dict) else {}
    rows = []
    for learning in dream_result.get("dream_learnings", []) if isinstance(dream_result.get("dream_learnings"), list) else []:
        if not isinstance(learning, dict):
            continue
        rows.append(
            {
                "exported_at": now,
                "dream_run_id": dream_result.get("dream_run_id") or dream_run.get("dreamRunId"),
                "dream_learning_id": learning.get("_id"),
                "scenario_key": learning.get("scenarioKey"),
                "outcome_label": learning.get("outcomeLabel"),
                "confidence": _flatten_metric(learning.get("confidence")),
                "prior_source": priors.get("source") or dream_result.get("summary", {}).get("prior_source"),
                "review_status": learning.get("reviewStatus", "pending_operator_review"),
                "promoted": bool(learning.get("promoted")),
                "lesson": learning.get("lesson"),
                "rule": learning.get("rule"),
            }
        )
    return {"dream_eval_results": rows}


def export_analytics_rows(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    status = bigquery_status()
    row_counts = {table: len(rows) for table, rows in rows_by_table.items()}
    if not status["ready"]:
        return {
            "status": "fallback_preview",
            "mode": status["mode"],
            "row_counts": row_counts,
            "readiness_issues": status["readiness_issues"],
            "preview": {table: rows[:2] for table, rows in rows_by_table.items()},
        }

    client, issues = _client_status()
    if client is None:
        return {"status": "fallback_preview", "mode": "analytics_fallback", "row_counts": row_counts, "readiness_issues": issues}

    dataset = status["dataset"]
    setup_errors = _ensure_bigquery_tables(client, status, rows_by_table.keys()) if status.get("auto_create_tables") else {}
    errors: dict[str, Any] = {}
    inserted: dict[str, int] = {}
    for table, rows in rows_by_table.items():
        if not rows:
            inserted[table] = 0
            continue
        table_id = f"{status['project']}.{dataset}.{table}"
        if table in setup_errors:
            errors[table] = setup_errors[table]
            continue
        try:
            result = client.insert_rows_json(table_id, rows)
            if result:
                errors[table] = result
            else:
                inserted[table] = len(rows)
        except Exception as error:  # pragma: no cover - depends on live BigQuery failures
            errors[table] = str(error)
    return {
        "status": "exported" if not errors else "partial_error",
        "mode": "bigquery",
        "dataset": dataset,
        "row_counts": row_counts,
        "inserted": inserted,
        "errors": errors,
    }


def _ensure_bigquery_tables(client: Any, status: dict[str, Any], table_names: Any) -> dict[str, str]:
    bigquery_module = _load_bigquery_module()
    if bigquery_module is None:
        return {"dataset": _bigquery_import_error or "google-cloud-bigquery is not importable."}

    project = status.get("project")
    dataset_name = status.get("dataset")
    location = status.get("location") or "US"
    errors: dict[str, str] = {}
    dataset_id = f"{project}.{dataset_name}"

    try:
        dataset = bigquery_module.Dataset(dataset_id)
        dataset.location = location
        client.create_dataset(dataset, exists_ok=True)
    except Exception as error:  # pragma: no cover - depends on live BigQuery permissions
        errors["dataset"] = str(error)
        return errors

    for table_name in table_names:
        schema_def = ANALYTICS_TABLE_SCHEMAS.get(str(table_name))
        if not schema_def:
            continue
        table_id = f"{dataset_id}.{table_name}"
        try:
            schema = [bigquery_module.SchemaField(name, field_type, mode="NULLABLE") for name, field_type in schema_def]
            client.create_table(bigquery_module.Table(table_id, schema=schema), exists_ok=True)
            _ensure_bigquery_table_schema(client, bigquery_module, table_id, schema_def)
        except Exception as error:  # pragma: no cover - depends on live BigQuery permissions
            errors[str(table_name)] = str(error)
    return errors


def _ensure_bigquery_table_schema(client: Any, bigquery_module: Any, table_id: str, schema_def: list[tuple[str, str]]) -> None:
    get_table = getattr(client, "get_table", None)
    update_table = getattr(client, "update_table", None)
    if get_table is None or update_table is None:
        return
    table = get_table(table_id)
    existing = {field.name for field in getattr(table, "schema", [])}
    missing = [(name, field_type) for name, field_type in schema_def if name not in existing]
    if not missing:
        return
    table.schema = list(getattr(table, "schema", [])) + [
        bigquery_module.SchemaField(name, field_type, mode="NULLABLE") for name, field_type in missing
    ]
    update_table(table, ["schema"])


def analytics_learning_summary(memory_dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    memory_dashboard = memory_dashboard or {}
    latest_outcomes = memory_dashboard.get("latest_outcomes", []) if isinstance(memory_dashboard, dict) else []
    latest_learnings = memory_dashboard.get("latest_learnings", []) if isinstance(memory_dashboard, dict) else []
    status = bigquery_status()
    return {
        "status": status,
        "loop": [
            "Operational loop writes decisions, dispatches, outcomes, and evals to MongoDB/Firestore.",
            "Analytics exporter mirrors useful rows to BigQuery.",
            "BigQuery aggregates response quality across many scenarios, zones, messages, and event plans.",
            "Agent prompt context uses aggregate priors such as take-rate by action type.",
            "Vertex Gen AI Evaluation or local scorecards use BigQuery failure cohorts to improve future prompts and policies.",
        ],
        "recommended_queries": [
            {
                "name": "message_take_rate_by_scenario",
                "question": "Which guest-message styles produce the highest take rate by scenario?",
                "sql": "SELECT scenario_key, channel, AVG(take_rate) AS avg_take_rate FROM action_dispatches GROUP BY scenario_key, channel ORDER BY avg_take_rate DESC",
            },
            {
                "name": "eval_to_followthrough_correlation",
                "question": "Do higher quality/eval response scores predict guest follow-through?",
                "sql": "SELECT APPROX_QUANTILES(response_score, 4), AVG(follow_through_rate) FROM outcome_events GROUP BY scenario_key",
            },
            {
                "name": "event_plan_revision_roi",
                "question": "Which event-plan revisions improve outcome score after measured response?",
                "sql": "SELECT scenario_key, AVG(response_score) AS avg_response_score, COUNT(*) AS runs FROM outcome_events GROUP BY scenario_key",
            },
        ],
        "latest_operational_rows_available": {
            "outcomes": len(latest_outcomes),
            "learnings": len(latest_learnings),
        },
    }


def _fallback_agent_priors(scenario: str) -> list[dict[str, Any]]:
    base_priors = {
        "ride_down": [
            {
                "cohort": "thrill_reroute_near_down_ride",
                "prior_take_rate": 0.38,
                "prior_follow_through": 0.31,
                "recommended_adjustment": "Pair alternate thrill rides with a concrete time-saving offer and keep the dead queue closed.",
            },
            {
                "cohort": "family_recovery_offer",
                "prior_take_rate": 0.57,
                "prior_follow_through": 0.49,
                "recommended_adjustment": "Use family-safe indoor destinations and food recovery instead of pushing thrill alternatives.",
            },
        ],
        "staff_shortage": [
            {
                "cohort": "break_protected_redeployment",
                "prior_take_rate": 0.74,
                "prior_follow_through": 0.68,
                "recommended_adjustment": "Protect breaks and move only cross-trained staff; worker acknowledgement stays materially higher.",
            },
            {
                "cohort": "generic_staff_move",
                "prior_take_rate": 0.44,
                "prior_follow_through": 0.36,
                "recommended_adjustment": "Avoid broad staff moves without role fit, zone, and time box.",
            },
        ],
        "food_spike": [
            {
                "cohort": "mobile_menu_suppression_plus_nearby_offer",
                "prior_take_rate": 0.63,
                "prior_follow_through": 0.55,
                "recommended_adjustment": "Suppress low-stock items and route demand to a nearby high-capacity station.",
            },
            {
                "cohort": "close_ordering_only",
                "prior_take_rate": 0.21,
                "prior_follow_through": 0.18,
                "recommended_adjustment": "Do not only close ordering; preserve guest choice with substitute items.",
            },
        ],
        "storm_response": [
            {
                "cohort": "indoor_shelter_preload",
                "prior_take_rate": 0.59,
                "prior_follow_through": 0.51,
                "recommended_adjustment": "Pre-cool indoor shelters and stagger guest app messages before outdoor closure.",
            },
            {
                "cohort": "late_weather_broadcast",
                "prior_take_rate": 0.32,
                "prior_follow_through": 0.27,
                "recommended_adjustment": "Avoid late generic weather messaging because it overloads indoor queues.",
            },
        ],
        "proactive_eventops": [
            {
                "cohort": "halloween_route_specific_offer",
                "prior_take_rate": 0.61,
                "prior_follow_through": 0.54,
                "recommended_adjustment": "Use route-specific offers by guest location; broad Halloween nudges underperform.",
            },
            {
                "cohort": "maze_entrance_food_promo",
                "prior_take_rate": 0.43,
                "prior_follow_through": 0.36,
                "recommended_adjustment": "Move food incentives to maze exit so the entrance remains flow-through.",
            },
            {
                "cohort": "worker_visible_flow_lane",
                "prior_take_rate": 0.9,
                "prior_follow_through": 0.86,
                "recommended_adjustment": "Give staff a named lane and location; worker acknowledgement rises when the task is concrete.",
            },
        ],
    }
    return deepcopy(base_priors.get(scenario, base_priors["proactive_eventops"]))


def _query_bigquery_agent_priors(status: dict[str, Any], scenario: str) -> tuple[list[dict[str, Any]], str | None]:
    if not status.get("ready"):
        return [], None
    bigquery_module = _load_bigquery_module()
    if bigquery_module is None:
        return [], _bigquery_import_error or "google-cloud-bigquery is not importable."
    client, issues = _client_status()
    if client is None:
        return [], "; ".join(issues)

    project = status.get("project")
    dataset = status.get("dataset")
    query = f"""
    WITH joined AS (
      SELECT
        o.scenario_key,
        COALESCE(NULLIF(d.channel, ''), NULLIF(d.target_system, ''), o.source, 'unknown_action') AS action_cohort,
        COALESCE(d.take_rate, o.take_rate) AS take_rate,
        COALESCE(d.follow_through_rate, o.follow_through_rate) AS follow_through_rate,
        COALESCE(o.response_score, d.positive_response_rate * 100) AS response_score
      FROM `{project}.{dataset}.outcome_events` AS o
      LEFT JOIN `{project}.{dataset}.action_dispatches` AS d
        USING (decision_id, outcome_id, scenario_key)
      WHERE o.scenario_key = @scenario_key
    )
    SELECT
      action_cohort,
      AVG(take_rate) AS prior_take_rate,
      AVG(follow_through_rate) AS prior_follow_through,
      AVG(response_score) AS avg_response_score,
      COUNT(*) AS run_count
    FROM joined
    GROUP BY action_cohort
    HAVING run_count > 0
    ORDER BY prior_take_rate DESC, prior_follow_through DESC
    LIMIT 8
    """
    try:
        job_config = bigquery_module.QueryJobConfig(
            query_parameters=[bigquery_module.ScalarQueryParameter("scenario_key", "STRING", scenario)]
        )
        try:
            query_timeout = max(0.5, float(os.getenv("BIGQUERY_QUERY_TIMEOUT_SECONDS", "1.5")))
        except ValueError:
            query_timeout = 1.5
        try:
            rows = list(client.query(query, job_config=job_config, timeout=query_timeout).result(timeout=query_timeout))
        except TypeError:
            rows = list(client.query(query, job_config=job_config).result())
    except Exception as error:  # pragma: no cover - depends on live BigQuery
        return [], str(error)

    priors: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        take_rate = float(item.get("prior_take_rate") or 0)
        follow_rate = float(item.get("prior_follow_through") or 0)
        cohort = str(item.get("action_cohort") or "unknown_action")
        priors.append(
            {
                "cohort": cohort,
                "prior_take_rate": round(take_rate, 3),
                "prior_follow_through": round(follow_rate, 3),
                "run_count": int(item.get("run_count") or 0),
                "avg_response_score": round(float(item.get("avg_response_score") or 0), 1),
                "recommended_adjustment": (
                    f"Prefer {cohort} when live constraints match; observed "
                    f"{round(take_rate * 100)}% take rate and {round(follow_rate * 100)}% follow-through."
                ),
            }
        )
    return priors, None


def build_bigquery_agent_priors(
    scenario_key: str = "proactive_eventops",
    memory_dashboard: dict[str, Any] | None = None,
    allow_live_query: bool = True,
) -> dict[str, Any]:
    """Return compact historical priors the decision agent can use as planning context."""
    memory_dashboard = memory_dashboard or {}
    status = bigquery_status()
    latest_learnings = memory_dashboard.get("latest_learnings", []) if isinstance(memory_dashboard, dict) else []
    latest_outcomes = memory_dashboard.get("latest_outcomes", []) if isinstance(memory_dashboard, dict) else []
    scenario = scenario_key or "proactive_eventops"
    queried_priors, query_error = _query_bigquery_agent_priors(status, scenario) if allow_live_query else ([], "Live BigQuery prior query skipped for latency-safe collaboration context.")
    priors = queried_priors or _fallback_agent_priors(scenario)
    best = max(priors, key=lambda item: float(item["prior_take_rate"]))
    weakest = min(priors, key=lambda item: float(item["prior_follow_through"]))
    memory_influence = []
    for item in latest_learnings[:2]:
        if isinstance(item, dict):
            memory_influence.append(str(item.get("takeRateSignal") or item.get("lesson") or item.get("rule") or item.get("_id")))
    source = "bigquery_query" if queried_priors else ("bigquery_query_fallback" if status["ready"] else "local_bigquery_contract")
    return {
        "source": source,
        "scenario_key": scenario,
        "ready": status["ready"],
        "dataset": status.get("dataset"),
        "query_name": "agent_action_priors_by_scenario",
        "rows_available": len(latest_outcomes),
        "query_error": query_error,
        "priors": priors,
        "best_prior": best,
        "weakest_prior": weakest,
        "agent_context": [
            f"Best historical pattern: {best['cohort']} at {round(float(best['prior_take_rate']) * 100)}% take rate.",
            f"Weak pattern to avoid: {weakest['cohort']} at {round(float(weakest['prior_follow_through']) * 100)}% follow-through.",
            "Use these priors as context, then still obey live state, policy, and human-approval gates.",
        ],
        "memory_influence": memory_influence,
        "sql_preview": (
            "SELECT scenario_key, action_cohort, AVG(take_rate), AVG(follow_through_rate) "
            "FROM outcome_events JOIN action_dispatches USING(decision_id, outcome_id) "
            "GROUP BY scenario_key, action_cohort"
        ),
    }
