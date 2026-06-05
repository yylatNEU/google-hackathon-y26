#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "backend"))


def _run_gcloud(args: list[str]) -> tuple[int, str]:
    if not shutil.which("gcloud"):
        return 127, "gcloud_not_installed"
    completed = subprocess.run(
        ["gcloud", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.returncode, completed.stdout.strip()


def _gcloud_project() -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    if project:
        return project
    code, output = _run_gcloud(["config", "get-value", "project"])
    return output.strip() if code == 0 else ""


def _secret_status(project_id: str, secret_name: str) -> dict[str, Any]:
    if not project_id:
        return {"status": "skipped", "reason": "project_not_configured", "secret": secret_name}
    code, output = _run_gcloud(["secrets", "describe", secret_name, "--project", project_id, "--format=value(name)"])
    if code == 0:
        return {"status": "exists", "secret": secret_name, "project": project_id}
    return {"status": "missing", "secret": secret_name, "project": project_id, "detail": output[:300]}


def _release_gates(
    *,
    secret: dict[str, Any],
    status: dict[str, Any],
    memory_ops: dict[str, Any],
    indexes: dict[str, Any] | None,
    backfill: dict[str, Any] | None,
) -> dict[str, Any]:
    model_api = status.get("modelApi", {}) if isinstance(status.get("modelApi"), dict) else {}
    model_readiness = memory_ops.get("model_api_readiness", {}) if isinstance(memory_ops.get("model_api_readiness"), dict) else {}
    gates = [
        {
            "id": "secret_manager_key",
            "status": "pass" if secret.get("status") == "exists" or model_api.get("configured") else "block",
            "detail": "Model API key is available via Secret Manager or local env." if secret.get("status") == "exists" or model_api.get("configured") else "Create the Secret Manager key before enabling provider embeddings.",
        },
        {
            "id": "mongo_connected",
            "status": "pass" if status.get("connected") else "block",
            "detail": "MongoDB is connected." if status.get("connected") else "MongoDB is not connected; backfill and Atlas index validation cannot run.",
        },
        {
            "id": "model_api_enabled",
            "status": "pass" if model_api.get("enabled") else "wait",
            "detail": "Provider embedding mode is enabled." if model_api.get("enabled") else "Keep disabled until key, index, and backfill are ready.",
        },
        {
            "id": "model_embedding_coverage",
            "status": "pass" if model_readiness.get("status") == "ready" else "wait" if model_readiness.get("status") == "not_enabled" else "block",
            "detail": model_readiness.get("blockers") or model_readiness.get("warnings") or [model_readiness.get("status")],
        },
    ]
    if indexes is not None:
        gates.append(
            {
                "id": "atlas_vector_indexes",
                "status": "pass" if indexes.get("status") in {"ready", "created", "ready_with_atlas_quota_limits"} else "block",
                "detail": indexes.get("collections", {}),
            }
        )
    if backfill is not None:
        gates.append(
            {
                "id": "embedding_backfill",
                "status": "pass" if backfill.get("status") == "repaired" else "block",
                "detail": backfill.get("collections", {}),
            }
        )

    decision = "ready_to_enable" if all(gate["status"] == "pass" for gate in gates) else "not_ready"
    blockers = [gate for gate in gates if gate["status"] == "block"]
    return {"decision": decision, "blockers": blockers, "gates": gates}


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight MongoDB Atlas/Voyage model API grounding for ParkPulse.")
    parser.add_argument("--project", default=_gcloud_project(), help="GCP project for Secret Manager checks.")
    parser.add_argument("--secret", default=os.getenv("PARKPULSE_MONGODB_MODEL_API_KEY_SECRET", "parkpulse-mongodb-model-api-key"))
    parser.add_argument("--query", default="ride down crowd staff food")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--create-indexes", action="store_true", help="Create/repair Atlas Vector Search indexes.")
    parser.add_argument("--backfill", action="store_true", help="Backfill embeddings in MongoDB.")
    parser.add_argument(
        "--collections",
        default="playbooks,incidents,agent_learnings",
        help="Comma-separated collections for optional backfill.",
    )
    args = parser.parse_args()

    import env_bootstrap
    import memory_ops_agent
    import mongo_memory

    loaded_env = env_bootstrap.load_backend_env()
    initial_status = mongo_memory.init_operational_memory(force=True)
    secret = _secret_status(args.project, args.secret)
    indexes = mongo_memory.ensure_memory_vector_indexes() if args.create_indexes else None
    selected_collections = [item.strip() for item in args.collections.split(",") if item.strip()]
    backfill = mongo_memory.backfill_memory_embeddings(selected_collections, args.limit) if args.backfill else None
    memory_ops = memory_ops_agent.build_memory_ops_report(args.query)
    gates = _release_gates(
        secret=secret,
        status=initial_status,
        memory_ops=memory_ops,
        indexes=indexes,
        backfill=backfill,
    )
    payload = {
        "status": gates["decision"],
        "loadedEnvFiles": loaded_env,
        "project": args.project,
        "secret": secret,
        "initialStatus": {
            "mode": initial_status.get("mode"),
            "connected": initial_status.get("connected"),
            "database": initial_status.get("database"),
            "modelApi": initial_status.get("modelApi"),
            "vectorSearch": initial_status.get("vectorSearch"),
            "errors": initial_status.get("errors"),
        },
        "indexRepair": indexes,
        "backfill": backfill,
        "memoryOps": {
            "overallStatus": memory_ops.get("overall_status"),
            "summary": memory_ops.get("summary"),
            "modelApiReadiness": memory_ops.get("model_api_readiness"),
            "modelEmbeddingCoverage": memory_ops.get("model_embedding_coverage"),
            "findings": memory_ops.get("findings"),
            "recommendedActions": memory_ops.get("recommended_actions"),
        },
        "releaseGates": gates,
        "nextCommands": [
            f"gcloud secrets create {args.secret} --project {args.project or '<project>'} --replication-policy=automatic --data-file=-",
            "PARKPULSE_MONGO_MODEL_EMBEDDINGS=true PARKPULSE_COPILOT_SEMANTIC_MEMORY=true scripts/preflight_mongodb_model_api.py --create-indexes --backfill",
            "PARKPULSE_MONGO_MODEL_EMBEDDINGS=true PARKPULSE_COPILOT_SEMANTIC_MEMORY=true scripts/deploy_private_cloud_run.sh crypto-song-496607-d7 us-central1",
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if gates["decision"] == "ready_to_enable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
