"""Phase 2: deterministic, time-aware feature engineering for FORTIFY."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .feature_config import FeatureConfig


REQUIRED_DATASETS = (
    "personnel.csv",
    "units.csv",
    "duty_events.csv",
    "recovery_events.csv",
    "leave_events.csv",
    "deployment_events.csv",
    "training_events.csv",
    "incident_events.csv",
    "wellness_events.csv",
)

FORBIDDEN_FEATURE_NAMES = {
    "stress_label",
    "stress_score",
    "mental_health_label",
    "depression_label",
    "anxiety_label",
    "risk_score",
    "risk_band",
}

CONTEXT_COLUMNS = ["unit_id", "role", "deployment_type", "service_years", "unit_type"]


class FeatureEngineer:
    """Build one deterministic row per person and simulation day.

    All event-derived calculations are explicitly filtered to events with date <= T.
    Rolling windows are closed on the current date: a 7-day feature for T uses T-6..T.
    """

    def __init__(self, input_dir: str | Path, config: FeatureConfig | None = None):
        self.input_dir = Path(input_dir)
        self.config = config or FeatureConfig()
        self.data: dict[str, pd.DataFrame] = {}
        self._load()

    def _load(self) -> None:
        missing = [name for name in REQUIRED_DATASETS if not (self.input_dir / name).exists()]
        if missing:
            raise FileNotFoundError(
                "Phase 1 dataset files missing: " + ", ".join(missing)
            )
        for name in REQUIRED_DATASETS:
            self.data[name[:-4]] = pd.read_csv(self.input_dir / name)
        self._prepare()
        self.validate_inputs()

    def _prepare(self) -> None:
        for key in (
            "personnel",
            "units",
            "duty_events",
            "recovery_events",
            "leave_events",
            "deployment_events",
            "training_events",
            "incident_events",
            "wellness_events",
        ):
            if key not in self.data:
                continue
        p = self.data["personnel"].copy()
        p["joining_date"] = pd.to_datetime(p["joining_date"], errors="raise")
        p["current_posting_start"] = pd.to_datetime(p["current_posting_start"], errors="raise")
        self.data["personnel"] = p

        date_columns = {
            "duty_events": ["timestamp", "date"],
            "recovery_events": ["date"],
            "leave_events": ["start_date", "end_date"],
            "deployment_events": ["start_date", "end_date"],
            "training_events": ["date"],
            "incident_events": ["date"],
            "wellness_events": ["date"],
        }
        for table, cols in date_columns.items():
            df = self.data[table].copy()
            for col in cols:
                df[col] = pd.to_datetime(df[col], errors="raise")
            self.data[table] = df

    def validate_inputs(self) -> None:
        p = self.data["personnel"]
        units = self.data["units"][['unit_id', 'unit_type']].drop_duplicates('unit_id')
        p_units = p.merge(units, on='unit_id', how='left', validate='many_to_one')
        if p_units["unit_type"].isna().any():
            raise ValueError("personnel.csv contains unit_id values missing from units.csv")
        self.data["personnel"] = p_units
        if p["person_id"].duplicated().any():
            raise ValueError("Duplicate person_id in personnel.csv")
        if p.empty:
            raise ValueError("personnel.csv is empty")
        if "unit_type" not in self.data["units"].columns:
            raise ValueError("units.csv must contain unit_type")
        person_ids = set(p["person_id"])
        for table in (
            "duty_events",
            "recovery_events",
            "leave_events",
            "deployment_events",
            "training_events",
            "incident_events",
            "wellness_events",
        ):
            unknown = set(self.data[table]["person_id"]) - person_ids
            if unknown:
                raise ValueError(f"{table}.csv has orphan person_id values")
        d = self.data["deployment_events"]
        if (d["end_date"] < d["start_date"]).any():
            raise ValueError("Deployment end_date precedes start_date")
        l = self.data["leave_events"]
        if (l["end_date"] < l["start_date"]).any():
            raise ValueError("Leave end_date precedes start_date")

    @staticmethod
    def _rolling_sum(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window, min_periods=1).sum()

    @staticmethod
    def _relative_change(current: pd.Series, previous: pd.Series) -> pd.Series:
        prev = previous.astype(float)
        cur = current.astype(float)
        return np.where(prev.abs() > 1e-12, (cur - prev) / prev.abs(), np.nan)

    def _person_days(self, start_date: pd.Timestamp | None = None, end_date: pd.Timestamp | None = None) -> pd.DataFrame:
        p = self.data["personnel"]
        all_dates = []
        duty_dates = pd.to_datetime(self.data["duty_events"]["date"])
        event_dates = [duty_dates]
        for key, start_col, end_col in [
            ("leave_events", "start_date", "end_date"),
            ("deployment_events", "start_date", "end_date"),
        ]:
            df = self.data[key]
            event_dates.extend([df[start_col], df[end_col]])
        for key in ("recovery_events", "training_events", "incident_events", "wellness_events"):
            event_dates.append(self.data[key]["date"])
        observed_min = min((s.min() for s in event_dates if not s.empty), default=p["current_posting_start"].min())
        observed_max = max((s.max() for s in event_dates if not s.empty), default=observed_min)
        start = pd.Timestamp(start_date) if start_date is not None else observed_min
        end = pd.Timestamp(end_date) if end_date is not None else observed_max
        if end < start:
            raise ValueError("end_date precedes start_date")
        dates = pd.date_range(start, end, freq="D")
        base = p[["person_id", *CONTEXT_COLUMNS]].merge(pd.DataFrame({"date": dates}), how="cross")
        return base.sort_values(["person_id", "date"], kind="stable").reset_index(drop=True)

    def _aggregate_daily(self, table: str, date_col: str, value_col: str | None = None, agg: str = "sum") -> pd.DataFrame:
        df = self.data[table]
        cols = ["person_id", date_col]
        work = df[cols + ([value_col] if value_col else [])].copy()
        if agg == "sum":
            result = work.groupby(["person_id", date_col], as_index=False)[value_col].sum()
        elif agg == "count":
            result = work.groupby(["person_id", date_col], as_index=False).size().rename(columns={"size": value_col or "value"})
        else:
            result = work.groupby(["person_id", date_col], as_index=False)[value_col].agg(agg)
        return result

    def build_features(
        self,
        start_date: pd.Timestamp | None = None,
        end_date: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        base = self._person_days(start_date, end_date)
        base["days_observed"] = base.groupby("person_id").cumcount() + 1

        duty = self.data["duty_events"].copy()
        duty["date"] = pd.to_datetime(duty["date"]).dt.normalize()
        duty["high_intensity"] = duty["intensity_level"] >= self.config.high_intensity_threshold
        duty["emergency"] = duty["duty_type"].isin(self.config.emergency_duty_types)
        duty_daily = duty.groupby(["person_id", "date"], as_index=False).agg(
            duty_hours=("duration_hours", "sum"),
            night_shifts=("night_shift", "sum"),
            high_intensity_duties=("high_intensity", "sum"),
            emergency_duties=("emergency", "sum"),
            duty_event_count=("duty_event_id", "count"),
        )
        duty_daily["duty_day"] = 1

        training = self.data["training_events"].groupby(["person_id", "date"], as_index=False)["duration_hours"].sum().rename(columns={"duration_hours": "training_hours"})
        incidents = self.data["incident_events"].copy()
        incidents["high_intensity_incident"] = incidents["intensity_level"] >= self.config.high_intensity_threshold
        incident_daily = incidents.groupby(["person_id", "date"], as_index=False).agg(
            incident_count=("incident_event_id", "count"),
            high_intensity_incident_count=("high_intensity_incident", "sum"),
            incident_recovery_requirement=("recovery_requirement", "sum"),
        )
        recovery = self.data["recovery_events"].groupby(["person_id", "date"], as_index=False)["rest_duration_hours"].agg(
            avg_rest="mean", min_rest="min", rest_total="sum", rest_count="count"
        )

        x = base.merge(duty_daily, on=["person_id", "date"], how="left")
        x = x.merge(training, on=["person_id", "date"], how="left")
        x = x.merge(incident_daily, on=["person_id", "date"], how="left")
        x = x.merge(recovery, on=["person_id", "date"], how="left")
        numeric_zero = [
            "duty_hours", "night_shifts", "high_intensity_duties", "emergency_duties",
            "duty_event_count", "duty_day", "training_hours", "incident_count",
            "high_intensity_incident_count", "incident_recovery_requirement",
        ]
        x[numeric_zero] = x[numeric_zero].fillna(0)
        x["duty_hours_1d"] = x["duty_hours"]
        x["avg_rest"] = x["avg_rest"].astype(float)
        x["min_rest"] = x["min_rest"].astype(float)

        def grouped_roll(frame: pd.DataFrame, column: str, days: int, out: str, agg: str = "sum") -> None:
            grouped = frame.groupby("person_id")[column]
            if agg == "sum":
                vals = grouped.rolling(days, min_periods=1).sum().reset_index(level=0, drop=True)
            elif agg == "mean":
                vals = grouped.rolling(days, min_periods=1).mean().reset_index(level=0, drop=True)
            elif agg == "min":
                vals = grouped.rolling(days, min_periods=1).min().reset_index(level=0, drop=True)
            else:
                vals = grouped.rolling(days, min_periods=1).std().reset_index(level=0, drop=True)
            tmp = pd.DataFrame({"person_id": frame["person_id"].values, "date": frame["date"].values, out: vals.values})
            x[out] = tmp[out].to_numpy()

        # Daily rows are complete for every person/date, making these rolling operations leakage-explicit.
        for days in (7, 30, 90):
            grouped_roll(x, "duty_hours", days, f"duty_hours_{days}d")
            grouped_roll(x, "duty_day", days, f"duty_days_{days}d")
            grouped_roll(x, "night_shifts", days, f"night_shifts_{days}d")
        for days in (7, 30):
            grouped_roll(x, "high_intensity_duties", days, f"high_intensity_duties_{days}d")
            grouped_roll(x, "emergency_duties", days, f"emergency_duties_{days}d")
            grouped_roll(x, "training_hours", days, f"training_hours_{days}d")
        for days in (7, 30, 90):
            grouped_roll(x, "incident_count", days, f"incident_count_{days}d")
        grouped_roll(x, "high_intensity_incident_count", 30, "high_intensity_incident_count_30d")
        grouped_roll(x, "incident_recovery_requirement", 30, "incident_recovery_requirement_30d")
        x["incident_density_30d"] = x["incident_count_30d"] / 30.0
        for days in (7, 30):
            grouped_roll(x, "avg_rest", days, f"avg_rest_{days}d", "mean")
            grouped_roll(x, "min_rest", days, f"min_rest_{days}d", "min")
            short = x["rest_count"].where(x["rest_count"].notna(), 0)
            x[f"short_rest_count_{days}d"] = (
                x.assign(short_rest=((x["min_rest"] < self.config.short_rest_threshold_hours) & x["rest_count"].gt(0)).astype(int))
                .groupby("person_id")["short_rest"]
                .rolling(days, min_periods=1).sum().reset_index(level=0, drop=True).to_numpy()
            )
            target = self.config.recovery_target_hours
            x[f"recovery_deficit_{days}d"] = (
                x["avg_rest"].fillna(target).rsub(target).clip(lower=0)
            )
            x[f"recovery_deficit_{days}d"] = x.groupby("person_id")[f"recovery_deficit_{days}d"].rolling(days, min_periods=1).sum().reset_index(level=0, drop=True).to_numpy()
        grouped_roll(x, "avg_rest", 30, "recovery_variability_30d", "std")

        x["duty_density_7d"] = x["duty_days_7d"] / 7.0
        x["duty_density_30d"] = x["duty_days_30d"] / 30.0
        x["night_shift_ratio_30d"] = np.divide(x["night_shifts_30d"], x["duty_days_30d"], out=np.zeros(len(x)), where=x["duty_days_30d"] > 0)

        # Gap features use the last duty date within the current rolling window.
        duty_day = x["duty_day"].astype(int)
        prev_duty_date = x["date"].where(duty_day.eq(1)).groupby(x["person_id"]).ffill().groupby(x["person_id"]).shift(1)
        gaps = (x["date"] - prev_duty_date).dt.days.astype(float)
        gap_7 = gaps.where(gaps.le(6))
        gap_30 = gaps.where(gaps.le(29))
        x["duty_gap_mean_7d"] = gap_7.groupby(x["person_id"]).transform(lambda s: s.rolling(7, min_periods=1).mean())
        x["duty_gap_mean_30d"] = gap_30.groupby(x["person_id"]).transform(lambda s: s.rolling(30, min_periods=1).mean())
        x["consecutive_duty_days"] = duty_day.groupby(x["person_id"]).transform(lambda s: s.groupby((s == 0).cumsum()).cumsum())
        x["longest_duty_streak_30d"] = x.groupby("person_id")["consecutive_duty_days"].transform(lambda s: s.rolling(30, min_periods=1).max())

        # Leave state/recency.
        x = self._add_leave_features(x)
        x = self._add_deployment_features(x)
        x = self._add_change_features(x)
        x = self._add_wellness_features(x)
        x = self._add_personal_history(x)
        x["leave_data_available"] = True
        x["deployment_data_available"] = True
        x["duty_data_days_30d"] = x.groupby("person_id")["duty_day"].transform(lambda s: s.rolling(30, min_periods=1).sum())
        x["feature_completeness_ratio"] = self._completeness(x)

        helper_columns = [
            "duty_hours", "night_shifts", "high_intensity_duties", "emergency_duties",
            "duty_event_count", "duty_day", "training_hours", "incident_count",
            "high_intensity_incident_count", "incident_recovery_requirement", "avg_rest",
            "min_rest", "rest_total", "rest_count",
        ]
        x.drop(columns=helper_columns, inplace=True)

        x = x.sort_values(["person_id", "date"], kind="stable").reset_index(drop=True)
        self._validate_output(x)
        return x

    def _add_leave_features(self, x: pd.DataFrame) -> pd.DataFrame:
        leaves = self.data["leave_events"]
        days_since, leave30, leave90, count90, gap90 = [], [], [], [], []
        for person_id, date in zip(x["person_id"], x["date"]):
            l = leaves[(leaves.person_id == person_id) & (leaves.start_date <= date)]
            completed = l[l.end_date <= date]
            days_since.append((date - completed.end_date.max()).days if not completed.empty else np.nan)
            def overlap_days(window_days: int) -> int:
                window_start = date - pd.Timedelta(days=window_days - 1)
                total = 0
                for _, row in l.iterrows():
                    start = max(row["start_date"], window_start)
                    end = min(row["end_date"], date)
                    if start <= end:
                        total += (end - start).days + 1
                return total
            leave30.append(overlap_days(30))
            leave90.append(overlap_days(90))
            count90.append((l["start_date"] >= date - pd.Timedelta(days=89)).sum())
            if len(completed) >= 2:
                ends = completed.end_date.sort_values()
                gap90.append((ends.iloc[-1] - ends.iloc[-2]).days)
            else:
                gap90.append(np.nan)
        x["days_since_last_leave"] = days_since
        x["leave_days_30d"] = leave30
        x["leave_days_90d"] = leave90
        x["leave_count_90d"] = count90
        x["leave_gap_90d"] = gap90
        # Phase 1 only exposes a status string; no reliable delayed semantics are assumed.
        x["pending_or_delayed_leave_indicator"] = pd.NA
        return x

    def _add_deployment_features(self, x: pd.DataFrame) -> pd.DataFrame:
        dep = self.data["deployment_events"]
        rows = []
        for person_id, date in zip(x["person_id"], x["date"]):
            d = dep[(dep.person_id == person_id) & (dep.start_date <= date)]
            active = d[d.end_date >= date]
            current_days = 0
            current_intensity = 0
            since_start = np.nan
            since_end = np.nan
            if not active.empty:
                current = active.sort_values(["start_date", "deployment_event_id"]).iloc[-1]
                current_days = (date - current.start_date).days + 1
                current_intensity = current.intensity_level
                since_start = current_days
            else:
                ended = d[d.end_date < date]
                if not ended.empty:
                    since_end = (date - ended.end_date.max()).days
            rows.append((current_days, current_intensity, since_start, since_end))
        x["current_deployment_days"], x["current_deployment_intensity"], x["days_since_deployment_start"], x["days_since_deployment_end"] = zip(*rows)
        for days in (30, 90):
            x[f"deployment_days_{days}d"] = x.groupby("person_id")["current_deployment_days"].transform(lambda s: (s > 0).rolling(days, min_periods=1).sum())
        x["deployment_count_180d"] = [
            int(
                ((dep["person_id"] == person_id)
                 & (dep["start_date"] <= date)
                 & (dep["start_date"] >= date - pd.Timedelta(days=179))).sum()
            )
            for person_id, date in zip(x["person_id"], x["date"])
        ]
        return x

    def _add_change_features(self, x: pd.DataFrame) -> pd.DataFrame:
        g = x.groupby("person_id", group_keys=False)
        metrics = {
            "duty_hours_7d": "duty_hours_7d_vs_previous_7d",
            "duty_hours_30d": "duty_hours_30d_vs_previous_30d",
            "night_shifts_30d": "night_shifts_30d_vs_previous_30d",
            "training_hours_30d": "training_hours_30d_vs_previous_30d",
            "incident_count_30d": "incident_count_30d_vs_previous_30d",
            "avg_rest_7d": "rest_7d_vs_previous_7d",
        }
        # Previous non-overlapping window = value at T-window minus value before that window.
        windows = {"duty_hours_7d": 7, "duty_hours_30d": 30, "night_shifts_30d": 30, "training_hours_30d": 30, "incident_count_30d": 30, "avg_rest_7d": 7}
        for col, prefix in metrics.items():
            w = windows[col]
            current = x[col]
            prev = current.groupby(x["person_id"]).shift(w)
            diff = current - prev
            x[prefix + "_abs"] = diff
            x[prefix + "_relative"] = x[col].groupby(x["person_id"]).transform(lambda s: self._relative_change(s, s.shift(w)))
        return x

    def _add_wellness_features(self, x: pd.DataFrame) -> pd.DataFrame:
        w = self.data["wellness_events"].copy()
        score_cols = ["mood_score", "energy_score", "sleep_quality", "perceived_stress", "workload_manageability"]
        for c in score_cols:
            if c not in w.columns:
                w[c] = np.nan
        w["support_request"] = w["support_request"].astype("boolean")
        x = x.merge(w[["person_id", "date", *score_cols, "support_request"]], on=["person_id", "date"], how="left")
        g = x.groupby("person_id", group_keys=False)
        for c, stem in [("mood_score", "mood"), ("energy_score", "energy"), ("sleep_quality", "sleep_quality"), ("perceived_stress", "perceived_stress"), ("workload_manageability", "workload_manageability")]:
            x[f"{stem}_latest"] = c if False else x[c]
            for d in (7, 30):
                x[f"{stem}_{d}d_mean"] = g[c].transform(lambda s, days=d: s.rolling(days, min_periods=1).mean())
            if stem in ("mood", "sleep_quality", "perceived_stress"):
                x[f"{stem}_change_7d"] = g[c].transform(lambda s: s - s.shift(7))
                x[f"{stem}_change_30d"] = g[c].transform(lambda s: s - s.shift(30))
        x["support_request_recent"] = g["support_request"].transform(lambda s: s.fillna(False).astype(int).rolling(self.config.support_recent_window_days, min_periods=1).max()).astype(int)
        x["wellness_available_today"] = x[score_cols].notna().any(axis=1)
        x["wellness_days_7d"] = g["wellness_available_today"].transform(lambda s: s.astype(int).rolling(7, min_periods=1).sum())
        x["wellness_days_30d"] = g["wellness_available_today"].transform(lambda s: s.astype(int).rolling(30, min_periods=1).sum())
        x.drop(columns=score_cols + ["support_request"], inplace=True)
        return x

    def _add_personal_history(self, x: pd.DataFrame) -> pd.DataFrame:
        g = x.groupby("person_id", group_keys=False)
        x["duty_hours_personal_history_mean"] = g["duty_hours_1d"].transform(lambda s: s.expanding(min_periods=1).mean())
        x["duty_hours_personal_history_std"] = g["duty_hours_1d"].transform(lambda s: s.expanding(min_periods=self.config.min_history_for_std).std())
        x["night_shift_personal_history_mean"] = g["night_shifts_90d"].transform(lambda s: s.expanding(min_periods=1).mean())
        x["rest_personal_history_mean"] = g["avg_rest_7d"].transform(lambda s: s.expanding(min_periods=1).mean())
        x["personal_history_length"] = g.cumcount() + 1
        x["personal_history_std_available"] = x["personal_history_length"] >= self.config.min_history_for_std
        return x

    @staticmethod
    def _completeness(x: pd.DataFrame) -> pd.Series:
        operational = [
            "duty_hours_7d", "duty_hours_30d", "duty_hours_90d", "duty_density_7d", "duty_density_30d",
            "avg_rest_7d", "avg_rest_30d", "current_deployment_days", "incident_count_30d", "training_hours_30d"
        ]
        return x[operational].notna().mean(axis=1)

    def _validate_output(self, x: pd.DataFrame) -> None:
        if x[["person_id", "date"]].duplicated().any():
            raise ValueError("Duplicate person/date feature rows")
        if x.empty:
            raise ValueError("Feature output is empty")
        bad = FORBIDDEN_FEATURE_NAMES.intersection(x.columns)
        if bad:
            raise ValueError(f"Forbidden Phase 3+ feature labels found: {sorted(bad)}")
        if (x[[c for c in x.columns if c.startswith("duty_hours_") and c.endswith("d")]].fillna(0) < 0).any().any():
            raise ValueError("Negative duty-hours feature detected")
        if x["duty_density_7d"].max() > 1 or x["duty_density_30d"].max() > 1:
            raise ValueError("Duty density exceeds 1")

    def write_features(self, output_path: str | Path, start_date=None, end_date=None) -> pd.DataFrame:
        result = self.build_features(start_date, end_date)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(path, index=False)
        return result

    def metadata(self) -> Mapping[str, object]:
        return asdict(self.config)
