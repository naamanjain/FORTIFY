"""Explicit data quality checks for the FORTIFY pipeline.

Welfare decisions must not silently rest on broken input. This module inspects
the generated datasets *before* they feed features, baselines, models and the
dashboard, and reports findings in three severities:

* ``error``   - the dataset is wrong in a way that invalidates downstream use.
* ``warning`` - usable, but a human should look: odd distributions, stale data.
* ``info``    - a fact about the data worth recording (row counts, date ranges).

The checks are structural and statistical only. They never assert anything
about real people, and they never claim the synthetic data is "valid welfare
data" - only that it is internally consistent for prototype use.

Every check is deterministic and cheap enough to run inside the generation
pipeline and at API readiness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

# Column-level expectations per table: (column, lower, upper) inclusive, or
# None for unbounded. Values outside the range are impossible for the field's
# definition, not merely unusual.
RANGE_EXPECTATIONS: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "duty_events": {
        "duration_hours": (0.0, 24.0),
        "intensity_level": (1.0, 5.0),
        "night_shift": (0.0, 1.0),
    },
    "recovery_events": {"rest_duration_hours": (0.0, 24.0)},
    "incident_events": {"intensity_level": (1.0, 5.0), "recovery_requirement": (0.0, 24.0)},
    "wellness_events": {
        "mood_score": (1.0, 5.0),
        "energy_score": (1.0, 5.0),
        "sleep_quality": (1.0, 5.0),
        "perceived_stress": (1.0, 5.0),
        "workload_manageability": (1.0, 5.0),
    },
    "deployment_events": {"intensity_level": (1.0, 5.0)},
    "training_events": {"duration_hours": (0.0, 24.0)},
}

DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "duty_events": ("date", "timestamp"),
    "recovery_events": ("date",),
    "leave_events": ("start_date", "end_date"),
    "deployment_events": ("start_date", "end_date"),
    "training_events": ("date",),
    "incident_events": ("date",),
    "wellness_events": ("date",),
}

# Event tables must reference personnel that exist. A broken join silently
# turns into NaN features, which then become imputed medians - so this is an
# error, not a warning.
PERSON_KEYED_TABLES = (
    "duty_events", "recovery_events", "leave_events",
    "deployment_events", "training_events", "incident_events", "wellness_events",
)

# A dataset older than this many days relative to its own latest event is
# considered stale for an operational dashboard.
STALE_DATA_DAYS = 45

# Columns whose absence is meaningful, not an error. Sparseness here is a
# property of the domain - for example, a duty record only carries a
# deployment_id when that duty was performed while deployed - so reporting it
# as a data fault would generate permanent noise that hides real problems.
NULLABLE_BY_DOMAIN: dict[str, set[str]] = {
    "duty_events": {"deployment_id"},
    "leave_events": {"approved_by", "leave_type"},
    "incident_events": {"deployment_id", "reporting_officer"},
    "training_events": {"deployment_id"},
}


@dataclass
class Finding:
    severity: str  # error | warning | info
    table: str
    check: str
    message: str
    count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity, "table": self.table, "check": self.check,
            "message": self.message, "count": self.count,
        }


@dataclass
class QualityReport:
    findings: list[Finding] = field(default_factory=list)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    generated_at: str = ""

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [f.as_dict() for f in self.findings],
            "tables": self.tables,
            "generated_at": self.generated_at,
        }


def _pct(value: int, total: int) -> float:
    return round(100.0 * value / total, 3) if total else 0.0


def _check_duplicates(table: str, frame: pd.DataFrame, keys: list[str], report: QualityReport) -> None:
    total = len(frame)
    duplicates = int(frame.duplicated(keys).sum())
    report.tables.setdefault(table, {})["rows"] = total
    report.tables.setdefault(table, {})["key"] = keys
    if duplicates:
        report.findings.append(Finding(
            "error", table, "duplicate_key",
            f"{duplicates} duplicate {keys} rows; welfare features assume one row per key.",
            duplicates,
        ))


def _check_missing(table: str, frame: pd.DataFrame, report: QualityReport, limit: float = 50.0) -> None:
    if frame.empty:
        return
    domain_nullable = NULLABLE_BY_DOMAIN.get(table, set())
    for column in frame.columns:
        missing = int(frame[column].isna().sum())
        if not missing:
            continue
        share = _pct(missing, len(frame))
        if column in domain_nullable:
            # Meaningful sparseness. Recorded as info so the fact is visible
            # without polluting the error/warning signal.
            report.findings.append(Finding(
                "info", table, "sparse_by_design",
                f"Column '{column}' is populated for {100 - share:.1f}% of rows "
                "(sparse by design, not a data fault).",
                missing,
            ))
            continue
        severity = "warning" if share <= limit else "error"
        report.findings.append(Finding(
            severity, table, "missing_values",
            f"Column '{column}' is missing {missing} values ({share}%).",
            missing,
        ))


def _check_ranges(table: str, frame: pd.DataFrame, report: QualityReport) -> None:
    expectations = RANGE_EXPECTATIONS.get(table, {})
    for column, (low, high) in expectations.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        low_bad = values.lt(low) if low is not None else pd.Series(False, index=values.index)
        high_bad = values.gt(high) if high is not None else pd.Series(False, index=values.index)
        impossible = int((low_bad | high_bad).sum())
        if impossible:
            span = f"[{low}, {high}]"
            report.findings.append(Finding(
                "error", table, "impossible_values",
                f"Column '{column}' has {impossible} values outside its defined range {span}.",
                impossible,
            ))


def _check_dates(table: str, frame: pd.DataFrame, report: QualityReport, today: pd.Timestamp) -> None:
    columns = [c for c in DATE_COLUMNS.get(table, ()) if c in frame.columns]
    for column in columns:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        unparseable = int(parsed.isna().sum() - frame[column].isna().sum())
        if unparseable:
            report.findings.append(Finding(
                "error", table, "invalid_dates",
                f"Column '{column}' has {unparseable} values that are not valid dates.",
                unparseable,
            ))
    # Interval sanity: end before start is always wrong.
    pairs = {"leave_events": ("start_date", "end_date"), "deployment_events": ("start_date", "end_date")}
    if table in pairs:
        start_col, end_col = pairs[table]
        if start_col in frame.columns and end_col in frame.columns:
            start = pd.to_datetime(frame[start_col], errors="coerce")
            end = pd.to_datetime(frame[end_col], errors="coerce")
            inverted = int((end < start).sum())
            if inverted:
                report.findings.append(Finding(
                    "error", table, "inverted_interval",
                    f"{inverted} rows have {end_col} earlier than {start_col}.",
                    inverted,
                ))


def _check_references(data: dict[str, pd.DataFrame], report: QualityReport) -> None:
    personnel = data.get("personnel")
    if personnel is None or personnel.empty:
        report.findings.append(Finding("error", "personnel", "empty_table", "personnel.csv is empty."))
        return
    known = set(personnel["person_id"].astype(str))
    for table in PERSON_KEYED_TABLES:
        frame = data.get(table)
        if frame is None:
            continue
        orphans = set(frame["person_id"].astype(str)) - known
        if orphans:
            report.findings.append(Finding(
                "error", table, "broken_reference",
                f"{len(orphans)} person_id values are not present in personnel.csv.",
                len(orphans),
            ))
    units = data.get("units")
    if units is not None and "unit_id" in personnel.columns and "unit_id" in units.columns:
        unit_ids = set(units["unit_id"].astype(str))
        unknown_units = set(personnel["unit_id"].astype(str)) - unit_ids
        if unknown_units:
            report.findings.append(Finding(
                "error", "personnel", "broken_reference",
                f"{len(unknown_units)} unit_id values are not present in units.csv.",
                len(unknown_units),
            ))


def _check_distribution_shift(table: str, frame: pd.DataFrame, report: QualityReport) -> None:
    """Flag columns whose distribution is implausible for their definition.

    These are heuristics, deliberately conservative: they exist to catch a
    broken generator or a bad export, not to second-guess real variance.
    """
    numeric = [c for c in frame.select_dtypes(include=[np.number]).columns]
    for column in numeric:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if len(values) < 100:
            continue
        std = float(values.std())
        mean = float(values.mean())
        if std == 0.0:
            report.findings.append(Finding(
                "warning", table, "zero_variance",
                f"Column '{column}' is constant across all rows; it carries no signal.",
                0,
            ))
            continue
        extreme = int((values > mean + 12 * std).sum()) + int((values < mean - 12 * std).sum())
        if extreme:
            report.findings.append(Finding(
                "warning", table, "unexpected_distribution",
                f"Column '{column}' has {extreme} extreme outliers (>12 sigma).",
                extreme,
            ))


def _check_staleness(data: dict[str, pd.DataFrame], report: QualityReport, today: pd.Timestamp) -> None:
    operational_dates: list[pd.Timestamp] = []
    for table, columns in DATE_COLUMNS.items():
        frame = data.get(table)
        if frame is None:
            continue
        for column in columns:
            if column in frame.columns:
                parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
                if not parsed.empty:
                    operational_dates.append(parsed.max())
    if not operational_dates:
        return
    latest = max(operational_dates)
    age_days = int((today - latest).days)
    report.tables["__dataset__"]["latest_event_date"] = str(latest.date())
    report.tables["__dataset__"]["age_days"] = age_days
    if age_days > STALE_DATA_DAYS:
        report.findings.append(Finding(
            "warning", "__dataset__", "stale_data",
            f"Latest event is {age_days} days old (older than {STALE_DATA_DAYS}); "
            "the operational picture may be out of date.",
            age_days,
        ))


def audit(data_dir: str | Path, today: datetime | None = None) -> QualityReport:
    """Run every check against the generated datasets in ``data_dir``.

    Returns a report; never raises. A missing file is recorded as an error so a
    partial dataset is visible instead of silently half-loaded.
    """

    data_dir = Path(data_dir)
    now = today or datetime.now(timezone.utc)
    # Normalise to a naive date: event dates in the CSVs are naive, and the
    # staleness comparison is a day-count, not an instant comparison.
    today_ts = pd.Timestamp(now).tz_localize(None).normalize()
    report = QualityReport(generated_at=now.isoformat())

    expected_tables = [
        "personnel", "units", "duty_events", "recovery_events", "leave_events",
        "deployment_events", "training_events", "incident_events", "wellness_events",
    ]
    data: dict[str, pd.DataFrame] = {}
    for name in expected_tables:
        path = data_dir / f"{name}.csv"
        if not path.exists():
            report.findings.append(Finding(
                "error", name, "missing_file", f"{name}.csv is missing from {data_dir}."
            ))
            report.tables[name] = {"present": False}
            continue
        try:
            frame = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001
            report.findings.append(Finding(
                "error", name, "unreadable_file", f"{name}.csv could not be parsed: {type(exc).__name__}."
            ))
            report.tables[name] = {"present": False}
            continue
        data[name] = frame
        report.tables[name] = {"present": True, "rows": len(frame), "columns": len(frame.columns)}

    if not data:
        return report

    report.tables["__dataset__"] = {}

    key_columns = {
        "personnel": ["person_id"], "units": ["unit_id"],
        "duty_events": ["duty_event_id"], "recovery_events": ["recovery_event_id"],
        "leave_events": ["leave_event_id"], "deployment_events": ["deployment_event_id"],
        "training_events": ["training_event_id"], "incident_events": ["incident_event_id"],
        "wellness_events": ["wellness_event_id"],
    }
    for name, frame in data.items():
        keys = [k for k in key_columns.get(name, []) if k in frame.columns]
        if keys:
            _check_duplicates(name, frame, keys, report)
        _check_missing(name, frame, report)
        _check_ranges(name, frame, report)
        _check_dates(name, frame, report, today_ts)
        _check_distribution_shift(name, frame, report)

    _check_references(data, report)
    _check_staleness(data, report, today_ts)

    # Order findings deterministically: errors first, then by table and check.
    order = {"error": 0, "warning": 1, "info": 2}
    report.findings.sort(key=lambda f: (order[f.severity], f.table, f.check, f.message))
    return report


def summarize(report: QualityReport) -> dict[str, Any]:
    """Compact summary suitable for /ready and system-health payloads."""
    return {
        "ok": report.ok,
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
        "top_errors": [f.message for f in report.errors[:5]],
        "top_warnings": [f.message for f in report.warnings[:5]],
    }
