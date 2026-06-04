from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_role_skills import build_agent_role_product_readiness_report, build_deliberate_role_eval_report  # noqa: E402
from agent_role_trace_samples import build_adversarial_sampled_role_trace_eval_report, build_sampled_agent_role_trace_eval_report  # noqa: E402
from main import _real_agent_role_eval_report  # noqa: E402


def _status_ok(report: dict[str, Any]) -> bool:
    return report.get("status") == "passed" and not report.get("readiness_issues")


async def _run() -> int:
    synthetic = build_deliberate_role_eval_report()
    real = await _real_agent_role_eval_report()
    sampled = build_sampled_agent_role_trace_eval_report()
    adversarial = build_adversarial_sampled_role_trace_eval_report()
    negative = real.get("negative_fixtures", {}) if isinstance(real.get("negative_fixtures"), dict) else {}
    product = build_agent_role_product_readiness_report(
        real,
        synthetic_report=synthetic,
        sampled_report=sampled,
        adversarial_report=adversarial,
        negative_report=negative,
    )
    sampled_ok = sampled.get("status") in {"passed", "skipped"}
    summary = {
        "status": "passed" if _status_ok(synthetic) and _status_ok(real) and sampled_ok and adversarial.get("status") == "passed" and negative.get("status") == "passed" and product.get("status") == "passed" else "failed",
        "mode": "agent_role_eval_gate",
        "synthetic": {
            "status": synthetic.get("status"),
            "average_score": synthetic.get("average_score"),
            "passed_role_count": synthetic.get("passed_role_count"),
            "failed_role_count": synthetic.get("failed_role_count"),
            "readiness_issues": synthetic.get("readiness_issues", []),
        },
        "real": {
            "status": real.get("status"),
            "average_score": real.get("average_score"),
            "passed_role_count": real.get("passed_role_count"),
            "failed_role_count": real.get("failed_role_count"),
            "readiness_issues": real.get("readiness_issues", []),
        },
        "sampled": {
            "status": sampled.get("status"),
            "average_score": sampled.get("average_score"),
            "sample_count": sampled.get("sample_count"),
            "passed_count": sampled.get("passed_count"),
            "failed_count": sampled.get("failed_count"),
            "path": sampled.get("path"),
            "readiness_issues": sampled.get("readiness_issues", []),
        },
        "adversarial_sampled": {
            "status": adversarial.get("status"),
            "fixture_count": adversarial.get("fixture_count"),
            "caught_count": adversarial.get("caught_count"),
            "missed_count": adversarial.get("missed_count"),
            "wrong_reason_count": adversarial.get("wrong_reason_count"),
            "readiness_issues": adversarial.get("readiness_issues", []),
        },
        "negative_fixtures": {
            "status": negative.get("status"),
            "missed_count": negative.get("missed_count"),
            "wrong_reason_count": negative.get("wrong_reason_count"),
        },
        "product_readiness": {
            "status": product.get("status"),
            "product_ready_role_count": product.get("product_ready_role_count"),
            "not_ready_role_count": product.get("not_ready_role_count"),
            "readiness_issues": product.get("readiness_issues", []),
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
