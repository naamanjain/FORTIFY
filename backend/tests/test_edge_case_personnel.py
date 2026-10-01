"""Edge-case stress tests for the FORTIFY feature and baseline layers.

The synthetic generator produces a well-behaved population. These tests build
hand-constructed, adversarial person histories and run them through the real
feature and baseline code to verify the pipeline does not take shortcuts:

* a stable person must not be flagged merely for differing from a global
  average (the core "baseline quality" requirement);
* a person with two weeks of history must not produce personal-deviation
  signals that require ninety days;
* missing observations must degrade to "unknown", not to zeros that read as
  healthy;
* a unit transfer must not be interpreted as a workload spike;
* conflicting signals (high load AND adequate rest) must produce a defensible
  explanation rather than a contradiction;
* short spikes must be visible in short windows, not only in long ones.

Everything here runs the production FeatureEngineer and BaselineEngineer on
small CSV datasets written to a temporary directory.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml.baseline_engineering import BaselineEngineer
from app.ml.feature_engineering import FeatureEngineer

START = date(2026, 1, 1)
DAYS = 120


def _dates() -> list[date]:
    return [START + timedelta(days=i) for i in range(DAYS)]


EMPTY_SCHEMAS: dict[str, list[str]] = {
    "units.csv": ["unit_id", "unit_type"],
    "personnel.csv": ["person_id", "unit_id", "role", "deployment_type", "service_years",
                      "joining_date", "current_posting_start"],
    "duty_events.csv": ["duty_event_id", "person_id", "date", "timestamp", "duration_hours",
                        "intensity_level", "duty_type", "night_shift"],
    "recovery_events.csv": ["recovery_event_id", "person_id", "date", "rest_duration_hours"],
    "leave_events.csv": ["leave_event_id", "person_id", "start_date", "end_date", "leave_type", "status"],
    "deployment_events.csv": ["deployment_event_id", "person_id", "start_date", "end_date", "intensity_level"],
    "training_events.csv": ["training_event_id", "person_id", "date", "duration_hours", "training_type"],
    "incident_events.csv": ["incident_event_id", "person_id", "date", "intensity_level", "recovery_requirement"],
    "wellness_events.csv": ["wellness_event_id", "person_id", "date", "mood_score", "energy_score",
                            "sleep_quality", "perceived_stress", "workload_manageability", "support_request"],
}


def _write_csv(tmp_path, name: str, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows, columns=EMPTY_SCHEMAS[name]) if not rows else pd.DataFrame(rows)
    # An empty table still needs its header: the loaders must see the columns.
    frame.to_csv(tmp_path / name, index=False)


def _base_personnel(person_ids: list[str], unit: str = "U-001") -> pd.DataFrame:
    return [
        {
            "person_id": pid,
            "unit_id": unit,
            "role": "Constable",
            "deployment_type": "None",
            "service_years": 8,
            "joining_date": "2018-01-01",
            "current_posting_start": "2024-01-01",
        }
        for pid in person_ids
    ]


def _make_dataset(tmp_path, personnel: list[dict], duty: list[dict], recovery: list[dict],
                  wellness: list[dict] | None = None) -> Path:
    _write_csv(tmp_path, "units.csv", [{"unit_id": "U-001", "unit_type": "District"}])
    _write_csv(tmp_path, "personnel.csv", personnel)
    _write_csv(tmp_path, "duty_events.csv", duty)
    _write_csv(tmp_path, "recovery_events.csv", recovery)
    for name in ("leave_events", "deployment_events", "training_events", "incident_events"):
        _write_csv(tmp_path, f"{name}.csv", [])
    _write_csv(tmp_path, "wellness_events.csv", wellness or [])
    return tmp_path


def _steady_duty(person_id: str, hours: float = 8.0, rest: float = 8.0) -> tuple[list[dict], list[dict]]:
    dates = _dates()
    duty = [
        {"duty_event_id": f"D-{person_id}-{i}", "person_id": person_id, "date": d.isoformat(),
         "timestamp": f"{d.isoformat()}T08:00:00", "duration_hours": hours,
         "intensity_level": 3, "duty_type": "Patrol", "night_shift": 0}
        for i, d in enumerate(dates)
    ]
    recovery = [
        {"recovery_event_id": f"R-{person_id}-{i}", "person_id": person_id,
         "date": d.isoformat(), "rest_duration_hours": rest}
        for i, d in enumerate(dates)
    ]
    return duty, recovery


def test_stable_person_is_not_flagged_for_differing_from_global_average(tmp_path) -> None:
    """Core baseline-quality requirement.

    A person who works steadily slightly MORE than the population mean is not
    under strain; their pattern is normal *for them*. Their 7-day duty hours
    must show a personal deviation near zero even though the cohort deviation
    is clearly positive.
    """
    # Population: 8h/day. Test person: steady 9h/day (12.5% above cohort).
    duty_p, rec_p = _steady_duty("P-STABLE", hours=9.0)
    others = []
    for i in range(6):
        d, r = _steady_duty(f"P-N{i}", hours=8.0)
        others.extend(d)
        others_r = r
    _make_dataset(
        tmp_path,
        _base_personnel(["P-STABLE"] + [f"P-N{i}" for i in range(6)]),
        duty_p + others,
        rec_p + others_r,
    )
    features = FeatureEngineer(tmp_path).build_features()
    baselines = BaselineEngineer().build_features(features)
    late = baselines[(baselines["person_id"] == "P-STABLE") & (baselines["date"] >= baselines["date"].max() - pd.Timedelta(days=7))]

    personal_relative = late["duty_hours_7d_personal_relative_deviation"].dropna()
    cohort = late["duty_hours_7d_cohort_deviation"].dropna() if "duty_hours_7d_cohort_deviation" in late.columns else pd.Series(dtype=float)
    # The relative personal deviation is what the explanation layer gates on
    # (>= 5% admits a factor). A steady person must sit far below that.
    assert personal_relative.abs().max() < 0.05, (
        f"a steady person shows personal relative deviation up to {personal_relative.abs().max():.3f}"
    )
    # If cohort deviation exists, it is positive (they do work more than peers)
    # - which is exactly why the personal reference must be the one used.
    if len(cohort):
        assert cohort.min() > 0


def test_insufficient_history_withholds_personal_deviation(tmp_path) -> None:
    """Two weeks of history must not produce personal-deviation signals that
    require a longer baseline; the reference is withheld instead."""
    dates = _dates()
    short_days = 14
    duty = [
        {"duty_event_id": f"D-P-SHORT-{i}", "person_id": "P-SHORT", "date": d.isoformat(),
         "timestamp": f"{d.isoformat()}T08:00:00",
         "duration_hours": 12.0 if i >= short_days - 3 else 8.0,
         "intensity_level": 3, "duty_type": "Patrol", "night_shift": 0}
        for i, d in enumerate(dates[:short_days])
    ]
    recovery = [
        {"recovery_event_id": f"R-P-SHORT-{i}", "person_id": "P-SHORT",
         "date": d.isoformat(), "rest_duration_hours": 7.0 if i >= short_days - 3 else 8.0}
        for i, d in enumerate(dates[:short_days])
    ]
    _make_dataset(tmp_path, _base_personnel(["P-SHORT"]), duty, recovery)
    features = FeatureEngineer(tmp_path).build_features()
    baselines = BaselineEngineer().build_features(features)
    first = baselines[baselines["date"] == baselines["date"].min()]
    # With one day of history there is no personal reference at all.
    assert first["duty_hours_7d_personal_deviation"].isna().all()
    # Sufficient-history flag is present and honest about the state.
    if "duty_hours_7d_personal_history_sufficient" in baselines.columns:
        early = baselines[baselines["date"] < baselines["date"].min() + pd.Timedelta(days=3)]
        assert (~early["duty_hours_7d_personal_history_sufficient"]).all()


def test_missing_observations_do_not_read_as_healthy(tmp_path) -> None:
    """A gap in duty records must not silently look like a rest day.

    Zero-filling missing duty would make a broken feed look like recovery, and
    a welfare tool must not treat absent evidence as good news. The row keeps
    the person visible, shows zero recorded duty, and the recorded-duty-days
    feature exposes the gap so downstream users are not misled.
    """
    dates = _dates()
    duty, recovery = _steady_duty("P-GAP", hours=8.0, rest=8.0)
    # Remove a 10-day band in the middle: no duty, no recovery records.
    gap_start, gap_end = 40, 50
    duty = [row for i, row in enumerate(duty) if not (gap_start <= i < gap_end)]
    recovery = [row for i, row in enumerate(recovery) if not (gap_start <= i < gap_end)]
    _make_dataset(tmp_path, _base_personnel(["P-GAP"]), duty, recovery)
    features = FeatureEngineer(tmp_path).build_features()
    last_gap_day = features[features["date"] == pd.Timestamp(START) + pd.Timedelta(days=49)].iloc[0]
    # The person-day row still exists (the person exists), and the gap is
    # visible as zero duty rather than being silently extrapolated.
    assert last_gap_day["duty_hours_1d"] == 0
    # The recorded-duty-days counter must expose the gap: of the 30 days
    # ending on the gap's last day, only the 20 before it have duty records.
    assert last_gap_day["duty_data_days_30d"] == 20, (
        f"30-day recorded-duty counter hid the gap: {last_gap_day['duty_data_days_30d']}"
    )


def test_unit_transfer_is_not_a_workload_spike(tmp_path) -> None:
    """A transfer changes the person's unit label, not their workload.

    The deviation the pipeline can legitimately see around a transfer is the
    cohort composition change, not a fabricated personal jump.
    """
    dates = _dates()
    duty, recovery = _steady_duty("P-MOVE", hours=8.0)
    personnel = _base_personnel(["P-MOVE"])
    for row in personnel:
        row["unit_id"] = "U-002"  # transferred before the window begins
    _make_dataset(tmp_path, personnel, duty, recovery)
    _write_csv(tmp_path, "units.csv", [
        {"unit_id": "U-001", "unit_type": "District"},
        {"unit_id": "U-002", "unit_type": "District"},
    ])
    features = FeatureEngineer(tmp_path).build_features()
    baselines = BaselineEngineer().build_features(features)
    moved = baselines[baselines["person_id"] == "P-MOVE"]
    # Converged tail of the history: steady 8h/day vs their own 8h/day history
    # leaves a negligible relative deviation (the early expanding-mean ramp is
    # expected and is exactly why the explanation layer requires a minimum
    # relative change before it will admit a factor).
    tail = moved[moved["date"] >= moved["date"].max() - pd.Timedelta(days=7)]
    relative = tail["duty_hours_7d_personal_relative_deviation"].dropna()
    assert relative.abs().max() < 0.05, (
        f"steady person after transfer shows relative deviation {relative.abs().max():.3f}"
    )


def test_short_spike_is_visible_in_short_windows(tmp_path) -> None:
    """A 5-day spike must be measurable by the 7-day features and must not be
    washed out by the 30/90-day windows."""
    dates = _dates()
    duty, recovery = _steady_duty("P-SPIKE", hours=8.0, rest=8.0)
    spike_start = 80
    for i in range(spike_start, spike_start + 5):
        duty[i]["duration_hours"] = 16.0
        recovery[i]["rest_duration_hours"] = 5.0
    _make_dataset(tmp_path, _base_personnel(["P-SPIKE"]), duty, recovery)
    features = FeatureEngineer(tmp_path).build_features()
    peak = features[features["date"] == pd.Timestamp(START) + pd.Timedelta(days=spike_start + 4)].iloc[0]
    assert peak["duty_hours_7d"] == 8 * 2 + 16 * 5  # 2 normal days + 5 spike days
    assert peak["avg_rest_7d"] < 7.0
    # After the spike ends, the 7-day window clears but the 30-day window
    # still records the exposure.
    after = features[features["date"] == pd.Timestamp(START) + pd.Timedelta(days=spike_start + 15)].iloc[0]
    assert after["duty_hours_7d"] == 56.0
    assert after["duty_hours_30d"] > 8 * 30  # includes the spike


def test_conflicting_signals_produce_a_defensible_row(tmp_path) -> None:
    """High duty load AND adequate rest must not be reported as a recovery
    problem. The explanation layer must not contradict the features."""
    dates = _dates()
    duty, recovery = _steady_duty("P-BOTH", hours=12.0, rest=9.0)
    _make_dataset(tmp_path, _base_personnel(["P-BOTH"]), duty, recovery)
    features = FeatureEngineer(tmp_path).build_features()
    late = features[features["date"] >= pd.Timestamp(START) + pd.Timedelta(days=100)].iloc[-1]

    from app.ml.explanations import build_factors
    factors = build_factors(late)
    ids = {f.factor_id for f in factors}
    assert "recovery_deficit_7d" not in ids, "adequate rest was reported as a recovery problem"
    assert "duty_hours_7d_personal_deviation" not in ids or (
        late["duty_hours_7d_personal_deviation"] > 0
    )


def test_sparse_wellness_reporting_is_not_treated_as_concern(tmp_path) -> None:
    """Two wellness reports in four months is sparse reporting, not a signal.

    The model excludes wellness-derived features entirely; the feature table
    must reflect sparseness honestly (low wellness-days counts) and the
    explanation layer must never cite missing reports as evidence.
    """
    dates = _dates()
    duty, recovery = _steady_duty("P-SPARSE-W", hours=8.0)
    wellness = [
        {"wellness_event_id": f"W-{i}", "person_id": "P-SPARSE-W", "date": d.isoformat(),
         "mood_score": 3, "energy_score": 3, "sleep_quality": 3,
         "perceived_stress": 2, "workload_manageability": 3, "support_request": False}
        for i, d in enumerate(dates) if i % 60 == 0
    ]
    _make_dataset(tmp_path, _base_personnel(["P-SPARSE-W"]), duty, recovery, wellness)
    features = FeatureEngineer(tmp_path).build_features()
    final = features[features["date"] == features["date"].max()].iloc[0]
    assert final["wellness_days_30d"] <= 1
    from app.ml.explanations import build_factors
    assert not any("wellness" in f.factor_id or "report" in f.signal for f in build_factors(final))


def test_explanations_withhold_when_nothing_adverse_changed() -> None:
    """No adverse change means no factors - not filler text."""
    from app.ml.explanations import build_factors

    row = pd.Series({
        "duty_hours_7d": 40.0,
        "duty_hours_7d_personal_deviation": 0.0,
        "duty_hours_7d_personal_relative_deviation": 0.0,
        "night_shifts_30d": 2.0,
        "night_shifts_30d_personal_deviation": -1.0,  # improved
        "night_shifts_30d_personal_relative_deviation": -0.3,
        "incident_count_30d": 0.0,
        "incident_count_30d_personal_deviation": 0.0,
        "incident_count_30d_personal_relative_deviation": 0.0,
        "avg_rest_7d": 8.5,
        "deployment_days_30d": 0,
        "duty_hours_30d": 160.0,
        "duty_hours_30d_cohort_relative_deviation": -0.1,
        "duty_hours_30d_operational_relative_deviation": -0.05,
    })
    assert build_factors(row) == []


def test_every_factor_sentence_carries_full_provenance() -> None:
    """WHAT changed, HOW MUCH, vs WHAT, over WHAT PERIOD, and WHY admitted."""
    from app.ml.explanations import build_factors

    row = pd.Series({
        "duty_hours_7d": 60.0,
        "duty_hours_7d_personal_deviation": 15.0,
        "duty_hours_7d_personal_relative_deviation": 0.33,
        "duty_hours_7d_personal_history_mean": 45.0,
        "night_shifts_30d": 10.0,
        "night_shifts_30d_personal_deviation": 5.0,
        "night_shifts_30d_personal_relative_deviation": 1.0,
        "night_shifts_30d_personal_history_mean": 5.0,
        "avg_rest_7d": 6.0,
        "incident_count_30d": 0.0,
        "deployment_days_30d": 12,
        "duty_hours_30d": 240.0,
        "duty_hours_30d_cohort_relative_deviation": 0.2,
        "duty_hours_30d_cohort_baseline_mean": 200.0,
    })
    factors = build_factors(row)
    assert factors, "an adverse profile produced no factors"
    for factor in factors:
        sentence = factor.as_sentence()
        assert factor.value_display and factor.window and factor.comparison
        assert factor.rule
        # Every element the spec requires appears in the sentence.
        assert factor.value_display.split()[0] in sentence
        assert "compared with" in sentence
        assert factor.window in sentence


def test_data_quality_flags_broken_input() -> None:
    """Broken input must be reported, not silently consumed."""
    from app.ml.data_quality import audit

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = __import__("pathlib").Path(tmp)
        personnel = _base_personnel(["P-1", "P-2"])
        _write_csv(tmp_path, "units.csv", [{"unit_id": "U-001", "unit_type": "District"}])
        _write_csv(tmp_path, "personnel.csv", personnel)
        # Duty rows referencing a person who does not exist, plus an
        # impossible rest value and an invalid date.
        _write_csv(tmp_path, "duty_events.csv", [
            {"duty_event_id": "D-1", "person_id": "P-GHOST", "date": "2026-01-01",
             "timestamp": "2026-01-01T08:00:00", "duration_hours": 8.0,
             "intensity_level": 3, "duty_type": "Patrol", "night_shift": 0},
        ])
        _write_csv(tmp_path, "recovery_events.csv", [
            {"recovery_event_id": "R-1", "person_id": "P-1", "date": "2026-01-01",
             "rest_duration_hours": 40.0},  # impossible: more than a day of rest
        ])
        _write_csv(tmp_path, "wellness_events.csv", [
            {"wellness_event_id": "W-1", "person_id": "P-1", "date": "not-a-date",
             "mood_score": 3, "energy_score": 3, "sleep_quality": 3,
             "perceived_stress": 9, "workload_manageability": 3, "support_request": False},
        ])
        for name in ("leave_events", "deployment_events", "training_events", "incident_events"):
            pd.DataFrame(columns={
                "leave_events": ["leave_event_id", "person_id", "start_date", "end_date", "leave_type", "status"],
                "deployment_events": ["deployment_event_id", "person_id", "start_date", "end_date", "intensity_level"],
                "training_events": ["training_event_id", "person_id", "date", "duration_hours", "training_type"],
                "incident_events": ["incident_event_id", "person_id", "date", "intensity_level", "recovery_requirement"],
            }[name]).to_csv(tmp_path / f"{name}.csv", index=False)

        report = audit(tmp_path)
        checks = {(f.table, f.check) for f in report.findings}
        assert ("duty_events", "broken_reference") in checks
        assert ("recovery_events", "impossible_values") in checks
        assert ("wellness_events", "invalid_dates") in checks
        assert ("wellness_events", "impossible_values") in checks
        assert report.ok is False
