from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.ml.baseline_config import BaselineConfig
from backend.app.ml.baseline_engineering import BaselineEngineer

METRICS = [
    "duty_hours_7d", "duty_hours_30d", "night_shifts_30d", "duty_density_30d",
    "avg_rest_7d", "min_rest_7d", "training_hours_30d", "incident_count_30d",
]


def fixture() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-01-01", periods=21, freq="D")
    for person_id, role, dep, unit_type, base in [
        ("P1", "OPERATIONS", "FIELD", "FIELD", 10.0),
        ("P2", "OPERATIONS", "FIELD", "FIELD", 14.0),
        ("P3", "PATROL", "BORDER", "BORDER", 8.0),
        ("P4", "PATROL", "BORDER", "BORDER", 9.0),
    ]:
        for i, date in enumerate(dates):
            row = {
                "person_id": person_id, "date": date,
                "role": role, "deployment_type": dep, "unit_type": unit_type,
                "unit_id": "U1" if person_id in {"P1", "P2"} else "U2",
            }
            for metric in METRICS:
                row[metric] = base + (i % 3)
            rows.append(row)
    df = pd.DataFrame(rows)
    df.loc[(df.person_id == "P1") & (df.date == "2026-01-15"), "duty_hours_7d"] = 99.0
    return df


def engineer(df: pd.DataFrame, min_personal=5, min_cohort=2, min_operational=2) -> pd.DataFrame:
    return BaselineEngineer(BaselineConfig(
        minimum_personal_history_days=min_personal,
        minimum_cohort_size=min_cohort,
        minimum_operational_size=min_operational,
    )).build_features(df)


def test_personal_baseline_and_sufficiency():
    out = engineer(fixture())
    early = out[(out.person_id == "P1") & (out.date == "2026-01-04")].iloc[0]
    late = out[(out.person_id == "P1") & (out.date == "2026-01-10")].iloc[0]
    assert pd.isna(early.duty_hours_7d_personal_history_mean)
    assert bool(late.duty_hours_7d_personal_history_sufficient)
    assert late.duty_hours_7d_personal_history_count >= 5


def test_personal_history_is_strictly_prior_days():
    out = engineer(fixture())
    target_date = pd.Timestamp("2026-01-15")
    target = out[(out.person_id == "P1") & (out.date == target_date)].iloc[0]
    prior = fixture()
    prior = prior[(prior.person_id == "P1") & (prior.date < target_date)]
    assert np.isclose(target.duty_hours_7d_personal_history_mean, prior.duty_hours_7d.mean())


def test_cohort_and_operational_baselines_exist():
    out = engineer(fixture(), min_cohort=1, min_operational=1)
    row = out[(out.person_id == "P1") & (out.date == "2026-01-15")].iloc[0]
    assert not pd.isna(row.duty_hours_7d_cohort_baseline_mean)
    assert not pd.isna(row.duty_hours_7d_operational_baseline_mean)
    assert row.duty_hours_7d_cohort_cohort_size == 1 or row.duty_hours_7d_cohort_size == 1.0


def test_small_cohort_preserves_missingness():
    df = fixture()[fixture().person_id != "P2"].copy()
    out = engineer(df, min_cohort=2, min_operational=10)
    assert out.duty_hours_7d_cohort_baseline_mean.isna().all()
    assert (~out.duty_hours_7d_cohort_sufficient.astype(bool)).all()
    assert out.duty_hours_7d_operational_baseline_mean.isna().all()


def test_missing_metric_values_are_not_zero_filled():
    df = fixture()
    df.loc[(df.person_id == "P1") & (df.date <= "2026-01-07"), "avg_rest_7d"] = np.nan
    out = engineer(df)
    row = out[(out.person_id == "P1") & (out.date == "2026-01-05")].iloc[0]
    assert pd.isna(row.avg_rest_7d_personal_history_mean)


def test_zero_denominator_relative_deviation_is_nan():
    df = fixture()
    df.loc[df.person_id == "P1", "incident_count_30d"] = 0.0
    out = engineer(df, min_personal=2)
    row = out[(out.person_id == "P1") & (out.date == "2026-01-10")].iloc[0]
    assert pd.isna(row.incident_count_30d_personal_relative_deviation)


def test_future_event_does_not_change_baselines():
    df = fixture()
    before = engineer(df)
    target_date = pd.Timestamp("2026-01-15")
    future = df.copy()
    new_row = future[(future.person_id == "P1") & (future.date == target_date)].copy()
    new_row["date"] = pd.Timestamp("2026-02-01")
    new_row["duty_hours_7d"] = 100000.0
    future = pd.concat([future, new_row], ignore_index=True)
    after = engineer(future)
    b = before[(before.person_id == "P1") & (before.date == target_date)].iloc[0]
    a = after[(after.person_id == "P1") & (after.date == target_date)].iloc[0]
    for col in [
        "duty_hours_7d_personal_history_mean",
        "duty_hours_7d_cohort_baseline_mean",
        "duty_hours_7d_operational_baseline_mean",
    ]:
        assert np.isclose(b[col], a[col], equal_nan=True)


def test_person_day_uniqueness_and_forbidden_fields():
    out = engineer(fixture())
    assert not out.duplicated(["person_id", "date"]).any()
    assert not ({"stress_score", "risk_score", "stress_label"} & set(out.columns))


def test_deterministic_output():
    a = engineer(fixture()).sort_index(axis=1)
    b = engineer(fixture()).sort_index(axis=1)
    pd.testing.assert_frame_equal(a, b)
