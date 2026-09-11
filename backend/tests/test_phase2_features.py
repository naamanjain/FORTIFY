import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from backend.app.ml import FeatureEngineer


COLUMNS = {
    "personnel": ["person_id", "unit_id", "role", "deployment_type", "service_years", "joining_date", "current_posting_start"],
    "units": ["unit_id", "unit_type"],
    "duty_events": ["duty_event_id", "person_id", "timestamp", "date", "duty_type", "duration_hours", "night_shift", "intensity_level", "deployment_id"],
    "recovery_events": ["recovery_event_id", "person_id", "date", "rest_duration_hours"],
    "leave_events": ["leave_event_id", "person_id", "start_date", "end_date", "duration_days", "leave_type", "status"],
    "deployment_events": ["deployment_event_id", "person_id", "deployment_type", "start_date", "end_date", "intensity_level", "location_type"],
    "training_events": ["training_event_id", "person_id", "date", "duration_hours", "training_type", "intensity_level"],
    "incident_events": ["incident_event_id", "person_id", "date", "incident_type", "intensity_level", "recovery_requirement"],
    "wellness_events": ["wellness_event_id", "person_id", "date", "mood_score", "energy_score", "sleep_quality", "perceived_stress", "workload_manageability", "support_request"],
}


def write_fixture(root: Path, *, add_future: bool = False, add_boundary_event: bool = False, wellness: bool = True):
    person = pd.DataFrame([{
        "person_id": "P-0001", "unit_id": "U-1", "role": "OPERATIONS", "deployment_type": "FIELD",
        "service_years": 5, "joining_date": "2020-01-01", "current_posting_start": "2025-01-01"
    }])
    unit = pd.DataFrame([{"unit_id": "U-1", "unit_type": "FIELD"}])
    duty_rows = [
        {"duty_event_id": "D-1", "person_id": "P-0001", "timestamp": "2026-01-01T10:00:00", "date": "2026-01-01", "duty_type": "DAY", "duration_hours": 8, "night_shift": False, "intensity_level": 3, "deployment_id": "DEP-1"},
        {"duty_event_id": "D-2", "person_id": "P-0001", "timestamp": "2026-01-03T22:00:00", "date": "2026-01-03", "duty_type": "NIGHT", "duration_hours": 10, "night_shift": True, "intensity_level": 4, "deployment_id": "DEP-1"},
        {"duty_event_id": "D-3", "person_id": "P-0001", "timestamp": "2026-01-10T10:00:00", "date": "2026-01-10", "duty_type": "DAY", "duration_hours": 6, "night_shift": False, "intensity_level": 2, "deployment_id": ""},
    ]
    if add_boundary_event:
        duty_rows.append({"duty_event_id": "D-B", "person_id": "P-0001", "timestamp": "2026-01-03T12:00:00", "date": "2026-01-03", "duty_type": "DAY", "duration_hours": 4, "night_shift": False, "intensity_level": 2, "deployment_id": "DEP-1"})
    if add_future:
        duty_rows.append({"duty_event_id": "D-FUTURE", "person_id": "P-0001", "timestamp": "2026-01-11T10:00:00", "date": "2026-01-11", "duty_type": "EMERGENCY", "duration_hours": 20, "night_shift": True, "intensity_level": 5, "deployment_id": "DEP-1"})
    duty = pd.DataFrame(duty_rows)
    recovery = pd.DataFrame([
        {"recovery_event_id": "R-1", "person_id": "P-0001", "date": "2026-01-02", "rest_duration_hours": 5},
        {"recovery_event_id": "R-2", "person_id": "P-0001", "date": "2026-01-04", "rest_duration_hours": 9},
    ])
    leave = pd.DataFrame([{"leave_event_id": "L-1", "person_id": "P-0001", "start_date": "2026-01-06", "end_date": "2026-01-08", "duration_days": 3, "leave_type": "ANNUAL", "status": "APPROVED"}])
    deployment = pd.DataFrame([{"deployment_event_id": "DEP-1", "person_id": "P-0001", "deployment_type": "FIELD", "start_date": "2026-01-01", "end_date": "2026-01-08", "intensity_level": 4, "location_type": "FIELD"}])
    training = pd.DataFrame([{"training_event_id": "T-1", "person_id": "P-0001", "date": "2026-01-04", "duration_hours": 4, "training_type": "TACTICAL", "intensity_level": 3}])
    incident = pd.DataFrame([{"incident_event_id": "I-1", "person_id": "P-0001", "date": "2026-01-03", "incident_type": "HIGH_INTENSITY_OPERATION", "intensity_level": 4, "recovery_requirement": 6}])
    if wellness:
        wellness_df = pd.DataFrame([{"wellness_event_id": "W-1", "person_id": "P-0001", "date": "2026-01-04", "mood_score": 4, "energy_score": 3, "sleep_quality": 3, "perceived_stress": 2, "workload_manageability": 4, "support_request": False}])
    else:
        wellness_df = pd.DataFrame(columns=COLUMNS["wellness_events"])
    frames = {
        "personnel": person, "units": unit, "duty_events": duty, "recovery_events": recovery,
        "leave_events": leave, "deployment_events": deployment, "training_events": training,
        "incident_events": incident, "wellness_events": wellness_df,
    }
    for name, df in frames.items():
        df.to_csv(root / f"{name}.csv", index=False)


def make_engine(*, add_future=False, add_boundary_event=False, wellness=True):
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    write_fixture(root, add_future=add_future, add_boundary_event=add_boundary_event, wellness=wellness)
    return td, FeatureEngineer(root)


def test_person_day_grain_and_required_features():
    td, engine = make_engine()
    try:
        out = engine.build_features(start_date="2026-01-01", end_date="2026-01-10")
        assert len(out) == 10
        assert not out[["person_id", "date"]].duplicated().any()
        required = {"duty_hours_1d", "duty_hours_7d", "duty_hours_30d", "duty_hours_90d", "duty_gap_mean_7d", "avg_rest_7d", "leave_days_30d", "deployment_days_30d", "incident_count_30d", "feature_completeness_ratio"}
        assert required.issubset(out.columns)
        assert not {"stress_label", "stress_score", "risk_score", "risk_band"}.intersection(out.columns)
    finally:
        td.cleanup()


def test_rolling_boundary_excludes_day_8():
    td, engine = make_engine(add_boundary_event=True)
    try:
        out = engine.build_features(start_date="2026-01-03", end_date="2026-01-10")
        row = out[out.date.eq(pd.Timestamp("2026-01-10"))].iloc[0]
        # 7-day window is Jan 4..Jan 10; Jan 3 is outside it.
        assert row["duty_hours_7d"] == pytest.approx(6.0)
        assert row["night_shifts_7d"] == 0
    finally:
        td.cleanup()


def test_future_event_cannot_change_feature_vector_at_t():
    td1, engine1 = make_engine(add_future=False)
    td2, engine2 = make_engine(add_future=True)
    try:
        a = engine1.build_features(start_date="2026-01-01", end_date="2026-01-10")
        b = engine2.build_features(start_date="2026-01-01", end_date="2026-01-10")
        cols = [c for c in a.columns if c not in {"date"}]
        pd.testing.assert_frame_equal(a[cols], b[cols], check_dtype=False)
    finally:
        td1.cleanup(); td2.cleanup()


def test_missing_wellness_stays_missing():
    td, engine = make_engine(wellness=False)
    try:
        out = engine.build_features(start_date="2026-01-01", end_date="2026-01-10")
        assert out["wellness_available_today"].sum() == 0
        assert out["mood_latest"].isna().all()
        assert out["mood_7d_mean"].isna().all()
    finally:
        td.cleanup()


def test_zero_denominator_change_is_nan():
    td, engine = make_engine()
    try:
        out = engine.build_features(start_date="2026-01-01", end_date="2026-01-10")
        assert pd.isna(out.iloc[0]["duty_hours_7d_vs_previous_7d_relative"])
    finally:
        td.cleanup()
