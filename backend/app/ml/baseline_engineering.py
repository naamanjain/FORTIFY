from __future__ import annotations

from dataclasses import asdict
import numpy as np
import pandas as pd

from .baseline_config import BaselineConfig

KEY_COLUMNS = ("person_id", "date")
FORBIDDEN_COLUMNS = {
    "stress_label",
    "stress_score",
    "mental_health_label",
    "depression_label",
    "anxiety_label",
    "risk_score",
    "risk_band",
}


class BaselineEngineer:
    """Build Phase 3 contextual baseline/reference features.

    Temporal semantics are deliberately explicit:
    * Personal historical statistics are strictly prior-day (< T).
    * Cohort and operational baselines are same-day contextual references at T,
      excluding the current person's value. Future dates are never consulted.
    * Small cohorts remain missing instead of being converted into pseudo-
      baselines from repeated observations of the same people.
    * No Phase 4 prediction/risk logic is performed.
    """

    def __init__(self, config: BaselineConfig | None = None) -> None:
        self.config = config or BaselineConfig()

    def _validate_input(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in KEY_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        if df.duplicated(list(KEY_COLUMNS)).any():
            raise ValueError("Input contains duplicate person/date rows")
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
        forbidden = sorted(FORBIDDEN_COLUMNS.intersection(out.columns))
        if forbidden:
            raise ValueError(f"Forbidden prediction/risk columns present: {forbidden}")
        required_context = {"unit_type", "role", "deployment_type"}
        missing_context = sorted(required_context.difference(out.columns))
        if missing_context:
            raise ValueError(f"Missing context columns: {missing_context}")
        for metric in self.config.feature_metrics:
            if metric not in out.columns:
                raise ValueError(f"Required Phase 2 feature missing: {metric}")
            out[metric] = pd.to_numeric(out[metric], errors="coerce")
        return out.sort_values(["date", "person_id"], kind="mergesort").reset_index(drop=True)

    @staticmethod
    def _safe_relative(values: pd.Series, baseline: pd.Series, eps: float) -> pd.Series:
        denom_ok = baseline.notna() & baseline.abs().gt(eps)
        out = pd.Series(np.nan, index=values.index, dtype="float64")
        out.loc[denom_ok] = (
            (values.loc[denom_ok] - baseline.loc[denom_ok])
            / baseline.loc[denom_ok].abs()
        )
        return out

    @staticmethod
    def _prior_expanding_stats(
        frame: pd.DataFrame,
        metric: str,
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        shifted = frame.groupby("person_id", sort=False)[metric].shift(1)
        grouped = shifted.groupby(frame["person_id"], sort=False)
        mean = grouped.expanding().mean().reset_index(level=0, drop=True).reindex(frame.index)
        median = grouped.expanding().median().reset_index(level=0, drop=True).reindex(frame.index)
        std = grouped.expanding().std(ddof=1).reset_index(level=0, drop=True).reindex(frame.index)
        count = shifted.notna().groupby(frame["person_id"], sort=False).cumsum().astype(float)
        return mean, median, std, count

    def _personal_columns(self, frame: pd.DataFrame) -> dict[str, pd.Series]:
        additions: dict[str, pd.Series] = {}
        for metric in self.config.feature_metrics:
            mean, median, std, count = self._prior_expanding_stats(frame, metric)
            sufficient = count.ge(self.config.minimum_personal_history_days)
            mean = mean.where(sufficient)
            median = median.where(sufficient)
            std = std.where(sufficient)
            deviation = frame[metric] - mean
            relative = self._safe_relative(frame[metric], mean, self.config.near_zero_denominator)
            additions.update(
                {
                    f"{metric}_personal_history_mean": mean,
                    f"{metric}_personal_history_median": median,
                    f"{metric}_personal_history_std": std,
                    f"{metric}_personal_history_count": count,
                    f"{metric}_personal_history_sufficient": sufficient,
                    f"{metric}_personal_deviation": deviation,
                    f"{metric}_personal_relative_deviation": relative,
                }
            )
        return additions

    def _context_columns(
        self,
        frame: pd.DataFrame,
        group_columns: list[str],
        prefix: str,
        minimum_size: int,
    ) -> dict[str, pd.Series]:
        additions: dict[str, pd.Series] = {}
        group = frame.groupby(group_columns + ["date"], sort=False)
        person_count = group["person_id"].transform("nunique").astype(float)

        for metric in self.config.feature_metrics:
            values = frame[metric]
            sums = group[metric].transform("sum")
            counts = group[metric].transform("count")
            self_present = values.notna().astype(int)
            effective_size = person_count - self_present
            mean = (sums - values.fillna(0)).div(counts.sub(self_present).replace(0, np.nan))
            sufficient = effective_size.ge(minimum_size)
            mean = mean.where(sufficient)
            deviation = values - mean
            relative = self._safe_relative(values, mean, self.config.near_zero_denominator)
            additions.update(
                {
                    f"{metric}_{prefix}_baseline_mean": mean,
                    f"{metric}_{prefix}_cohort_size": effective_size.where(sufficient, effective_size),
                    f"{metric}_{prefix}_sufficient": sufficient,
                    f"{metric}_{prefix}_deviation": deviation,
                    f"{metric}_{prefix}_relative_deviation": relative,
                }
            )
        return additions

    def build_features(self, features: pd.DataFrame) -> pd.DataFrame:
        """Extend a Phase 2 person-day feature table with Phase 3 references."""
        result = self._validate_input(features)
        result = result.sort_values(["person_id", "date"], kind="mergesort").reset_index(drop=True)

        additions = self._personal_columns(result)
        additions.update(
            self._context_columns(
                result,
                ["role", "deployment_type"],
                "cohort",
                self.config.minimum_cohort_size,
            )
        )
        additions.update(
            self._context_columns(
                result,
                ["unit_type"],
                "operational",
                self.config.minimum_operational_size,
            )
        )

        # Operational context is descriptive only. These aggregates remain non-predictive.
        operational_group = result.groupby(["unit_type", "date"], sort=False)
        additions["operational_unit_type_person_count"] = operational_group["person_id"].transform("nunique").astype(float)
        additions["operational_unit_workload_reference_7d"] = operational_group["duty_hours_7d"].transform("median")
        additions["operational_unit_duty_density_reference_30d"] = operational_group["duty_density_30d"].transform("median")
        additions["operational_period_person_days"] = result.groupby("date", sort=False)["person_id"].transform("nunique").astype(float)

        # Small, explicit provenance/semantics fields. They carry no predictive target.
        additions["cohort_definition"] = pd.Series("role|deployment_type", index=result.index, dtype="string")
        additions["operational_context_definition"] = pd.Series("unit_type|date", index=result.index, dtype="string")
        additions["personal_baseline_semantics"] = pd.Series("strictly_prior_days", index=result.index, dtype="string")
        additions["cohort_baseline_semantics"] = pd.Series("current_day_excluding_self", index=result.index, dtype="string")
        additions["operational_baseline_semantics"] = pd.Series("current_day_unit_type_excluding_self", index=result.index, dtype="string")

        added = pd.DataFrame(additions, index=result.index)
        result = pd.concat([result, added], axis=1)
        result = result.sort_values(["date", "person_id"], kind="mergesort").reset_index(drop=True)

        forbidden = sorted(FORBIDDEN_COLUMNS.intersection(result.columns))
        if forbidden:
            raise AssertionError(f"Forbidden columns generated: {forbidden}")
        return result

    def config_dict(self) -> dict:
        return asdict(self.config)
