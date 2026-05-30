from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar


T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None
    last_error: str | None = None
    successes: int = 0

    def allow_request(self) -> bool:
        if self.opened_at is None:
            return True
        if time.monotonic() - self.opened_at >= self.recovery_seconds:
            return True
        return False

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.allow_request():
            return "half_open"
        return "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.last_error = None
        self.successes += 1

    def record_failure(self, error: BaseException) -> None:
        self.failures += 1
        self.last_error = str(error)[:500]
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self.failures,
            "failure_threshold": self.failure_threshold,
            "recovery_seconds": self.recovery_seconds,
            "last_error": self.last_error,
            "successes": self.successes,
        }


@dataclass
class ReliabilityRegistry:
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    def breaker(self, name: str) -> CircuitBreaker:
        if name not in self.breakers:
            self.breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=_env_int("PARKPULSE_CIRCUIT_FAILURE_THRESHOLD", 3),
                recovery_seconds=_env_float("PARKPULSE_CIRCUIT_RECOVERY_SECONDS", 30.0),
            )
        return self.breakers[name]

    def snapshot(self) -> dict[str, Any]:
        return {name: breaker.snapshot() for name, breaker in sorted(self.breakers.items())}


registry = ReliabilityRegistry()


def _default_retryable(error: BaseException) -> bool:
    if isinstance(error, CircuitOpenError):
        return False
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    if status_code is not None:
        return int(status_code) in {408, 409, 425, 429, 500, 502, 503, 504}
    return True


def _sleep_seconds(attempt: int, base_delay: float, max_delay: float) -> float:
    jitter = random.uniform(0, base_delay)
    return min(max_delay, base_delay * (2 ** max(0, attempt - 1)) + jitter)


def call_with_retries(
    name: str,
    operation: Callable[[], T],
    *,
    attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    retryable: Callable[[BaseException], bool] = _default_retryable,
) -> T:
    breaker = registry.breaker(name)
    if not breaker.allow_request():
        raise CircuitOpenError(f"Circuit {name} is open.")

    max_attempts = attempts or _env_int("PARKPULSE_RETRY_ATTEMPTS", 2)
    retry_delay = base_delay if base_delay is not None else _env_float("PARKPULSE_RETRY_BASE_DELAY_SECONDS", 0.2)
    retry_max = max_delay if max_delay is not None else _env_float("PARKPULSE_RETRY_MAX_DELAY_SECONDS", 2.0)
    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = operation()
            breaker.record_success()
            return result
        except BaseException as error:
            last_error = error
            breaker.record_failure(error)
            if attempt >= max_attempts or not retryable(error):
                raise
            time.sleep(_sleep_seconds(attempt, retry_delay, retry_max))

    raise RuntimeError(f"{name} failed without an exception.") from last_error


async def async_call_with_retries(
    name: str,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    retryable: Callable[[BaseException], bool] = _default_retryable,
) -> T:
    breaker = registry.breaker(name)
    if not breaker.allow_request():
        raise CircuitOpenError(f"Circuit {name} is open.")

    max_attempts = attempts or _env_int("PARKPULSE_RETRY_ATTEMPTS", 2)
    retry_delay = base_delay if base_delay is not None else _env_float("PARKPULSE_RETRY_BASE_DELAY_SECONDS", 0.2)
    retry_max = max_delay if max_delay is not None else _env_float("PARKPULSE_RETRY_MAX_DELAY_SECONDS", 2.0)
    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = await operation()
            breaker.record_success()
            return result
        except BaseException as error:
            last_error = error
            breaker.record_failure(error)
            if attempt >= max_attempts or not retryable(error):
                raise
            await asyncio.sleep(_sleep_seconds(attempt, retry_delay, retry_max))

    raise RuntimeError(f"{name} failed without an exception.") from last_error


def reliability_status() -> dict[str, Any]:
    return {
        "enabled": not _truthy(os.getenv("PARKPULSE_DISABLE_RELIABILITY")),
        "retry_attempts": _env_int("PARKPULSE_RETRY_ATTEMPTS", 2),
        "retry_base_delay_seconds": _env_float("PARKPULSE_RETRY_BASE_DELAY_SECONDS", 0.2),
        "retry_max_delay_seconds": _env_float("PARKPULSE_RETRY_MAX_DELAY_SECONDS", 2.0),
        "circuit_breakers": registry.snapshot(),
    }
