from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .model_config import FORBIDDEN_INPUT_COLUMNS, WELLNESS_INPUT_PATTERNS, ModelConfig
from .model_evaluation import evaluate_binary_predictions
from .target_engineering import build_future_wellness_target

KEY_COLUMNS = {"person_id", "date"}
NON_MODEL_COLUMNS = FORBIDDEN_INPUT_COLUMNS | KEY_COLUMNS | {"target", "target_observed", "target_horizon_days", "target_definition"}


class RiskModelTrainer:
    """Train the Phase 4 predictive welfare-risk model without clinical claims."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()

    @staticmethod
    def _is_wellness_column(name: str) -> bool:
        return any(name.startswith(prefix) for prefix in WELLNESS_INPUT_PATTERNS)

    def select_features(self, frame: pd.DataFrame) -> list[str]:
        candidates: list[str] = []
        for column in frame.columns:
            if column in NON_MODEL_COLUMNS or column == "target":
                continue
            if self._is_wellness_column(column):
                continue
            if frame[column].dtype == "object" and column not in {"unit_id", "role", "deployment_type", "unit_type"}:
                continue
            if frame[column].notna().sum() == 0:
                continue
            candidates.append(column)
        if not candidates:
            raise ValueError("No eligible model features found")
        return candidates

    def split_by_date(self, labeled: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        dates = sorted(pd.to_datetime(labeled["date"], errors="raise").dt.normalize().unique())
        n_dates = len(dates)
        if n_dates < 3:
            raise ValueError("Need at least three dates for temporal train/validation/test splitting")
        train_end = max(1, int(n_dates * self.config.train_fraction))
        valid_end = max(train_end + 1, int(n_dates * (self.config.train_fraction + self.config.validation_fraction)))
        valid_end = min(valid_end, n_dates - 1)

        train_dates = set(dates[:train_end])
        valid_dates = set(dates[train_end:valid_end])
        test_dates = set(dates[valid_end:])

        if not train_dates or not valid_dates or not test_dates:
            raise ValueError("Temporal split produced an empty partition")

        train = labeled[labeled["date"].isin(train_dates)].copy()
        valid = labeled[labeled["date"].isin(valid_dates)].copy()
        test = labeled[labeled["date"].isin(test_dates)].copy()
        return train, valid, test

    def _build_pipeline(self, frame: pd.DataFrame, feature_columns: list[str]) -> Pipeline:
        categorical = [
            c for c in feature_columns
            if c in {"unit_id", "role", "deployment_type", "unit_type"}
        ]
        numeric = [c for c in feature_columns if c not in categorical]

        numeric_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=False)),
                ("scaler", StandardScaler()),
            ]
        )
        categorical_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=True)),
            ]
        )
        transformer = ColumnTransformer(
            transformers=[
                ("numeric", numeric_pipeline, numeric),
                ("categorical", categorical_pipeline, categorical),
            ],
            remainder="drop",
        )
        estimator = LogisticRegression(
            max_iter=self.config.max_iter,
            class_weight=self.config.class_weight,
            solver="liblinear",
            random_state=self.config.random_state,
        )
        return Pipeline([("preprocess", transformer), ("model", estimator)])

    def train(self, phase3_features: pd.DataFrame) -> dict[str, Any]:
        frame = phase3_features.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
        targets = build_future_wellness_target(
            frame,
            horizon_days=self.config.target_horizon_days,
            stress_threshold=self.config.target_threshold,
        )
        frame = frame.merge(targets, on=["person_id", "date"], how="left", validate="one_to_one", sort=False)
        labeled = frame[frame["target"].notna()].copy()
        labeled["target"] = labeled["target"].astype(int)
        labeled = labeled.sort_values(["date", "person_id"], kind="mergesort").reset_index(drop=True)
        if len(labeled) < self.config.min_training_samples:
            raise ValueError(f"Only {len(labeled)} labeled samples; minimum is {self.config.min_training_samples}")

        train, valid, test = self.split_by_date(labeled)
        features = self.select_features(labeled)
        model = self._build_pipeline(labeled, features)
        X_train, y_train = train[features], train["target"]
        X_valid, y_valid = valid[features], valid["target"]
        X_test, y_test = test[features], test["target"]
        model.fit(X_train, y_train)

        valid_prob = model.predict_proba(X_valid)[:, 1]
        test_prob = model.predict_proba(X_test)[:, 1]
        validation_metrics = evaluate_binary_predictions(y_valid, valid_prob)
        test_metrics = evaluate_binary_predictions(y_test, test_prob)

        split_summary = {
            "train": self._split_summary(train),
            "validation": self._split_summary(valid),
            "test": self._split_summary(test),
        }
        metadata = {
            "phase": 4,
            "model_type": "logistic_regression",
            "target_name": self.config.target_name,
            "target_horizon_days": self.config.target_horizon_days,
            "target_threshold": self.config.target_threshold,
            "target_definition": f"Any observed perceived_stress_latest >= {self.config.target_threshold} during T+1..T+{self.config.target_horizon_days}",
            "target_source": "synthetic voluntary wellness self-report",
            "clinical_interpretation": "none; this is an operational/welfare modeling signal",
            "feature_count": len(features),
            "feature_columns": features,
            "wellness_features_excluded": True,
            "excluded_rows": int(len(frame) - len(labeled)),
            "usable_samples": int(len(labeled)),
            "temporal_splits": split_summary,
            "validation_metrics": validation_metrics,
            "test_metrics": test_metrics,
            "config": asdict(self.config),
        }

        return {
            "model": model,
            "metadata": metadata,
            "labeled": labeled,
            "features": features,
            "validation": (valid, valid_prob),
            "test": (test, test_prob),
        }

    @staticmethod
    def _split_summary(frame: pd.DataFrame) -> dict[str, Any]:
        return {
            "rows": int(len(frame)),
            "date_start": frame["date"].min().date().isoformat(),
            "date_end": frame["date"].max().date().isoformat(),
            "positive_count": int(frame["target"].sum()),
            "negative_count": int((frame["target"] == 0).sum()),
            "positive_rate": float(frame["target"].mean()),
        }

    @staticmethod
    def predict(model: Pipeline, phase3_features: pd.DataFrame, feature_columns: list[str], risk_thresholds=(0.33, 0.66)) -> pd.DataFrame:
        features = phase3_features.copy()
        probabilities = model.predict_proba(features[feature_columns])[:, 1]
        low, high = risk_thresholds
        levels = np.where(probabilities < low, "LOW", np.where(probabilities < high, "MODERATE", "ELEVATED"))
        return pd.DataFrame(
            {
                "person_id": features["person_id"].astype(str).to_numpy(),
                "date": pd.to_datetime(features["date"], errors="raise").dt.strftime("%Y-%m-%d").to_numpy(),
                "welfare_risk_probability": probabilities.astype(float),
                "risk_level": levels,
            }
        )

    @staticmethod
    def save_artifacts(result: dict[str, Any], model_path: str | Path, metadata_path: str | Path) -> None:
        model_path = Path(model_path)
        metadata_path = Path(metadata_path)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(result["model"], model_path)
        metadata_path.write_text(json.dumps(result["metadata"], indent=2, sort_keys=True), encoding="utf-8")
