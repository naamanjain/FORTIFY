from __future__ import annotations

import numpy as np
import pandas as pd

from .model_config import DEFAULT_TARGET_HORIZON_DAYS, DEFAULT_TARGET_THRESHOLD

REQUIRED_COLUMNS = {"person_id", "date", "perceived_stress_latest"}


def build_future_wellness_target(
    features: pd.DataFrame,
    *,
    horizon_days: int = DEFAULT_TARGET_HORIZON_DAYS,
    stress_threshold: int = DEFAULT_TARGET_THRESHOLD,
) -> pd.DataFrame:
    """Attach a future-observation target without using it as an input feature.

    For prediction date T, the target is 1 when the same person's observed
    voluntary perceived-stress score reaches ``stress_threshold`` on any day in
    T+1..T+horizon_days. Rows without an observed future wellness value remain
    unlabeled (NaN). This is an observed synthetic self-report outcome, not a
    clinical diagnosis or clinical ground truth.
    """
    missing = sorted(REQUIRED_COLUMNS.difference(features.columns))
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    if not 1 <= stress_threshold <= 5:
        raise ValueError("stress_threshold must be between 1 and 5")

    frame = features[["person_id", "date", "perceived_stress_latest"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame["perceived_stress_latest"] = pd.to_numeric(frame["perceived_stress_latest"], errors="coerce")
    frame = frame.sort_values(["person_id", "date"], kind="mergesort").reset_index(drop=True)

    observed = frame["perceived_stress_latest"].notna().astype(int)
    high = frame["perceived_stress_latest"].ge(stress_threshold).astype(float)

    # Aggregate future observations by person/date first, then construct an
    # explicit person-day lookup. No event at T itself contributes to the target.
    future_by_day = frame.loc[observed.eq(1), ["person_id", "date"]].copy()
    future_by_day["high"] = high.loc[observed.eq(1)].astype(float).to_numpy()
    daily = (
        future_by_day.groupby(["person_id", "date"], as_index=False, sort=False)["high"]
        .max()
    )
    daily["observed"] = 1.0

    base = frame[["person_id", "date"]].copy()
    base["target_date"] = base["date"] + pd.to_timedelta(horizon_days, unit="D")

    # A backward-looking range join is avoided entirely: for each target date T,
    # inspect the person's next horizon days via shifted aligned person-day rows.
    # This is leakage-safe because the shifts only read future observations into
    # the target column, never into model features.
    person_groups = []
    daily_indexed = daily.set_index(["person_id", "date"])
    for offset in range(1, horizon_days + 1):
        shifted = frame[["person_id", "date", "perceived_stress_latest"]].copy()
        shifted["date"] = shifted["date"] - pd.to_timedelta(offset, unit="D")
        shifted = shifted.rename(columns={"perceived_stress_latest": f"_future_{offset}"})
        person_groups.append(shifted[["person_id", "date", f"_future_{offset}"]])

    target_frame = frame[["person_id", "date"]].copy()
    for shifted in person_groups:
        target_frame = target_frame.merge(shifted, on=["person_id", "date"], how="left", sort=False)

    future_cols = [f"_future_{offset}" for offset in range(1, horizon_days + 1)]
    future_matrix = target_frame[future_cols]
    any_observed = future_matrix.notna().any(axis=1)
    high_future = future_matrix.ge(stress_threshold).any(axis=1)

    target_frame["target_observed"] = any_observed.astype(bool)
    target_frame["target"] = np.where(any_observed, high_future.astype(int), np.nan)
    target_frame["target_horizon_days"] = horizon_days
    target_frame["target_definition"] = (
        f"Any observed perceived_stress_latest >= {stress_threshold} during T+1..T+{horizon_days}"
    )

    return target_frame[["person_id", "date", "target", "target_observed", "target_horizon_days", "target_definition"]]
