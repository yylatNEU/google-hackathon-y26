#!/usr/bin/env python3
"""Routine QA agent for the ParkPulse hackathon project."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
BACKEND_DIR = REPO_ROOT / "backend"
REPORT_DIR = REPO_ROOT / "output" / "qa"

TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
    ".yaml",
}

EXCLUDED_PARTS = {
    ".git",
    ".agents",
    ".arize-tmp-traces",
    ".next",
    ".next-build",
    ".next-dev",
    ".pytest_cache",
    ".venv",
    ".venv-smoke",
    "__pycache__",
    "db_backups",
    "dist",
    "node_modules",
    "output",
    "tmp",
    "venv",
}

SECRET_PATTERNS = [
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9_\-.=]{24,}")),
    ("generic_secret_assignment", re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]")),
]

SECRET_PREFILTERS = {
    "google_api_key": ("AIza",),
    "private_key": ("PRIVATE KEY",),
    "bearer_token": ("Bearer ",),
    "generic_secret_assignment": ("api_key", "apikey", "api-key", "secret", "token", "password"),
}


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    duration_seconds: float = 0.0
    command: list[str] | None = None
    cwd: str | None = None
    output_tail: str = ""
    details: dict = field(default_factory=dict)


def is_excluded(path: Path) -> bool:
    return bool(set(path.relative_to(REPO_ROOT).parts) & EXCLUDED_PARTS)


def tail(text: str, lines: int = 80) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return "\n".join(stripped.splitlines()[-lines:])


def status_from_returncode(returncode: int, required: bool) -> str:
    if returncode == 0:
        return "pass"
    return "fail" if required else "warn"


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
    required: bool = True,
    env: dict[str, str] | None = None,
) -> CheckResult:
    if not executable_available(cmd):
        status = "fail" if required else "skipped"
        return CheckResult(
            name=name,
            status=status,
            summary=f"Executable not found: {cmd[0]}",
            command=cmd,
            cwd=str(cwd),
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
        return CheckResult(
            name=name,
            status=status_from_returncode(completed.returncode, required),
            summary="Completed successfully" if completed.returncode == 0 else f"Exited with code {completed.returncode}",
            duration_seconds=round(duration, 2),
            command=cmd,
            cwd=str(cwd),
            output_tail=tail(output),
            details={"returncode": completed.returncode},
        )
    except subprocess.TimeoutExpired as error:
        duration = time.monotonic() - started
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return CheckResult(
            name=name,
            status="fail" if required else "warn",
            summary=f"Timed out after {timeout_seconds}s",
            duration_seconds=round(duration, 2),
            command=cmd,
            cwd=str(cwd),
            output_tail=tail(output),
        )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http(url: str, timeout_seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.4)
    return False


def stop_process(process: subprocess.Popen[str] | None) -> str:
    if process is None:
        return ""
    output = ""
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, _ = process.communicate(timeout=8)
            output += stdout or ""
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, _ = process.communicate(timeout=3)
            output += stdout or ""
    else:
        stdout, _ = process.communicate(timeout=3)
        output += stdout or ""
    return output


def project_inventory() -> CheckResult:
    started = time.monotonic()
    failures: list[str] = []
    warnings: list[str] = []

    required_paths = [
        FRONTEND_DIR / "package.json",
        FRONTEND_DIR / "src" / "app" / "page.tsx",
        FRONTEND_DIR / "tsconfig.json",
        BACKEND_DIR / "requirements.txt",
        BACKEND_DIR / "main.py",
        BACKEND_DIR / "simulation.py",
        BACKEND_DIR / "policy_books",
    ]
    for path in required_paths:
        if not path.exists():
            failures.append(f"Missing required path: {path.relative_to(REPO_ROOT)}")

    package_json = FRONTEND_DIR / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text())
            scripts = package.get("scripts", {})
            for script_name in ("lint", "build"):
                if script_name not in scripts:
                    failures.append(f"frontend/package.json missing script: {script_name}")
        except json.JSONDecodeError as error:
            failures.append(f"frontend/package.json is invalid JSON: {error}")

    if (FRONTEND_DIR / "src" / "app" / "page 2.tsx").exists():
        warnings.append("Found frontend/src/app/page 2.tsx; duplicate route-like files are easy to ship accidentally.")

    generated_dirs = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (FRONTEND_DIR / ".next-build", FRONTEND_DIR / ".next-dev")
        if path.exists()
    ]

    if failures:
        status = "fail"
        summary = f"{len(failures)} inventory problem(s)"
    elif warnings:
        status = "warn"
        summary = f"{len(warnings)} inventory warning(s)"
    else:
        status = "pass"
        summary = "Project layout and required scripts are present"

    return CheckResult(
        name="Project inventory",
        status=status,
        summary=summary,
        duration_seconds=round(time.monotonic() - started, 2),
        details={"failures": failures, "warnings": warnings, "generated_dirs": generated_dirs},
    )


def static_hygiene_scan() -> CheckResult:
    started = time.monotonic()
    failures: list[str] = []
    warnings: list[str] = []
    scanned_files = 0
    task_marker_pattern = re.compile(r"\b(?:TODO|FIXME):", re.IGNORECASE)

    for root, dirnames, filenames in os.walk(REPO_ROOT):
        root_path = Path(root)
        dirnames[:] = sorted(dirname for dirname in dirnames if dirname not in EXCLUDED_PARTS)
        for filename in sorted(filenames):
            path = root_path / filename
            if is_excluded(path) or path.suffix not in TEXT_SUFFIXES:
                continue
            scanned_files += 1
            try:
                text = path.read_text(errors="replace")
            except OSError as error:
                warnings.append(f"Could not read {path.relative_to(REPO_ROOT)}: {error}")
                continue

            rel = path.relative_to(REPO_ROOT).as_posix()
            lines = text.splitlines()
            if any(line.startswith(("<<<<<<< ", "=======", ">>>>>>> ")) for line in lines):
                failures.append(f"Possible merge conflict marker in {rel}")

            for line_no, line in enumerate(lines, start=1):
                if len(line) > 5000:
                    continue

                if task_marker_pattern.search(line):
                    warnings.append(f"{rel}:{line_no} contains an open task marker")
                    break

                searchable_line = line.lower()
                for label, pattern in SECRET_PATTERNS:
                    prefilters = SECRET_PREFILTERS.get(label, ())
                    if prefilters and not any(marker.lower() in searchable_line for marker in prefilters):
                        continue
                    if pattern.search(line):
                        failures.append(f"{rel}:{line_no} matches secret pattern {label}")

    if failures:
        status = "fail"
        summary = f"{len(failures)} static hygiene failure(s)"
    elif warnings:
        status = "warn"
        summary = f"{len(warnings)} static hygiene warning(s)"
    else:
        status = "pass"
        summary = f"Scanned {scanned_files} text files"

    return CheckResult(
        name="Static hygiene scan",
        status=status,
        summary=summary,
        duration_seconds=round(time.monotonic() - started, 2),
        details={
            "scanned_files": scanned_files,
            "failures": failures[:50],
            "warnings": warnings[:50],
            "truncated": len(failures) > 50 or len(warnings) > 50,
        },
    )


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


def backend_compile_check() -> CheckResult:
    code = r"""
import pathlib
import py_compile
import os
import sys

root = pathlib.Path("backend")
failures = []
count = 0
for walk_root, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(dirname for dirname in dirnames if dirname not in {"venv", "__pycache__"})
    for filename in sorted(filenames):
        if not filename.endswith(".py"):
            continue
        path = pathlib.Path(walk_root) / filename
        count += 1
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as error:
            failures.append(f"{path}: {error.msg}")

if failures:
    print("\n".join(failures))
    sys.exit(1)

print(f"Compiled {count} backend Python files")
"""
    return run_command(
        "Backend Python compile",
        [python_executable(), "-c", code],
        REPO_ROOT,
        timeout_seconds=120,
    )


def backend_smoke_check() -> CheckResult:
    code = r"""
import asyncio

from governance import governance_status
from policy_loader import get_policy_books
from simulation import parkpulse_simulation

async def main():
    state = await parkpulse_simulation.get_state()
    if not isinstance(state, dict) or not state:
        raise AssertionError("parkpulse_simulation.get_state() returned an empty or non-dict state")

    policy_books = get_policy_books()
    if not policy_books:
        raise AssertionError("No policy books loaded")

    governance = governance_status()
    if not isinstance(governance, dict) or not governance:
        raise AssertionError("governance_status() returned an empty or non-dict result")

    print(
        "Backend smoke passed "
        f"(state_keys={len(state)}, policy_books={len(policy_books)}, governance_keys={len(governance)})"
    )

asyncio.run(main())
"""
    env = {"PYTHONPATH": str(BACKEND_DIR)}
    return run_command(
        "Backend smoke",
        [python_executable(), "-c", code],
        BACKEND_DIR,
        timeout_seconds=60,
        env=env,
    )


def frontend_lint_check() -> CheckResult:
    return run_command(
        "Frontend lint",
        ["npm", "run", "lint"],
        FRONTEND_DIR,
        timeout_seconds=180,
    )


def frontend_typecheck() -> CheckResult:
    return run_command(
        "Frontend TypeScript",
        ["npm", "run", "typecheck"],
        FRONTEND_DIR,
        timeout_seconds=180,
    )


def frontend_build_check() -> CheckResult:
    env = {"NEXT_DIST_DIR": ".next-build"}
    return run_command(
        "Frontend production build",
        ["npm", "run", "build"],
        FRONTEND_DIR,
        timeout_seconds=360,
        env=env,
    )


def frontend_e2e_check() -> CheckResult:
    started = time.monotonic()
    backend_port = free_port()
    frontend_port = free_port()
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    runtime_dir = Path(os.environ.get("PARKPULSE_FRONTEND_RUNTIME_DIR", "/tmp/parkpulse_frontend_runtime"))
    backend: subprocess.Popen[str] | None = None
    frontend: subprocess.Popen[str] | None = None
    logs: list[str] = []
    command = ["npm", "run", "test:e2e", "--", "--reporter=line", "ui-action-check.spec.ts"]

    try:
        backend_env = os.environ.copy()
        backend_env["PYTHONPATH"] = str(BACKEND_DIR)
        backend_env["PARKPULSE_ALLOWED_ORIGINS"] = frontend_url
        backend = subprocess.Popen(
            [python_executable(), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
            cwd=BACKEND_DIR,
            env=backend_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if not wait_for_http(f"{backend_url}/api/gcp/trace-eval-status", timeout_seconds=35):
            logs.append(stop_process(backend))
            return CheckResult(
                name="Frontend Playwright E2E",
                status="fail",
                summary="Backend did not become ready for isolated browser test",
                duration_seconds=round(time.monotonic() - started, 2),
                command=command,
                cwd=str(FRONTEND_DIR),
                output_tail=tail("\n".join(logs)),
                details={"backend_port": backend_port, "frontend_port": frontend_port},
            )

        frontend = subprocess.Popen(
            ["npm", "run", "start", "--", "--host", "127.0.0.1", "--port", str(frontend_port)],
            cwd=FRONTEND_DIR,
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if not wait_for_http(frontend_url, timeout_seconds=35):
            logs.append(stop_process(frontend))
            logs.append(stop_process(backend))
            return CheckResult(
                name="Frontend Playwright E2E",
                status="fail",
                summary="Frontend did not become ready for isolated browser test",
                duration_seconds=round(time.monotonic() - started, 2),
                command=command,
                cwd=str(FRONTEND_DIR),
                output_tail=tail("\n".join(logs)),
                details={"backend_port": backend_port, "frontend_port": frontend_port},
            )

        env = os.environ.copy()
        env["PARKPULSE_TEST_API_URL"] = backend_url
        env["PARKPULSE_TEST_APP_URL"] = frontend_url
        completed = subprocess.run(
            command,
            cwd=runtime_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
            check=False,
        )
        logs.append(completed.stdout or "")
        return CheckResult(
            name="Frontend Playwright E2E",
            status=status_from_returncode(completed.returncode, True),
            summary="Completed successfully" if completed.returncode == 0 else f"Exited with code {completed.returncode}",
            duration_seconds=round(time.monotonic() - started, 2),
            command=command,
            cwd=str(runtime_dir),
            output_tail=tail("\n".join(logs)),
            details={"returncode": completed.returncode, "backend_port": backend_port, "frontend_port": frontend_port},
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        logs.append(output)
        return CheckResult(
            name="Frontend Playwright E2E",
            status="fail",
            summary="Timed out after 120s",
            duration_seconds=round(time.monotonic() - started, 2),
            command=command,
            cwd=str(FRONTEND_DIR),
            output_tail=tail("\n".join(logs)),
            details={"backend_port": backend_port, "frontend_port": frontend_port},
        )
    finally:
        logs.append(stop_process(frontend))
        logs.append(stop_process(backend))


def skipped(name: str, reason: str) -> CheckResult:
    return CheckResult(name=name, status="skipped", summary=reason)


def quality_score(results: Iterable[CheckResult]) -> int:
    score = 100
    for result in results:
        if result.status == "fail":
            score -= 25
        elif result.status == "warn":
            score -= 8
        elif result.status == "skipped":
            score -= 4
    return max(score, 0)


def render_report(results: list[CheckResult], generated_at: str, quick: bool, score: int) -> str:
    failures = [result for result in results if result.status == "fail"]
    warnings = [result for result in results if result.status == "warn"]
    skipped_results = [result for result in results if result.status == "skipped"]
    overall = "fail" if failures else "warn" if warnings else "pass"

    lines = [
        "# Routine QA Agent Report",
        "",
        f"- Generated: {generated_at}",
        f"- Mode: {'quick' if quick else 'full'}",
        f"- Overall status: {overall}",
        f"- Quality score: {score}/100",
        f"- Checks: {len(results)} total, {len(failures)} failed, {len(warnings)} warned, {len(skipped_results)} skipped",
        "",
        "## Check Summary",
        "",
        "| Check | Status | Duration | Summary |",
        "| --- | --- | ---: | --- |",
    ]

    for result in results:
        duration = f"{result.duration_seconds:.2f}s" if result.duration_seconds else "-"
        lines.append(f"| {result.name} | {result.status} | {duration} | {result.summary.replace('|', '\\|')} |")

    notable = failures + warnings + skipped_results
    if notable:
        lines.extend(["", "## Details"])
        for result in notable:
            lines.extend(["", f"### {result.name}", "", f"Status: `{result.status}`", "", result.summary])
            if result.command:
                lines.extend(["", "Command:", "", f"```bash\n{' '.join(result.command)}\n```"])
            for key in ("failures", "warnings"):
                values = result.details.get(key, [])
                if values:
                    lines.extend(["", f"{key.title()}:"])
                    lines.extend(f"- {value}" for value in values)
            if result.output_tail:
                lines.extend(["", "Output tail:", "", f"```text\n{result.output_tail}\n```"])

    lines.extend(
        [
            "",
            "## Routine",
            "",
            "- Run `make qa` before demos, merges, or deploys.",
            "- Run `make qa-quick` while iterating on small backend or UI changes.",
            "- Treat failed checks as release blockers; warnings are review items unless `--fail-on-warning` is used.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(results: list[CheckResult], args: argparse.Namespace) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    score = quality_score(results)
    payload = {
        "generated_at": generated_at,
        "mode": "quick" if args.quick else "full",
        "quality_score": score,
        "overall_status": "fail" if any(result.status == "fail" for result in results) else "warn" if any(result.status == "warn" for result in results) else "pass",
        "results": [asdict(result) for result in results],
    }

    markdown = render_report(results, generated_at, args.quick, score)
    markdown_path = REPORT_DIR / f"{stamp}.md"
    json_path = REPORT_DIR / f"{stamp}.json"
    markdown_path.write_text(markdown)
    json_path.write_text(json.dumps(payload, indent=2))
    (REPORT_DIR / "latest.md").write_text(markdown)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2))
    return markdown_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run routine QA checks for the ParkPulse project.")
    parser.add_argument("--quick", action="store_true", help="Skip the production frontend build.")
    parser.add_argument("--backend-only", action="store_true", help="Run only backend and static checks.")
    parser.add_argument("--frontend-only", action="store_true", help="Run only frontend and static checks.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit non-zero when warnings are present.")
    parser.add_argument("--no-report", action="store_true", help="Do not write output/qa reports.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.backend_only and args.frontend_only:
        print("--backend-only and --frontend-only cannot be used together", file=sys.stderr)
        return 2

    results: list[CheckResult] = [project_inventory(), static_hygiene_scan()]

    if not args.frontend_only:
        results.extend([backend_compile_check(), backend_smoke_check()])

    if not args.backend_only:
        results.extend([frontend_lint_check(), frontend_typecheck()])
        if args.quick:
            results.append(skipped("Frontend production build", "Skipped in quick mode"))
            results.append(skipped("Frontend Playwright E2E", "Skipped in quick mode"))
        else:
            results.append(frontend_build_check())
            results.append(frontend_e2e_check())

    score = quality_score(results)
    failures = [result for result in results if result.status == "fail"]
    warnings = [result for result in results if result.status == "warn"]

    print(f"Routine QA score: {score}/100")
    for result in results:
        print(f"[{result.status.upper():7}] {result.name}: {result.summary}")

    if not args.no_report:
        markdown_path, json_path = write_reports(results, args)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")

    if failures or (args.fail_on_warning and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
