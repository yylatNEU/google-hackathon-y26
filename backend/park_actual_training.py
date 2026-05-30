from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any

from bigquery_analytics import bigquery_status, online_improvement_status
from mongo_memory import get_operational_memory_dashboard


MIN_ACTUAL_TRAINING_ROWS = 3
GENERATED_SOURCE_PATTERNS = ("seed", "synthetic", "demo", "validation")
_LAST_BQML_TRAINING: dict[str, Any] = {}


def actual_training_status(min_rows: int = MIN_ACTUAL_TRAINING_ROWS, run_gcp_training: bool | None = None) -> dict[str, Any]:
    dashboard = get_operational_memory_dashboard("actual outcome training reward policy gate follow through")
    memory_rows = _memory_training_rows(dashboard)
    bq = bigquery_status()
    bq_rows, bq_error = _bigquery_training_rows(bq)
    rows = bq_rows or memory_rows
    source = "bigquery_outcome_events" if bq_rows else "mongodb_outcome_events" if memory_rows else "none"
    sample_count = len(rows)
    gcp_training_enabled = _env_bool("PARKPULSE_ENABLE_GCP_ML_TRAINING")
    requested_gcp_training = bool(run_gcp_training)
    gcp_training = _run_bigquery_ml_training(bq, True) if requested_gcp_training and gcp_training_enabled else _gcp_training_not_started(bq)
    model = _train_contextual_bandit(rows)
    readiness_issues: list[str] = []
    if sample_count < min_rows:
        readiness_issues.append(f"Need at least {min_rows} observed outcome rows; found {sample_count}.")
    if bq_error:
        readiness_issues.append(f"BigQuery training row query failed: {bq_error}")
    if requested_gcp_training and not gcp_training_enabled:
        readiness_issues.append("PARKPULSE_ENABLE_GCP_ML_TRAINING is not enabled.")
    if requested_gcp_training and gcp_training_enabled and gcp_training.get("status") not in {"started", "recently_started"}:
        readiness_issues.extend(gcp_training.get("readiness_issues", []))

    return {
        "status": "ready" if sample_count >= min_rows else "not_ready",
        "mode": "actual_outcome_training",
        "uses_generated_data": False,
        "source": source,
        "sample_count": sample_count,
        "min_sample_count": min_rows,
        "model": model,
        "training_rows": rows[:12],
        "gcp_ml": {
            "online_improvement": online_improvement_status(),
            "bigquery": bq,
            "bigquery_ml_training": gcp_training,
            "bigquery_ml_training_enabled": gcp_training_enabled,
        },
        "debug": {
            "readiness_issues": readiness_issues,
            "memory_rows_available": len(memory_rows),
            "bigquery_rows_available": len(bq_rows),
            "memory_status": dashboard.get("status", {}),
        },
    }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _scenario_key(row: dict[str, Any]) -> str:
    state_scenario = row.get("stateScenario", {}) if isinstance(row.get("stateScenario"), dict) else {}
    return str(row.get("scenario_key") or state_scenario.get("key") or row.get("scenario") or "unknown")


def _policy_key(row: dict[str, Any]) -> str:
    learning = row.get("learning", {}) if isinstance(row.get("learning"), dict) else {}
    state_impact = row.get("stateImpact", {}) if isinstance(row.get("stateImpact"), dict) else {}
    after = state_impact.get("after", {}) if isinstance(state_impact.get("after"), dict) else {}
    active_policy = after.get("active_policy") or after.get("activePolicy")
    signal = learning.get("take_rate_signal") or learning.get("policy") or row.get("mode") or active_policy
    return str(signal or "observed_policy").lower().replace(" ", "_")[:90]


def _is_actual_training_source(value: Any) -> bool:
    source = str(value or "").strip().lower()
    return not any(pattern in source for pattern in GENERATED_SOURCE_PATTERNS)


def _row_reward(row: dict[str, Any]) -> float:
    response = row.get("responseMetrics", {}) if isinstance(row.get("responseMetrics"), dict) else {}
    scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
    state_impact = row.get("stateImpact", {}) if isinstance(row.get("stateImpact"), dict) else {}
    response_score = _float(response.get("score") or scorecard.get("response_score"))
    overall = _float(scorecard.get("overall"))
    state_score = _float(scorecard.get("state_movement_score"))
    take_rate = _float(response.get("takeRate")) * 100
    follow_rate = _float(response.get("reactiveFollowThroughRate") or response.get("followThroughRate")) * 100
    density_delta = _float(state_impact.get("density_delta"))
    congestion_delta = _float(state_impact.get("congestion_delta"))
    relief_bonus = max(0.0, -density_delta) * 0.35 + max(0.0, -congestion_delta) * 0.25
    return round(overall * 0.36 + response_score * 0.24 + state_score * 0.18 + take_rate * 0.12 + follow_rate * 0.1 + relief_bonus, 2)


def _memory_training_rows(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in dashboard.get("latest_outcomes", []) if isinstance(dashboard.get("latest_outcomes"), list) else []:
        if not isinstance(row, dict):
            continue
        if not _is_actual_training_source(row.get("source") or row.get("mode") or row.get("agentId")):
            continue
        response = row.get("responseMetrics", {}) if isinstance(row.get("responseMetrics"), dict) else {}
        scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
        reward = _row_reward(row)
        if reward <= 0:
            continue
        rows.append(
            {
                "row_id": row.get("_id"),
                "decision_id": row.get("decisionId"),
                "source": "mongodb_outcome_events",
                "scenario_key": _scenario_key(row),
                "policy_key": _policy_key(row),
                "reward": reward,
                "overall": _float(scorecard.get("overall")),
                "response_score": _float(response.get("score") or scorecard.get("response_score")),
                "take_rate": _float(response.get("takeRate")),
                "follow_through_rate": _float(response.get("reactiveFollowThroughRate") or response.get("followThroughRate")),
                "created_at": row.get("createdAt"),
            }
        )
    return rows


def _train_contextual_bandit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_context: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        policy = str(row.get("policy_key") or "observed_policy")
        context = str(row.get("scenario_key") or "unknown")
        reward = _float(row.get("reward"))
        by_policy[policy].append(row)
        by_context[context][policy].append(reward)

    policies = []
    for policy, policy_rows in by_policy.items():
        rewards = [_float(item.get("reward")) for item in policy_rows]
        policies.append(
            {
                "policy_id": policy,
                "sample_count": len(policy_rows),
                "average_reward": round(sum(rewards) / max(1, len(rewards)), 2),
                "best_reward": round(max(rewards), 2),
                "latest_reward": round(rewards[0], 2),
            }
        )
    policies.sort(key=lambda item: (item["average_reward"], item["sample_count"]), reverse=True)
    context_values = []
    for context, values_by_policy in by_context.items():
        ranked = sorted(
            (
                {
                    "policy_id": policy,
                    "q_value": round(sum(values) / max(1, len(values)), 2),
                    "sample_count": len(values),
                }
                for policy, values in values_by_policy.items()
            ),
            key=lambda item: (item["q_value"], item["sample_count"]),
            reverse=True,
        )
        context_values.append({"context": context, "ranked_policies": ranked})
    context_values.sort(key=lambda item: item["context"])
    return {
        "type": "actual_contextual_bandit_reward_model",
        "update_rule": "Q(context, policy) = average observed reward from outcome_events",
        "best_policy_id": policies[0]["policy_id"] if policies else None,
        "ranked_policies": policies,
        "context_values": context_values,
        "authority": "Ranks candidate policies only; dispatch still requires policy/eval gate and human review when required.",
    }


def _bigquery_training_rows(status: dict[str, Any], limit: int = 200) -> tuple[list[dict[str, Any]], str | None]:
    if not status.get("ready"):
        return [], None
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=status.get("project"))
        query = f"""
        SELECT
          outcome_id AS row_id,
          decision_id,
          scenario_key,
          COALESCE(NULLIF(source, ''), 'observed_policy') AS policy_key,
          response_score,
          overall_eval_score AS overall,
          take_rate,
          follow_through_rate,
          exported_at AS created_at
        FROM `{status['project']}.{status['dataset']}.outcome_events`
        WHERE (response_score IS NOT NULL OR overall_eval_score IS NOT NULL)
          AND NOT REGEXP_CONTAINS(LOWER(COALESCE(source, '')), r'(seed|synthetic|demo|validation)')
        ORDER BY exported_at DESC
        LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)])
        timeout = max(0.5, _float(os.getenv("BIGQUERY_QUERY_TIMEOUT_SECONDS"), 2.0))
        try:
            result = client.query(query, job_config=job_config, timeout=timeout).result(timeout=timeout)
        except TypeError:
            result = client.query(query, job_config=job_config).result()
        rows = []
        for row in result:
            item = dict(row)
            reward = round(
                _float(item.get("overall")) * 0.42
                + _float(item.get("response_score")) * 0.28
                + _float(item.get("take_rate")) * 100 * 0.16
                + _float(item.get("follow_through_rate")) * 100 * 0.14,
                2,
            )
            if reward <= 0:
                continue
            rows.append(
                {
                    "row_id": item.get("row_id"),
                    "decision_id": item.get("decision_id"),
                    "source": "bigquery_outcome_events",
                    "scenario_key": item.get("scenario_key") or "unknown",
                    "policy_key": str(item.get("policy_key") or "observed_policy").lower().replace(" ", "_")[:90],
                    "reward": reward,
                    "overall": _float(item.get("overall")),
                    "response_score": _float(item.get("response_score")),
                    "take_rate": _float(item.get("take_rate")),
                    "follow_through_rate": _float(item.get("follow_through_rate")),
                    "created_at": str(item.get("created_at")) if item.get("created_at") else None,
                }
            )
        return rows, None
    except Exception as error:  # pragma: no cover - depends on live GCP credentials
        return [], str(error)


def _gcp_training_not_started(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "not_started",
        "enabled": False,
        "ready": bool(status.get("ready")),
        "tool": "BigQuery ML",
        "model_id": _bqml_model_id(status),
        "start_condition": "Set PARKPULSE_ENABLE_GCP_ML_TRAINING=true with BigQuery credentials to start a real BQML training job.",
        "readiness_issues": [] if status.get("ready") else status.get("readiness_issues", []),
        "sql": _bqml_training_sql(status) if status.get("project") and status.get("dataset") else None,
    }


def _bqml_model_id(status: dict[str, Any]) -> str | None:
    project = status.get("project")
    dataset = status.get("dataset")
    if not project or not dataset:
        return None
    return f"{project}.{dataset}.parkpulse_policy_reward_model"


def _bqml_training_sql(status: dict[str, Any]) -> str:
    model_id = _bqml_model_id(status) or "PROJECT.DATASET.parkpulse_policy_reward_model"
    table_prefix = f"{status.get('project', 'PROJECT')}.{status.get('dataset', 'DATASET')}"
    return f"""
CREATE OR REPLACE MODEL `{model_id}`
OPTIONS(model_type='linear_reg', input_label_cols=['reward'])
AS
SELECT
  COALESCE(o.response_score, 0) * 0.35
    + COALESCE(o.overall_eval_score, 0) * 0.35
    + COALESCE(o.take_rate, 0) * 100 * 0.15
    + COALESCE(o.follow_through_rate, 0) * 100 * 0.15 AS reward,
  o.scenario_key,
  COALESCE(d.channel, d.target_system, o.source, 'observed_policy') AS action_channel,
  COALESCE(o.take_rate, 0) AS take_rate,
  COALESCE(o.follow_through_rate, 0) AS follow_through_rate
FROM `{table_prefix}.outcome_events` AS o
LEFT JOIN `{table_prefix}.action_dispatches` AS d
USING (decision_id, outcome_id, scenario_key)
WHERE (o.response_score IS NOT NULL OR o.overall_eval_score IS NOT NULL)
  AND NOT REGEXP_CONTAINS(LOWER(COALESCE(o.source, '')), r'(seed|synthetic|demo|validation)')
""".strip()


def _run_bigquery_ml_training(status: dict[str, Any], enabled: bool) -> dict[str, Any]:
    base = _gcp_training_not_started(status)
    base["enabled"] = enabled
    if not enabled:
        return base
    if not status.get("ready"):
        return {
            **base,
            "status": "not_ready",
            "readiness_issues": status.get("readiness_issues", []),
        }
    model_id = _bqml_model_id(status)
    now = time.time()
    recent_window_seconds = _float(os.getenv("PARKPULSE_BQML_RETRAIN_COOLDOWN_SECONDS"), 900)
    if (
        _LAST_BQML_TRAINING.get("model_id") == model_id
        and now - float(_LAST_BQML_TRAINING.get("started_at", 0) or 0) < recent_window_seconds
    ):
        return {
            "status": "recently_started",
            "enabled": True,
            "ready": True,
            "tool": "BigQuery ML",
            "model_id": model_id,
            "job_id": _LAST_BQML_TRAINING.get("job_id"),
            "start_condition": f"Retrain cooldown active for {round(recent_window_seconds)}s to avoid duplicate dashboard-triggered jobs.",
            "sql": _bqml_training_sql(status),
            "readiness_issues": [],
        }
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=status.get("project"))
        sql = _bqml_training_sql(status)
        job = client.query(sql)
        _LAST_BQML_TRAINING.update({"model_id": model_id, "job_id": getattr(job, "job_id", None), "started_at": now})
        return {
            "status": "started",
            "enabled": True,
            "ready": True,
            "tool": "BigQuery ML",
            "model_id": model_id,
            "job_id": getattr(job, "job_id", None),
            "sql": sql,
            "readiness_issues": [],
        }
    except Exception as error:  # pragma: no cover - depends on live GCP credentials
        return {
            **base,
            "status": "error",
            "readiness_issues": [str(error)[:300]],
        }
