#!/usr/bin/env python3
"""Coverage engineer for enforcing project test coverage gates."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
REPORT_DIR = REPO_ROOT / "output" / "coverage"

BACKEND_EXCLUDED_PARTS = {
    "__pycache__",
    ".venv",
    "venv",
    "db_backups",
}

BACKEND_COVERAGE_OMITS = [
    "lazy_dev_server.py",
    "* 2.py",
]

FRONTEND_COVERAGE_SUMMARIES = [
    FRONTEND_DIR / "coverage" / "coverage-summary.json",
    FRONTEND_DIR / "coverage" / "coverage-final.json",
]


@dataclass
class CoverageResult:
    name: str
    status: str
    summary: str
    duration_seconds: float = 0.0
    command: list[str] | None = None
    cwd: str | None = None
    coverage_percent: float | None = None
    threshold_percent: float = 98.0
    output_tail: str = ""
    details: dict = field(default_factory=dict)


def tail(text: str, lines: int = 80) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return "\n".join(stripped.splitlines()[-lines:])


def python_executable() -> str:
    configured = os.getenv("PARKPULSE_BACKEND_PYTHON")
    if configured:
        configured_path = Path(configured)
        if configured_path.exists() and not python_runtime_is_dataless(configured_path):
            return configured

    candidates = [
        Path("/tmp/parkpulse_backend_venv/bin/python"),
        BACKEND_DIR / "venv" / "bin" / "python",
        REPO_ROOT / ".venv-smoke" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists() and not python_runtime_is_dataless(candidate):
            return str(candidate)
    return sys.executable


def python_runtime_is_dataless(python: Path) -> bool:
    site_package_roots = sorted((python.parents[1] / "lib").glob("python*/site-packages"))
    sentinels = []
    for site_packages in site_package_roots:
        sentinels.extend(
            [
                site_packages / "pytest" / "__init__.py",
                site_packages / "fastapi" / "__init__.py",
            ]
        )
    for sentinel in sentinels:
        if not sentinel.exists():
            continue
        try:
            result = subprocess.run(
                ["/bin/ls", "-lO", str(sentinel)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        if "dataless" in result.stdout:
            return True
    return False


def executable_available(cmd: list[str]) -> bool:
    executable = cmd[0]
    candidate = Path(executable)
    if candidate.is_absolute() or os.sep in executable:
        return candidate.exists()
    return shutil.which(executable) is not None


def run_command(
    name: str,
    cmd: list[str],
    cwd: Path,
    timeout_seconds: int,
    threshold: float,
    env: dict[str, str] | None = None,
) -> CoverageResult:
    if not executable_available(cmd):
        return CoverageResult(
            name=name,
            status="fail",
            summary=f"Executable not found: {cmd[0]}",
            command=cmd,
            cwd=str(cwd),
            threshold_percent=threshold,
        )

    started = time.monotonic()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
        duration = time.monotonic() - started
        output = completed.stdout or ""
        return CoverageResult(
            name=name,
            status="pass" if completed.returncode == 0 else "fail",
            summary="Completed successfully" if completed.returncode == 0 else f"Exited with code {completed.returncode}",
            duration_seconds=round(duration, 2),
            command=cmd,
            cwd=str(cwd),
            threshold_percent=threshold,
            output_tail=tail(output),
            details={"returncode": completed.returncode},
        )
    except subprocess.TimeoutExpired as error:
        duration = time.monotonic() - started
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return CoverageResult(
            name=name,
            status="fail",
            summary=f"Timed out after {timeout_seconds}s",
            duration_seconds=round(duration, 2),
            command=cmd,
            cwd=str(cwd),
            threshold_percent=threshold,
            output_tail=tail(output),
        )


def excluded_backend_path(path: Path) -> bool:
    return bool(set(path.relative_to(REPO_ROOT).parts) & BACKEND_EXCLUDED_PARTS)


def duplicate_copy_test_path(path: Path) -> bool:
    """Ignore local Finder-style duplicate test copies such as ``test_foo 2.py``."""
    return path.suffix == ".py" and path.stem.endswith(" 2")


def discover_pytest_nodes(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return [str(path.relative_to(REPO_ROOT))]
    nodes = [
        f"{path.relative_to(REPO_ROOT)}::{node.name}"
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]
    return nodes or [str(path.relative_to(REPO_ROOT))]


def discover_backend_tests() -> list[str]:
    test_files: list[Path] = []
    for root in (BACKEND_DIR, REPO_ROOT / "tests"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if excluded_backend_path(path):
                continue
            if duplicate_copy_test_path(path):
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                test_files.append(path)
    targets: list[str] = []
    for path in sorted(test_files, key=lambda path: (path.name == "test_parkpulse_api_wrappers.py", str(path))):
        if path.name == "test_parkpulse_completion.py":
            targets.extend(discover_pytest_nodes(path))
        else:
            targets.append(str(path.relative_to(REPO_ROOT)))
    return targets


def module_available(python: str, module: str) -> bool:
    completed = subprocess.run(
        [python, "-c", f"import {module}"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    safe_size = max(1, size)
    for index in range(0, len(items), safe_size):
        yield items[index : index + safe_size]


def backend_coverage(threshold: float, timeout_seconds: int) -> CoverageResult:
    started = time.monotonic()
    test_files = discover_backend_tests()
    if not test_files:
        return CoverageResult(
            name="Backend coverage",
            status="fail",
            summary="No backend pytest files found; add test_*.py or *_test.py files before the 98% gate can pass.",
            duration_seconds=round(time.monotonic() - started, 2),
            threshold_percent=threshold,
            details={"test_targets": []},
        )

    python = python_executable()
    missing_modules = [module for module in ("coverage", "pytest") if not module_available(python, module)]
    if missing_modules:
        return CoverageResult(
            name="Backend coverage",
            status="fail",
            summary=f"Missing Python test tooling: {', '.join(missing_modules)}",
            duration_seconds=round(time.monotonic() - started, 2),
            threshold_percent=threshold,
            details={
                "install": "python -m pip install -r backend/requirements.txt",
                "test_targets": test_files,
            },
        )

    json_path = REPORT_DIR / "backend-coverage.json"
    env = {"PYTHONPATH": str(BACKEND_DIR), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    erase_result = run_command(
        "Backend coverage erase",
        [python, "-m", "coverage", "erase"],
        REPO_ROOT,
        timeout_seconds=60,
        threshold=threshold,
        env=env,
    )
    if erase_result.status == "fail":
        erase_result.name = "Backend coverage"
        erase_result.details["test_targets"] = test_files
        return erase_result

    chunk_size = int(os.getenv("COVERAGE_BACKEND_TEST_CHUNK_SIZE", "4") or "4")
    run_results: list[CoverageResult] = []
    chunk_commands: list[list[str]] = []
    coverage_base = [
        python,
        "-m",
        "coverage",
        "run",
        "--parallel-mode",
        "--source",
        str(BACKEND_DIR),
        "--omit",
        ",".join(
            [
                f"{BACKEND_DIR}/venv/*",
                f"{BACKEND_DIR}/__pycache__/*",
                f"{BACKEND_DIR}/db_backups/*",
                *[f"{BACKEND_DIR}/{name}" for name in BACKEND_COVERAGE_OMITS],
            ]
        ),
        "-m",
        "pytest",
        "-q",
    ]
    for index, test_chunk in enumerate(chunks(test_files, chunk_size), start=1):
        cmd = [*coverage_base, *test_chunk]
        chunk_commands.append(cmd)
        run_result = run_command(
            f"Backend coverage chunk {index}",
            cmd,
            REPO_ROOT,
            timeout_seconds=timeout_seconds,
            threshold=threshold,
            env=env,
        )
        if run_result.status == "fail" and run_result.details.get("returncode") == -15:
            retry_result = run_command(
                f"Backend coverage chunk {index} retry",
                cmd,
                REPO_ROOT,
                timeout_seconds=timeout_seconds,
                threshold=threshold,
                env=env,
            )
            if retry_result.status == "pass":
                run_result = retry_result
        run_results.append(run_result)
        if run_result.status == "fail":
            run_result.name = "Backend coverage"
            run_result.details["test_targets"] = test_files
            run_result.details["failed_chunk"] = test_chunk
            run_result.details["chunk_commands"] = chunk_commands
            return run_result

    combine_result = run_command(
        "Backend coverage combine",
        [python, "-m", "coverage", "combine"],
        REPO_ROOT,
        timeout_seconds=max(60, timeout_seconds),
        threshold=threshold,
        env=env,
    )
    if combine_result.status == "fail":
        combine_result.name = "Backend coverage"
        combine_result.details["test_targets"] = test_files
        combine_result.details["chunk_commands"] = chunk_commands
        return combine_result

    json_result = run_command(
        "Backend coverage JSON",
        [python, "-m", "coverage", "json", "-o", str(json_path)],
        REPO_ROOT,
        timeout_seconds=max(60, timeout_seconds),
        threshold=threshold,
        env=env,
    )
    if json_result.status == "fail":
        json_result.name = "Backend coverage"
        json_result.details["test_targets"] = test_files
        return json_result

    try:
        payload = json.loads(json_path.read_text())
        percent = float(payload["totals"]["percent_covered"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return CoverageResult(
            name="Backend coverage",
            status="fail",
            summary=f"Could not parse backend coverage JSON: {error}",
            duration_seconds=round(time.monotonic() - started, 2),
            threshold_percent=threshold,
            details={"coverage_json": str(json_path)},
        )

    status = "pass" if percent >= threshold else "fail"
    return CoverageResult(
        name="Backend coverage",
        status=status,
        summary=f"Backend line coverage is {percent:.2f}% against required {threshold:.2f}%",
        duration_seconds=round(time.monotonic() - started, 2),
        command=chunk_commands[-1] if chunk_commands else None,
        cwd=str(REPO_ROOT),
        coverage_percent=round(percent, 2),
        threshold_percent=threshold,
        output_tail="\n".join(result.output_tail for result in run_results if result.output_tail),
        details={
            "coverage_json": str(json_path),
            "test_targets": test_files,
            "chunk_size": chunk_size,
            "chunk_count": len(chunk_commands),
            "chunk_commands": chunk_commands,
        },
    )


def frontend_package() -> dict:
    package_path = FRONTEND_DIR / "package.json"
    if not package_path.exists():
        return {}
    try:
        return json.loads(package_path.read_text())
    except json.JSONDecodeError:
        return {}


def frontend_coverage_script(scripts: dict) -> str | None:
    for script_name in ("coverage", "test:coverage", "test"):
        script = scripts.get(script_name)
        if not isinstance(script, str):
            continue
        if script_name == "test" and "coverage" not in script:
            continue
        return script_name
    return None


def parse_frontend_coverage_percent() -> tuple[float | None, Path | None, str | None]:
    for path in FRONTEND_COVERAGE_SUMMARIES:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            return None, path, f"Invalid JSON: {error}"

        total = payload.get("total", {})
        if "lines" in total and isinstance(total["lines"], dict):
            pct = total["lines"].get("pct")
            if isinstance(pct, (int, float)):
                return float(pct), path, None

        if payload:
            covered = 0
            total_lines = 0
            for file_payload in payload.values():
                statement_map = file_payload.get("statementMap") if isinstance(file_payload, dict) else None
                statement_hits = file_payload.get("s") if isinstance(file_payload, dict) else None
                if not isinstance(statement_map, dict) or not isinstance(statement_hits, dict):
                    continue
                total_lines += len(statement_map)
                covered += sum(1 for hits in statement_hits.values() if hits)
            if total_lines:
                return (covered / total_lines) * 100, path, None

    return None, None, "No frontend coverage summary found."


def frontend_coverage(threshold: float, timeout_seconds: int) -> CoverageResult:
    started = time.monotonic()
    package = frontend_package()
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    script_name = frontend_coverage_script(scripts)
    if not script_name:
        return CoverageResult(
            name="Frontend coverage",
            status="fail",
            summary="No frontend coverage npm script found; add coverage or test:coverage that writes coverage-summary.json.",
            duration_seconds=round(time.monotonic() - started, 2),
            threshold_percent=threshold,
            details={"available_scripts": sorted(scripts.keys())},
        )

    for path in FRONTEND_COVERAGE_SUMMARIES:
        if path.exists():
            path.unlink()

    result = run_command(
        "Frontend coverage",
        ["npm", "run", script_name],
        FRONTEND_DIR,
        timeout_seconds=timeout_seconds,
        threshold=threshold,
    )
    if result.status == "fail":
        return result

    percent, summary_path, error = parse_frontend_coverage_percent()
    if percent is None:
        return CoverageResult(
            name="Frontend coverage",
            status="fail",
            summary=error or "Could not parse frontend coverage output.",
            duration_seconds=round(time.monotonic() - started, 2),
            command=["npm", "run", script_name],
            cwd=str(FRONTEND_DIR),
            threshold_percent=threshold,
            output_tail=result.output_tail,
        )

    status = "pass" if percent >= threshold else "fail"
    return CoverageResult(
        name="Frontend coverage",
        status=status,
        summary=f"Frontend line coverage is {percent:.2f}% against required {threshold:.2f}%",
        duration_seconds=round(time.monotonic() - started, 2),
        command=["npm", "run", script_name],
        cwd=str(FRONTEND_DIR),
        coverage_percent=round(percent, 2),
        threshold_percent=threshold,
        output_tail=result.output_tail,
        details={"coverage_summary": str(summary_path) if summary_path else ""},
    )


def render_report(results: list[CoverageResult], generated_at: str, threshold: float) -> str:
    failures = [result for result in results if result.status == "fail"]
    overall = "fail" if failures else "pass"

    lines = [
        "# Coverage Engineer Report",
        "",
        f"- Generated: {generated_at}",
        f"- Overall status: {overall}",
        f"- Required coverage: {threshold:.2f}%",
        f"- Checks: {len(results)} total, {len(failures)} failed",
        "",
        "## Summary",
        "",
        "| Scope | Status | Coverage | Duration | Summary |",
        "| --- | --- | ---: | ---: | --- |",
    ]

    for result in results:
        coverage = f"{result.coverage_percent:.2f}%" if result.coverage_percent is not None else "-"
        duration = f"{result.duration_seconds:.2f}s" if result.duration_seconds else "-"
        lines.append(f"| {result.name} | {result.status} | {coverage} | {duration} | {result.summary.replace('|', '\\|')} |")

    if failures:
        lines.extend(["", "## Blockers"])
        for result in failures:
            lines.extend(["", f"### {result.name}", "", result.summary])
            if result.command:
                lines.extend(["", "Command:", "", f"```bash\n{' '.join(result.command)}\n```"])
            if result.output_tail:
                lines.extend(["", "Output tail:", "", f"```text\n{result.output_tail}\n```"])
            if result.details:
                lines.extend(["", "Details:", "", f"```json\n{json.dumps(result.details, indent=2)}\n```"])

    lines.extend(
        [
            "",
            "## Operating Rule",
            "",
            "- The gate passes only when every selected scope reports line coverage greater than or equal to the required threshold.",
            "- The default threshold is 98%; use `--threshold` only for local investigation, not for release approval.",
            "",
        ]
    )
    return "\n".join(lines)


def coverage_score(results: Iterable[CoverageResult]) -> float:
    percentages = [result.coverage_percent for result in results if result.coverage_percent is not None]
    if not percentages:
        return 0.0
    return round(min(percentages), 2)


def write_reports(results: list[CoverageResult], args: argparse.Namespace) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {
        "generated_at": generated_at,
        "threshold_percent": args.threshold,
        "coverage_score": coverage_score(results),
        "overall_status": "fail" if any(result.status == "fail" for result in results) else "pass",
        "results": [asdict(result) for result in results],
    }

    markdown = render_report(results, generated_at, args.threshold)
    markdown_path = REPORT_DIR / f"{stamp}.md"
    json_path = REPORT_DIR / f"{stamp}.json"
    markdown_path.write_text(markdown)
    json_path.write_text(json.dumps(payload, indent=2))
    (REPORT_DIR / "latest.md").write_text(markdown)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2))
    return markdown_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the 98% test coverage engineer gate.")
    parser.add_argument("--threshold", type=float, default=98.0, help="Minimum required line coverage percentage.")
    parser.add_argument("--backend-only", action="store_true", help="Run only backend coverage.")
    parser.add_argument("--frontend-only", action="store_true", help="Run only frontend coverage.")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per coverage command in seconds.")
    parser.add_argument("--no-report", action="store_true", help="Do not write output/coverage reports.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.backend_only and args.frontend_only:
        print("--backend-only and --frontend-only cannot be used together", file=sys.stderr)
        return 2

    if args.threshold <= 0 or args.threshold > 100:
        print("--threshold must be greater than 0 and less than or equal to 100", file=sys.stderr)
        return 2

    results: list[CoverageResult] = []
    if not args.frontend_only:
        results.append(backend_coverage(args.threshold, args.timeout))
    if not args.backend_only:
        results.append(frontend_coverage(args.threshold, args.timeout))

    overall = "fail" if any(result.status == "fail" for result in results) else "pass"
    print(f"Coverage engineer status: {overall} (threshold {args.threshold:.2f}%)")
    for result in results:
        coverage = f" ({result.coverage_percent:.2f}%)" if result.coverage_percent is not None else ""
        print(f"[{result.status.upper():7}] {result.name}{coverage}: {result.summary}")
        if result.status == "fail":
            failed_chunk = result.details.get("failed_chunk")
            if failed_chunk:
                print(f"Failed chunk: {', '.join(failed_chunk)}")
            if result.output_tail:
                print(result.output_tail)

    if not args.no_report:
        markdown_path, json_path = write_reports(results, args)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")

    return 1 if overall == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
