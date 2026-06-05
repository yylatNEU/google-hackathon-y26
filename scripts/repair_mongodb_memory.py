#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "backend"))


def _public_ip() -> str | None:
    for url in ("http://api.ipify.org", "http://ifconfig.me/ip"):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "parkpulse-mongodb-repair/1.0"})
            with urllib.request.urlopen(request, timeout=4) as response:
                value = response.read(128).decode("utf-8", errors="replace").strip()
                if value:
                    return value
        except Exception:
            continue
    return None


def main() -> int:
    import env_bootstrap

    loaded_env = env_bootstrap.load_backend_env()
    import memory_ops_agent
    import mongo_memory

    egress_ip = _public_ip()
    initial_status = mongo_memory.init_operational_memory(force=True)
    connected = bool(initial_status.get("connected"))
    repair = {"status": "skipped", "reason": "MongoDB is not connected; no persistent writes were attempted."}
    if connected:
        mongo_memory._memory.seed_defaults()
        repair = mongo_memory.backfill_memory_embeddings(["playbooks", "incidents", "agent_learnings"], 250)
    report = memory_ops_agent.build_memory_ops_report()
    payload = {
        "loadedEnvFiles": loaded_env,
        "publicEgressIp": egress_ip,
        "atlasNetworkAccessCidr": f"{egress_ip}/32" if egress_ip else None,
        "initialStatus": initial_status,
        "repair": repair,
        "memoryOps": {
            "overallStatus": report.get("overall_status"),
            "summary": report.get("summary"),
            "findings": report.get("findings"),
            "recommendedActions": report.get("recommended_actions"),
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if connected else 2


if __name__ == "__main__":
    raise SystemExit(main())
