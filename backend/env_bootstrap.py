from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
except ModuleNotFoundError:  # pragma: no cover - only used outside the project venv
    _load_dotenv = None


def _fallback_load_dotenv(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip("\"'")
        os.environ[key] = value


@lru_cache(maxsize=1)
def load_backend_env() -> tuple[str, ...]:
    """Load local backend env files before provider readiness checks run."""
    backend_dir = Path(__file__).resolve().parent
    repo_dir = backend_dir.parent
    candidates = (
        repo_dir / ".env",
        backend_dir / ".env",
    )
    loaded: list[str] = []
    for path in candidates:
        if path.exists():
            if _load_dotenv is not None:
                _load_dotenv(path, override=False)
            else:
                _fallback_load_dotenv(path)
            loaded.append(str(path))
    return tuple(loaded)
