"""Observability for the FORTIFY prototype.

Three concerns, kept together because they share the redaction policy:

* **Structured logging** - JSON lines rather than free text, so a deployment
  can be aggregated without a parser. Every record carries the same keys.
* **Redaction** - FORTIFY handles welfare data. Personnel identifiers, wellness
  responses and free-text comments must never reach a log sink, because logs
  are shipped, retained and backed up far more widely than the database.
* **Metrics** - counters and histograms for the few operational facts a
  departmental deployment would actually watch.

This is deliberately small. It is not OpenTelemetry, and it does not pretend to
be: see SECURITY_MODEL.md for what a production deployment would need.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from collections import defaultdict
from typing import Any

# Any value that looks like a personnel or unit identifier is redacted wherever
# it appears in a log record, so a new call site cannot leak one by accident.
_IDENTIFIER_PATTERN = re.compile(r"\b(P|U)-\d{3,}\b")
_REDACTED = "[redacted]"

# Keys whose values are never logged, regardless of content.
_SENSITIVE_KEYS = frozenset({
    "person_id", "comment", "details", "password", "token", "authorization",
    "mood_score", "energy_score", "sleep_quality", "perceived_stress",
    "workload_manageability", "support_request", "scheduled_for",
})


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact identifiers and sensitive fields for logging."""
    if key is not None and key.lower() in _SENSITIVE_KEYS:
        return _REDACTED
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _IDENTIFIER_PATTERN.sub(_REDACTED, value)
    return value


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line, with redaction applied."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for attr in ("request_id", "method", "path", "status", "duration_ms", "principal_role", "purpose"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = redact(value)
        if record.exc_info:
            # The exception *type* is useful; its message may embed data.
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else "unknown"
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    level_name = (level or os.getenv("FORTIFY_LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level_name, logging.INFO))


class Metrics:
    """In-process counters and timers.

    Exposed via ``/metrics`` in Prometheus text format. Process-local by
    design: a multi-replica deployment needs a real metrics backend, which is
    listed as a production requirement rather than simulated here.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timings: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: int = 1, **labels: Any) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def observe(self, name: str, seconds: float, **labels: Any) -> None:
        with self._lock:
            # Bounded: a long-running process must not grow memory without limit.
            samples = self._timings[self._key(name, labels)]
            if len(samples) < 1000:
                samples.append(seconds)

    @staticmethod
    def _key(name: str, labels: dict[str, Any]) -> str:
        if not labels:
            return name
        rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{rendered}}}"

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []
            for key, value in sorted(self._counters.items()):
                safe = _IDENTIFIER_PATTERN.sub(_REDACTED, key)
                lines.append(f"fortify_{safe} {value}")
            for key, samples in sorted(self._timings.items()):
                if not samples:
                    continue
                safe = _IDENTIFIER_PATTERN.sub(_REDACTED, key)
                lines.append(f"fortify_{safe}_count {len(samples)}")
                lines.append(f"fortify_{safe}_mean_seconds {sum(samples) / len(samples):.6f}")
            return "\n".join(lines) + "\n"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "timings": {k: {"count": len(v), "mean_seconds": (sum(v) / len(v)) if v else 0.0}
                            for k, v in self._timings.items()},
            }


METRICS = Metrics()


class RateLimiter:
    """Fixed-window request counter keyed by client.

    This exists to blunt the cheapest denial-of-service against the prototype -
    repeated full-file audit verification and large CSV parses on unauthenticated
    endpoints. It is not a substitute for an edge rate limiter (nginx, CDN, or
    a gateway) in a real deployment, and it is not distributed, so it does
    nothing across replicas.
    """

    def __init__(self, limit: int = 120, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> tuple[bool, int]:
        """Return (allowed, remaining)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - self.window
            while bucket and bucket[0] < cutoff:
                bucket.pop(0)
            if len(bucket) >= self.limit:
                return False, 0
            bucket.append(now)
            return True, self.limit - len(bucket)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Opt-in so tests and the demonstration environment are unaffected.
def build_rate_limiter() -> RateLimiter | None:
    raw = os.getenv("FORTIFY_RATE_LIMIT", "").strip()
    if not raw:
        return None
    try:
        limit = int(raw)
    except ValueError:
        return None
    if limit <= 0:
        return None
    return RateLimiter(limit=limit, window_seconds=float(os.getenv("FORTIFY_RATE_WINDOW", "60")))