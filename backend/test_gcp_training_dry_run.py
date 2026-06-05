from __future__ import annotations

import asyncio
import json

import main
from park_role_access import sign_role_session


def run(coro):
    return asyncio.run(coro)


async def call_app(method: str, path: str, body: dict | None = None, headers: dict[str, str] | None = None):
    sent = []
    received = False
    body_bytes = json.dumps(body or {}).encode("utf-8")

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    async def send(message):
        sent.append(message)

    header_rows = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
    await main.app({"type": "http", "method": method, "path": path, "query_string": b"", "headers": header_rows}, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(response_body or b"{}")


def signed_headers(role: str = "ml_ops_admin") -> dict[str, str]:
    token = sign_role_session("unit-test", role, main._role_auth_secret(), ttl_seconds=900)
    return {"authorization": f"Bearer {token}", "x-parkpulse-role": role}


def test_gcp_training_dry_run_times_out_slow_preflight(monkeypatch):
    async def slow_preflight(*args, **kwargs):
        await asyncio.sleep(0.2)
        return {"status": "ready", "mode": "training_live_feed_preflight"}

    monkeypatch.setenv("PARKPULSE_GCP_TRAINING_DRY_RUN_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(main, "_training_live_feed_preflight_payload", slow_preflight)

    status, payload = run(call_app("POST", "/api/park/gcp-training-dry-run", {}, signed_headers()))

    assert status == 200
    assert payload["status"] == "blocked"
    assert payload["live_feed_preflight"]["status"] == "timeout"
    assert payload["gcp_training_started"] is False
    assert payload["model_promotion_started"] is False


def test_gcp_training_dry_run_does_not_refresh_live_feeds_by_default(monkeypatch):
    seen = {}

    async def fast_preflight(request_payload=None, *, default_refresh=True):
        seen["default_refresh"] = default_refresh
        return {
            "status": "no_due_feeds",
            "mode": "training_live_feed_preflight",
            "refresh_status": "not_requested",
            "readiness_issues": [],
        }

    def fake_dry_run_readiness(min_rows=3, **kwargs):
        seen["fast_readiness"] = kwargs.get("fast_readiness")
        return {
            "status": "ready",
            "mode": "gcp_training_dry_run_readiness",
            "min_sample_count": min_rows,
            "live_feed_preflight": kwargs.get("live_feed_preflight"),
            "gcp_training_started": False,
            "model_promotion_started": False,
        }

    import park_actual_training

    monkeypatch.setattr(main, "_training_live_feed_preflight_payload", fast_preflight)
    monkeypatch.setattr(park_actual_training, "gcp_training_dry_run_readiness", fake_dry_run_readiness)

    status, payload = run(call_app("POST", "/api/park/gcp-training-dry-run", {}, signed_headers()))

    assert status == 200
    assert payload["status"] == "ready"
    assert seen["default_refresh"] is False
    assert seen["fast_readiness"] is True
    assert payload["live_feed_preflight"]["refresh_status"] == "not_requested"


def test_fast_gcp_training_dry_run_skips_slow_eval_and_training_reads(monkeypatch):
    import park_actual_training

    def fail_eval_lookup(*args, **kwargs):
        raise AssertionError("fast dry-run should not read latest controlled eval")

    def fail_training_readiness(*args, **kwargs):
        raise AssertionError("fast dry-run should not run deep training readiness")

    def fail_bigquery_status(*args, **kwargs):
        raise AssertionError("fast dry-run should not create a live BigQuery client")

    monkeypatch.setattr(park_actual_training, "_scoped_bqml_eval_gate", fail_eval_lookup)
    monkeypatch.setattr(park_actual_training, "actual_training_status", fail_training_readiness)
    monkeypatch.setattr(park_actual_training, "bigquery_status", fail_bigquery_status)

    payload = park_actual_training.gcp_training_dry_run_readiness(
        fast_readiness=True,
        live_feed_preflight={"status": "no_due_feeds", "readiness_issues": []},
    )

    assert payload["status"] == "blocked"
    assert payload["controlled_eval_gate"]["status"] == "not_checked"
    assert payload["actual_training"]["status"] == "not_checked"
    assert payload["gcp_training_started"] is False
    assert payload["model_promotion_started"] is False
