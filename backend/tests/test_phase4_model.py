from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.ml.model_config import ModelConfig
from backend.app.ml.model_training import RiskModelTrainer
from backend.app.ml.target_engineering import build_future_wellness_target

FORBIDDEN = {
    "stress_label",
    "stress_score",
    "mental_health_label",
    "depression_label",
    "anxiety_label",
    "risk_score",
    "risk_band",
}


def make_fixture() -> pd.DataFrame:
    rows = []
    for person in ["P-0001", "P-0002", "P-0003", "P-0004"]:
        for day in range(35):
            date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
            # Operational-only explanatory variables.
            high_load = 1 if 15 <= day <= 24 else 0
            wellness = np.nan
            if day in {16, 19, 22, 25, 28, 31}:
                wellness = 4 if person in {"P-0001", "P-0002"} else 2
            rows.append(
                {
                    "person_id": person,
                    "date": date,
                    "unit_id": "U-001" if person in {"P-0001", "P-0002"} else "U-002",
                    "role": "OPERATIONS",
                    "deployment_type": "FIELD",
                    "unit_type": "FIELD",
                    "service_years": 6,
                    "duty_hours_7d": float(40 + 10 * high_load + day % 3),
                    "duty_hours_30d": float(160 + 30 * high_load),
                    "duty_density_30d": float(0.7 + 0.1 * high_load),
                    "avg_rest_7d": float(8 - 1.5 * high_load),
                    "perceived_stress_latest": wellness,
                    "mood_latest": np.nan if wellness is np.nan else max(1, 6 - wellness),
                }
            )
    return pd.DataFrame(rows)


def test_target_construction_future_only() -> None:
    df = make_fixture()
    targets = build_future_wellness_target(df, horizon_days=7, stress_threshold=4)
    p1 = targets[targets.person_id == "P-0001"].set_index("date")
    # Jan 10 + next 7 days includes Jan 17 high report.
    assert p1.loc[pd.Timestamp("2026-01-10"), "target"] == 1
    # Jan 13 looks through Jan 20 and includes the Jan 17 report.
    assert p1.loc[pd.Timestamp("2026-01-13"), "target"] == 1
    # Jan 8 looks only through Jan 15, before the first observed report.
    assert pd.isna(p1.loc[pd.Timestamp("2026-01-08"), "target"])


def test_temporal_split_is_chronological() -> None:
    trainer = RiskModelTrainer(ModelConfig(min_training_samples=2))
    df = make_fixture()
    targets = build_future_wellness_target(df)
    labeled = df.merge(targets, on=["person_id", "date"], how="left")
    labeled = labeled[labeled.target.notna()].copy()
    labeled["target"] = labeled["target"].astype(int)
    train, valid, test = trainer.split_by_date(labeled)
    assert train.date.max() < valid.date.min()
    assert valid.date.max() < test.date.min()


def test_future_event_does_not_change_earlier_target_or_feature_inputs() -> None:
    df = make_fixture()
    base_targets = build_future_wellness_target(df)
    changed = df.copy()
    changed.loc[(changed.person_id == "P-0001") & (changed.date == pd.Timestamp("2026-02-10")), "perceived_stress_latest"] = 5
    changed_targets = build_future_wellness_target(changed)
    # A wellness event after T+7 must not affect T's future target.
    t = pd.Timestamp("2026-01-25")
    assert base_targets[(base_targets.person_id == "P-0001") & (base_targets.date == t)].target.iloc[0] == changed_targets[(changed_targets.person_id == "P-0001") & (changed_targets.date == t)].target.iloc[0]


def test_model_training_and_prediction_schema() -> None:
    df = make_fixture()
    trainer = RiskModelTrainer(ModelConfig(min_training_samples=5, train_fraction=0.5, validation_fraction=0.25, test_fraction=0.25))
    result = trainer.train(df)
    predictions = trainer.predict(result["model"], df, result["features"])
    assert len(predictions) == len(df)
    assert set(["person_id", "date", "welfare_risk_probability", "risk_level"]).issubset(predictions.columns)
    assert predictions.welfare_risk_probability.between(0, 1).all()
    assert predictions.risk_level.isin({"LOW", "MODERATE", "ELEVATED"}).all()
    assert not FORBIDDEN.intersection(predictions.columns)
    assert result["metadata"]["feature_count"] > 0


def test_target_bookkeeping_is_not_a_model_feature() -> None:
    trainer = RiskModelTrainer(ModelConfig(min_training_samples=2))
    frame = make_fixture()
    targets = build_future_wellness_target(frame)
    merged = frame.merge(targets, on=["person_id", "date"], how="left")
    selected = trainer.select_features(merged)
    assert "target" not in selected
    assert "target_observed" not in selected
    assert "target_horizon_days" not in selected
    assert "target_definition" not in selected


def test_wellness_features_are_excluded() -> None:
    trainer = RiskModelTrainer(ModelConfig(min_training_samples=2))
    features = trainer.select_features(make_fixture())
    assert all(not any(c.startswith(prefix) for prefix in ("mood_", "perceived_stress_")) for c in features)


def test_deterministic_training() -> None:
    df = make_fixture()
    config = ModelConfig(min_training_samples=5, train_fraction=0.5, validation_fraction=0.25, test_fraction=0.25)
    a = RiskModelTrainer(config).train(df)
    b = RiskModelTrainer(config).train(df)
    pa = RiskModelTrainer.predict(a["model"], df, a["features"])
    pb = RiskModelTrainer.predict(b["model"], df, b["features"])
    pd.testing.assert_frame_equal(pa, pb)


def test_cli_train_and_validate(tmp_path: Path) -> None:
    df = make_fixture()
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "artifacts"
    pred = tmp_path / "predictions.csv"
    input_dir.mkdir()
    input_path = input_dir / "person_day_features_baseline.csv"
    df.to_csv(input_path, index=False)

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/train_model.py", "--input", str(input_path), "--output-dir", str(output_dir), "--prediction-output", str(pred), "--target-horizon-days", "7", "--min-training-samples", "20"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    result2 = subprocess.run(
        [sys.executable, "scripts/validate_model.py", "--metadata", str(output_dir / "model_metadata.json"), "--evaluation", str(output_dir / "evaluation_report.json"), "--predictions", str(pred)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result2.returncode == 0, result2.stdout + result2.stderr
