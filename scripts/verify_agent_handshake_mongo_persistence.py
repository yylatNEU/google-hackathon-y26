#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def _http_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    body = None
    headers = {"User-Agent": "parkpulse-ahp-mongo-verifier/1.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _policy_event_count(mongo_memory: Any, session_id: str) -> int | None:
    if getattr(mongo_memory._memory, "db", None) is None:
        return None
    collection = mongo_memory._memory.db.agent_handshake_policy_events
    return int(collection.count_documents({"session_id": session_id}) + collection.count_documents({"sessionId": session_id}))


def verify(api: str, scenario_mode: str) -> dict[str, Any]:
    import env_bootstrap
    import mongo_memory

    env_bootstrap.load_backend_env()
    mongo_status = mongo_memory.init_operational_memory(force=True)
    demo_url = f"{api.rstrip('/')}/api/park/agent-handshake/supply-chain/demo"
    demo = _http_json(demo_url, {"scenario_mode": scenario_mode})
    session_id = str(demo.get("session_id") or "")
    persisted = mongo_memory.get_agent_handshake_session(session_id) if session_id else None
    receipt = demo.get("receipt") if isinstance(demo.get("receipt"), dict) else {}
    verification: dict[str, Any] = {}
    if receipt:
        verification = _http_json(
            f"{api.rstrip('/')}/api/park/agent-handshake/verify-artifact",
            {"artifact": receipt, "expected_artifact_type": "agent_handshake_session_receipt"},
        )
    passed = bool(
        mongo_status.get("connected")
        and mongo_status.get("mode") == "mongodb"
        and persisted
        and _policy_event_count(mongo_memory, session_id)
        and verification.get("status") == "verified"
    )
    report = {
        "status": "passed" if passed else "failed",
        "mode": "agent_handshake_mongo_persistence",
        "api": api,
        "scenarioMode": scenario_mode,
        "mongo": {
            "connected": bool(mongo_status.get("connected")),
            "mode": mongo_status.get("mode"),
            "database": mongo_status.get("database"),
            "probableCause": (mongo_status.get("connectivity") or {}).get("probableCause"),
            "nextAction": (mongo_status.get("connectivity") or {}).get("nextAction"),
        },
        "session": {
            "id": session_id or None,
            "apiPersistenceStatus": ((demo.get("session") or {}).get("persistence") or {}).get("status")
            if isinstance(demo.get("session"), dict)
            else None,
            "persistedSessionFound": bool(persisted),
            "persistedCollection": "agent_handshake_sessions" if persisted else None,
            "persistedState": persisted.get("state") if isinstance(persisted, dict) else None,
            "policyEventCount": _policy_event_count(mongo_memory, session_id) if session_id else None,
        },
        "receipt": {
            "id": receipt.get("receipt_id"),
            "verificationStatus": verification.get("status"),
            "signatureStatus": verification.get("signature_status"),
            "digestStatus": verification.get("digest_status"),
        },
    }
    if not passed and mongo_status.get("connected"):
        report["nextAction"] = "Restart the API after Atlas access changes, then rerun this verifier."
    elif not passed:
        report["nextAction"] = (mongo_status.get("connectivity") or {}).get("nextAction")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify agent-handshake sessions and policy events persist to MongoDB.")
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="ParkPulse API base URL")
    parser.add_argument(
        "--scenario-mode",
        default="cold_chain_incident",
        choices=["supply_replenishment", "cold_chain_incident", "maintenance_parts_shortage"],
        help="Supply-chain protocol scenario to execute",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()
    try:
        report = verify(args.api, args.scenario_mode)
    except (urllib.error.URLError, TimeoutError) as error:
        report = {
            "status": "failed",
            "mode": "agent_handshake_mongo_persistence",
            "api": args.api,
            "reason": f"API request failed: {error}",
            "nextAction": "Start the ParkPulse API, then rerun this verifier.",
        }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
