"""Pytest configuration: red-team evidence reporting.

Tests marked ``red_team`` constitute the security attack campaign; their
outcomes are recorded to artifacts/red_team/red_team_report.json as
EXPECTED (from the docstring) / ACTUAL (from the failure) / PASS-FAIL.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPORT: list[dict] = []


def pytest_addoption(parser):
    parser.addoption("--red-team-report", action="store_true", default=False,
                     help="Write the red-team evidence report")


def pytest_configure(config):
    config.addinivalue_line("markers", "red_team: security attack from the red-team campaign")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if "red_team" in item.keywords and report.when == "call":
        doc = (item.function.__doc__ or "").strip()
        expected = doc.splitlines()[0] if doc else item.name
        actual = "behaviour matched the expectation"
        if report.failed:
            longrepr = report.longreprtext.strip().splitlines()
            actual = longrepr[-1] if longrepr else "assertion failed"
        elif report.skipped:
            actual = str(report.longrepr).strip().splitlines()[-1] if report.longrepr else "skipped"
        _REPORT.append({
            "attack": item.name,
            "expected": expected,
            "actual": actual,
            # A skip is NOT a breach. Recording one as FAIL made the evidence
            # report claim a successful attack that was never attempted, and
            # failed CI whenever the demo data lacked a case an attack needs.
            "verdict": "PASS" if report.passed else "NOT_EXECUTED" if report.skipped else "FAIL",
        })


def pytest_sessionfinish(session, exitstatus):
    if not session.config.getoption("--red-team-report"):
        return
    out = Path("artifacts") / "red_team" / "red_team_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    counts = {v: sum(1 for r in _REPORT if r["verdict"] == v)
              for v in ("PASS", "FAIL", "NOT_EXECUTED")}
    summary = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total": len(_REPORT),
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "not_executed": counts["NOT_EXECUTED"],
        "attacks": _REPORT,
    }
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print()
    print("Red-team report written:", out,
          f"({counts['PASS']}/{summary['total']} attacks held; "
          f"{counts['FAIL']} breached; {counts['NOT_EXECUTED']} not executed)")
