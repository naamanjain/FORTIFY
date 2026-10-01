"""Explanation fidelity tests.

Every contributing factor shown to a human is a claim about data. These tests
verify the claims against the actual feature and baseline tables:

* the source feature column exists and the quoted value equals it;
* the reference matches the actual computed baseline column;
* the stated window matches the column's real rolling window;
* adverse-direction logic holds (only adverse deviations admitted);
* the admitting rule's threshold is what the config says it is;
* recommendation provenance (signal → rule → recommendation) is internally
  consistent with the policy configuration.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml.explanations import (
    MIN_RELATIVE_DEVIATION,
    RECOVERY_HOURS_REFERENCE,
    build_factors,
)

ROOT = Path(__file__).resolve().parents[2]  # backend/tests/ -> repo root

# factor_id -> (metric column, baseline/reference column, deviation column,
#               relative column, stated window)
PERSONAL_FACTORS = {
    "duty_hours_7d_personal_deviation": (
        "duty_hours_7d", "duty_hours_7d_personal_history_mean",
        "duty_hours_7d_personal_deviation", "duty_hours_7d_personal_relative_deviation",
        "last 7 days",
    ),
    "night_shifts_30d_personal_deviation": (
        "night_shifts_30d", "night_shifts_30d_personal_history_mean",
        "night_shifts_30d_personal_deviation", "night_shifts_30d_personal_relative_deviation",
        "last 30 days",
    ),
    "incident_count_30d_personal_deviation": (
        "incident_count_30d", "incident_count_30d_personal_history_mean",
        "incident_count_30d_personal_deviation", "incident_count_30d_personal_relative_deviation",
        "last 30 days",
    ),
}
CONTEXT_FACTORS = {
    "duty_hours_30d_cohort_relative_deviation": (
        "duty_hours_30d", "duty_hours_30d_cohort_baseline_mean",
        "duty_hours_30d_cohort_relative_deviation", "last 30 days",
    ),
    "duty_hours_30d_operational_relative_deviation": (
        "duty_hours_30d", "duty_hours_30d_operational_baseline_mean",
        "duty_hours_30d_operational_relative_deviation", "last 30 days",
    ),
}


@pytest.fixture(scope="module")
def feature_sample() -> pd.DataFrame:
    """A slice of real baseline-extended feature rows."""
    path = ROOT / "data" / "generated" / "person_day_features_baseline.csv"
    if not path.exists():
        pytest.skip("generated features not available; run scripts/build_all.py")
    # The table is sorted by date, so its first rows are day-1 rows where the
    # personal baselines are still NaN and no personal factor can exist. A
    # mid-history slice exercises the factors the dashboard actually shows.
    return pd.read_csv(path, skiprows=range(1, 45_001), nrows=400)


def test_every_factor_value_equals_its_source_column(feature_sample: pd.DataFrame) -> None:
    checked = 0
    for _, row in feature_sample.iterrows():
        for factor in build_factors(row, max_factors=8):
            if factor.factor_id in PERSONAL_FACTORS:
                metric_col = PERSONAL_FACTORS[factor.factor_id][0]
                assert factor.value == pytest.approx(float(row[metric_col]), abs=1e-6), (
                    f"{factor.factor_id} displayed value {factor.value} != source {row[metric_col]}"
                )
                checked += 1
            elif factor.factor_id in CONTEXT_FACTORS:
                metric_col = CONTEXT_FACTORS[factor.factor_id][0]
                assert factor.value == pytest.approx(float(row[metric_col]), abs=1e-6)
                checked += 1
    assert checked > 50, "explanation fidelity check exercised too few factors to be meaningful"


def test_every_factor_reference_equals_the_real_baseline(feature_sample: pd.DataFrame) -> None:
    checked = 0
    for _, row in feature_sample.iterrows():
        for factor in build_factors(row, max_factors=8):
            if factor.factor_id in PERSONAL_FACTORS:
                reference_col = PERSONAL_FACTORS[factor.factor_id][1]
                assert factor.reference == pytest.approx(float(row[reference_col]), abs=1e-6), (
                    f"{factor.factor_id} displayed reference {factor.reference} "
                    f"!= computed baseline {row[reference_col]}"
                )
                checked += 1
    assert checked > 20


def test_factor_windows_match_the_feature_window(feature_sample: pd.DataFrame) -> None:
    for _, row in feature_sample.iterrows():
        for factor in build_factors(row, max_factors=8):
            if factor.factor_id in PERSONAL_FACTORS:
                assert factor.window == PERSONAL_FACTORS[factor.factor_id][4]
            elif factor.factor_id in CONTEXT_FACTORS:
                assert factor.window == CONTEXT_FACTORS[factor.factor_id][3]
            elif factor.factor_id == "recovery_deficit_7d":
                assert factor.window == "last 7 days"
            elif factor.factor_id == "deployment_exposure_30d":
                assert factor.window == "last 30 days"


def test_only_adverse_directions_are_admitted(feature_sample: pd.DataFrame) -> None:
    """A factor whose underlying deviation is favourable must never appear."""
    for _, row in feature_sample.iterrows():
        for factor in build_factors(row, max_factors=8):
            if factor.factor_id in PERSONAL_FACTORS:
                deviation_col = PERSONAL_FACTORS[factor.factor_id][2]
                deviation = row[deviation_col]
                if pd.notna(deviation):
                    assert float(deviation) > 0, (
                        f"{factor.factor_id} admitted with non-adverse deviation {deviation}"
                    )
                    assert factor.direction == "higher"
            elif factor.factor_id in CONTEXT_FACTORS:
                relative_col = CONTEXT_FACTORS[factor.factor_id][2]
                relative = row[relative_col]
                if pd.notna(relative):
                    assert float(relative) > 0
            elif factor.factor_id == "recovery_deficit_7d":
                rest = float(row["avg_rest_7d"])
                assert rest < RECOVERY_HOURS_REFERENCE, "recovery factor with adequate rest"


def test_admission_threshold_matches_the_published_rule(feature_sample: pd.DataFrame) -> None:
    """Factors appear exactly when relative deviation >= the published minimum."""
    admitted = 0
    for _, row in feature_sample.iterrows():
        factors = {f.factor_id for f in build_factors(row, max_factors=8)}
        for factor_id, (*_, relative_col, _window) in PERSONAL_FACTORS.items():
            relative = row[relative_col]
            if pd.notna(relative) and float(relative) >= MIN_RELATIVE_DEVIATION:
                assert factor_id in factors, f"{factor_id} should be admitted at {relative:.3f}"
                if factor_id in factors:
                    admitted += 1
            elif pd.notna(relative):
                assert factor_id not in factors or float(relative) >= MIN_RELATIVE_DEVIATION
    assert admitted > 10


def test_structured_explanations_artifact_is_consistent_with_features() -> None:
    """The generated explanations.jsonl quotes values that exist in the data."""
    path = ROOT / "data" / "generated" / "explanations.jsonl"
    if not path.exists():
        pytest.skip("explanations artifact not available")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records, "explanations artifact is empty"
    by_key = {(r["person_id"], r["date"]): r for r in records}
    assert len(by_key) == len(records), "duplicate person/date explanations"

    features = pd.read_csv(ROOT / "data" / "generated" / "person_day_features_baseline.csv", nrows=0)
    factor_columns = {c for c in features.columns}
    for record in records:
        for factor in record["factors"]:
            assert factor["metric_column"] in factor_columns, (
                f"{factor['factor_id']} cites {factor['metric_column']} which does not exist"
            )
            assert factor["window"] and factor["comparison"] and factor["rule"]
            assert factor["weight"] >= MIN_RELATIVE_DEVIATION or factor["comparison_kind"] == "absolute"


def test_recommendation_provenance_matches_policy_rules() -> None:
    """Every recommendation's provenance chain must name a real policy rule."""
    path = ROOT / "data" / "generated" / "intervention_recommendations.csv"
    if not path.exists():
        pytest.skip("recommendations artifact not available")
    frame = pd.read_csv(path, usecols=["risk_band", "recommended_action", "policy_rule", "provenance"], nrows=5000)
    valid_rules = {
        "BAND_LOW", "BAND_HIGH", "BAND_MODERATE_RECOVERY_SIGNAL",
        "BAND_MODERATE_CONTEXT_SIGNAL", "BAND_MODERATE_DEFAULT", "COOLDOWN_CONTINUATION",
    }
    for _, row in frame.iterrows():
        assert row["policy_rule"] in valid_rules, f"unknown rule id {row['policy_rule']}"
        provenance = json.loads(row["provenance"])
        assert provenance["rule_id"] == row["policy_rule"]
        assert provenance["recommendation"] == row["recommended_action"]
        assert provenance["policy_version"]
        if row["policy_rule"] == "BAND_HIGH":
            assert row["risk_band"] == "HIGH"
        if row["policy_rule"] == "BAND_LOW":
            assert row["risk_band"] == "LOW"