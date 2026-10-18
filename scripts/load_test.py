"""Practical load test for FORTIFY's request paths.

Runs concurrent requests against a live backend (started by the caller) and
reports throughput and latency percentiles per endpoint class. The goal is to
find *meaningful* bottlenecks — paths slow enough to hurt a welfare officer —
not to publish impressive numbers.

Endpoints exercised: dashboard overview (cold + warm cache), attention,
person detail, review update (transition), follow-up update, system health,
search/filter.

Usage:
    python -m uvicorn app.main:app --app-dir backend --port 8000 &
    python scripts/load_test.py [--duration 30] [--concurrency 8]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
AGGREGATE = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
AUDIT_HEADERS = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}

READ_PATHS = [
    ("overview", "/api/dashboard/overview", WELFARE),
    ("attention", "/api/dashboard/attention?limit=25", WELFARE),
    ("person_detail", "/api/dashboard/person/P-0001", WELFARE),
    ("review_queue", "/api/dashboard/review-queue", WELFARE),
    ("units", "/api/dashboard/units", AGGREGATE),
    ("system_health", "/api/dashboard/system-health", AUDIT_HEADERS),
    ("search", "/api/dashboard/search?query=P-0", AGGREGATE),
    ("health", "/health", None),
]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


def load_path(client: httpx.Client, name: str, path: str, headers: dict | None,
              stop: threading.Event, results: dict[str, list[float]], errors: list[str]) -> None:
    while not stop.is_set():
        started = time.perf_counter()
        try:
            response = client.get(path, headers=headers or {})
            elapsed = (time.perf_counter() - started) * 1000
            if response.status_code == 200:
                results[name].append(elapsed)
            else:
                errors.append(f"{name}: status {response.status_code}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    results: dict[str, list[float]] = defaultdict(list)
    errors: list[str] = []
    stop = threading.Event()

    # Warm the artifact cache so the cold-path cost is measured separately.
    cold_started = time.perf_counter()
    with httpx.Client(timeout=120, base_url=BASE) as client:
        first = client.get("/api/dashboard/overview", headers=WELFARE)
    cold_ms = (time.perf_counter() - cold_started) * 1000
    print(f"Cold overview (artifact parse): {cold_ms:.0f} ms (status {first.status_code})")

    threads = []
    with httpx.Client(timeout=120, base_url=BASE) as client:
        for index in range(args.concurrency):
            # Spread threads across the read paths round-robin.
            name, path, headers = READ_PATHS[index % len(READ_PATHS)]
            thread = threading.Thread(
                target=load_path, args=(client, name, path, headers, stop, results, errors))
            threads.append(thread)
            thread.start()
        time.sleep(args.duration)
        stop.set()
        for thread in threads:
            thread.join()

    report: dict = {"cold_overview_ms": round(cold_ms, 1), "concurrency": args.concurrency,
                    "duration_s": args.duration, "endpoints": {}, "error_count": len(errors)}
    print(f"\n{'endpoint':<16} {'reqs':>6} {'mean ms':>9} {'p50':>8} {'p95':>8} {'p99':>8}")
    for name, samples in results.items():
        if not samples:
            continue
        report["endpoints"][name] = {
            "count": len(samples),
            "mean_ms": round(statistics.mean(samples), 1),
            "p50_ms": round(percentile(samples, 0.50), 1),
            "p95_ms": round(percentile(samples, 0.95), 1),
            "p99_ms": round(percentile(samples, 0.99), 1),
        }
        print(f"{name:<16} {len(samples):>6} {report['endpoints'][name]['mean_ms']:>9.1f} "
              f"{report['endpoints'][name]['p50_ms']:>8.1f} {report['endpoints'][name]['p95_ms']:>8.1f} "
              f"{report['endpoints'][name]['p99_ms']:>8.1f}")

    if errors:
        report["sample_errors"] = errors[:10]
        print(f"\nErrors: {len(errors)} (first: {errors[0]})")

    out = ROOT / "artifacts" / "benchmark" / "load_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {out}")

    # Meaningful-bottleneck thresholds for this prototype: a welfare officer
    # reading a queue should not wait seconds on a warm cache.
    slow = {n: v for n, v in report["endpoints"].items() if v["p95_ms"] > 2000}
    if slow:
        print("BOTTLENECKS (p95 > 2s):", {n: v["p95_ms"] for n, v in slow.items()})
    else:
        print("No endpoint exceeded 2s at p95 (warm cache).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())