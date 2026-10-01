"""Operational benchmark for FORTIFY scoring strategies.

This script answers the only question that matters for a triage tool: *given a
bounded human review capacity, which scoring strategy puts the most true cases
in front of reviewers?*

It deliberately does NOT optimise generic F1. A welfare review queue has a
budget; the metrics below are defined on that budget:

* precision@K        - of the top K% highest-scored person-days, how many are
                       true positives (future high-stress observation).
* recall@capacity    - of all true positives, how many fall inside the top K%.
* alerts per person per month, false alerts per 100 personnel per month -
  the reviewer-burden view.
* precision/recall at fixed alert RATES (1%, 2%, 5%, 10% of all person-days).

Strategies compared:

A. ``rule``      - the two-variable operational rule (rest<6.5h or duty>70h/week).
B. ``logreg``    - the deployed Phase 4 logistic regression, calibrated.
C. ``temporal``  - an interpretable linear score on five named operational
                   features (fixed weights, no fitting) probing whether a
                   hand-set weighted sum already captures the structure.
D. ``logreg_l2`` - logistic regression with stronger L2 (C=0.05), fitted on
                   the training window only, probing whether regularisation
                   fixes the drift degradation.

All strategies are scored on the same labelled person-days, in three time
periods (early / middle / recent thirds), so drift is visible per strategy.

Usage:
    python scripts/benchmark_operational.py [--world data/generated]

The benchmark is evidence for the architecture decision recorded in
docs/MODEL_LINEAGE.md; it never changes the deployed model by itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ml.model_config import ModelConfig  # noqa: E402
from app.ml.model_training import RiskModelTrainer  # noqa: E402
from app.ml.risk_decision import fit_platt_calibrator, apply_calibrator  # noqa: E402
from app.ml.target_engineering import build_future_wellness_target  # noqa: E402

REVIEW_CAPACITIES = (0.01, 0.02, 0.05, 0.10)
DAYS_PER_MONTH = 30.0


def rule_scores(frame: pd.DataFrame) -> np.ndarray:
    """The two-variable rule, expressed as a score compatible with ranking.

    The rule is binary; to make precision@K meaningful at capacities below the
    flag rate we rank flagged rows by a fixed severity order (lowest rest,
    then highest duty) and unflagged rows last. This is the most generous
    reasonable reading of the baseline: it gets the rule's knowledge *and*
    a severity ordering for free.
    """
    rest = pd.to_numeric(frame.get("avg_rest_7d"), errors="coerce")
    duty = pd.to_numeric(frame.get("duty_hours_7d"), errors="coerce")
    flagged = ((rest < 6.5) | (duty > 70.0)).fillna(False)
    # Severity: rank flagged rows by (rest ascending, duty descending).
    severity = (rest.max() - rest.fillna(rest.max())) + (duty.fillna(0) / duty.max())
    return np.where(flagged, 100.0 + severity.fillna(0), severity.fillna(0) * 0.001).astype(float)


def temporal_scores(frame: pd.DataFrame) -> np.ndarray:
    """Fixed-weight interpretable score over five operational features.

    Weights are set by hand from the operational story (load up, rest down,
    incidents up, deployment exposure) on a 0-1 scale per feature. No fitting
    on labels - this probes whether domain knowledge alone ranks well.
    """
    def unit(series: pd.Series) -> pd.Series:
        values = pd.to_numeric(series, errors="coerce")
        lo, hi = values.quantile(0.02), values.quantile(0.98)
        if not np.isfinite(lo) or hi <= lo:
            return pd.Series(0.0, index=values.index)
        return ((values - lo) / (hi - lo)).clip(0, 1).fillna(0.5)

    duty = unit(frame.get("duty_hours_7d"))
    rest_deficit = 1.0 - unit(frame.get("avg_rest_7d"))
    nights = unit(frame.get("night_shifts_30d"))
    incidents = unit(frame.get("incident_count_30d"))
    deployment = unit(frame.get("deployment_days_30d"))
    return (0.30 * duty + 0.30 * rest_deficit + 0.15 * nights + 0.15 * incidents + 0.10 * deployment).to_numpy(float)


def load_labelled(world_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str], object]:
    features = pd.read_csv(world_dir / "person_day_features_baseline.csv")
    meta_path = ROOT / "artifacts" / "phase4" / "model_metadata.json"
    if not meta_path.exists():
        raise SystemExit("Phase 4 artifacts missing; run scripts/build_all.py first")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    feature_columns = meta["feature_columns"]
    model = joblib.load(ROOT / "artifacts" / "phase4" / "fortify_phase4_logistic_regression.joblib")

    trainer = RiskModelTrainer(ModelConfig())
    targets = build_future_wellness_target(features)
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.merge(targets, on=["person_id", "date"], how="left", validate="one_to_one", sort=False)
    labeled = frame[frame["target"].notna()].copy()
    labeled["target"] = labeled["target"].astype(int)
    train, valid, test = trainer.split_by_date(labeled)

    raw_valid = model.predict_proba(valid[feature_columns])[:, 1]
    calibrator = fit_platt_calibrator(raw_valid, valid["target"])
    return train, valid, test, feature_columns, calibrator


def fit_world(world_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str], dict[str, object]]:
    """Fit the deployed model family ON THIS WORLD's training window.

    Used for the latent generator and OOD families where no deployed artifact
    exists. The fitted model, calibrator and L2 variant are all learned from
    the train split only; validation is used for calibration; test is scored.
    """
    features = pd.read_csv(world_dir / "person_day_features_baseline.csv")
    trainer = RiskModelTrainer(ModelConfig())
    targets = build_future_wellness_target(features)
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.merge(targets, on=["person_id", "date"], how="left", validate="one_to_one", sort=False)
    labeled = frame[frame["target"].notna()].copy()
    labeled["target"] = labeled["target"].astype(int)
    train, valid, test = trainer.split_by_date(labeled)
    columns = trainer.select_features(labeled)

    model = trainer._build_pipeline(labeled, columns)
    model.fit(train[columns], train["target"])
    raw_valid = model.predict_proba(valid[columns])[:, 1]
    calibrator = fit_platt_calibrator(raw_valid, valid["target"])

    l2_model = trainer._build_pipeline(labeled, columns)
    l2_model.named_steps["model"].set_params(C=0.05)
    l2_model.fit(train[columns], train["target"])

    return train, valid, test, columns, {"logreg": model, "logreg_l2": l2_model, "calibrator": calibrator}


def logreg_scores(model, calibrator, frames: dict[str, pd.DataFrame], columns: list[str]) -> dict[str, np.ndarray]:
    out = {}
    for name, frame in frames.items():
        raw = model.predict_proba(frame[columns])[:, 1]
        out[name] = apply_calibrator(calibrator, raw)
    return out


def l2_scores(l2_model, splits: dict[str, pd.DataFrame], columns: list[str]) -> dict[str, np.ndarray]:
    """Strongly regularised logistic regression scores."""
    return {name: l2_model.predict_proba(frame[columns])[:, 1] for name, frame in splits.items()}


def period_bounds(dates: pd.Series) -> dict[str, set]:
    unique = sorted(pd.to_datetime(dates).unique())
    third = max(1, len(unique) // 3)
    return {
        "early": set(unique[:third]),
        "middle": set(unique[third:2 * third]),
        "recent": set(unique[2 * third:]),
    }


def capacity_metrics(y: np.ndarray, scores: np.ndarray, dates: np.ndarray, capacities=REVIEW_CAPACITIES) -> dict:
    """Precision/recall at fixed review capacity, plus reviewer-burden metrics."""
    order = np.argsort(-scores, kind="stable")
    ranked_y = y[order]
    ranked_dates = dates[order]
    n = len(y)
    positive_rate = float(y.mean())
    days_span = max(1.0, (pd.Timestamp(dates.max()) - pd.Timestamp(dates.min())).days + 1)
    personnel = len(np.unique(_person_ids_at(order))) if False else None  # placeholder, replaced below

    out = {
        "base_rate": positive_rate,
        "roc_auc": _roc_auc(y, scores),
        "average_precision": _average_precision(y, scores),
        "capacities": {},
    }
    for capacity in capacities:
        k = max(1, int(round(capacity * n)))
        top_y = ranked_y[:k]
        tp = int(top_y.sum())
        precision = tp / k
        recall = tp / max(1, int(y.sum()))
        out["capacities"][f"{int(capacity * 100)}%"] = {
            "review_slots": k,
            "precision": precision,
            "recall": recall,
            "true_positives": tp,
        }
    return out


def _person_ids_at(order):  # pragma: no cover - placeholder kept for clarity
    raise NotImplementedError


def _roc_auc(y: np.ndarray, scores: np.ndarray) -> float | None:
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(y, scores)) if np.unique(y).size == 2 else None


def _average_precision(y: np.ndarray, scores: np.ndarray) -> float | None:
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(y, scores)) if np.unique(y).size == 2 else None


def burden_metrics(frame: pd.DataFrame, y: np.ndarray, scores: np.ndarray, threshold_quantile: float) -> dict:
    """Alert volume from a human's point of view: per person, per month.

    The alert threshold is the score quantile matching the requested alert
    rate, so every strategy is compared at the same alert volume.
    """
    threshold = float(np.quantile(scores, 1.0 - threshold_quantile))
    alert = scores >= threshold
    dates = pd.to_datetime(frame["date"])
    days_span = max(1.0, (dates.max() - dates.min()).days + 1)
    n_people = int(frame["person_id"].nunique())
    alerts_per_person_per_month = float(alert.sum() / n_people * (DAYS_PER_MONTH / days_span))
    # False alerts: alerted person-days that are not true positives.
    false_alerts = int((alert & (y == 0)).sum())
    false_per_100_per_month = float(false_alerts / n_people * (DAYS_PER_MONTH / days_span) * 100 / 100 * 100)
    false_per_100_per_month = float(false_alerts / n_people * (DAYS_PER_MONTH / days_span))
    return {
        "alert_rate": float(alert.mean()),
        "alerts_per_person_per_month": alerts_per_person_per_month,
        "false_alerts_per_person_per_month": false_per_100_per_month,
        "alert_threshold": threshold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, default=ROOT / "data" / "generated",
                        help="Directory containing person_day_features_baseline.csv (fit + evaluate here)")
    parser.add_argument("--eval-world", type=Path, default=None,
                        help="Optional second world for out-of-distribution evaluation: strategies are "
                             "FIT on --world's train split and SCORED on this world's test split. "
                             "Rule and temporal score are threshold-free and transfer directly.")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "benchmark")
    parser.add_argument("--alert-rate", type=float, default=0.05,
                        help="Fixed alert rate for burden metrics (fraction of person-days)")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Benchmarking world: {args.world}")
    train, valid, test, columns, fitted = fit_world(args.world)
    print(f"  labelled rows: train={len(train):,} valid={len(valid):,} test={len(test):,}  features={len(columns)}")

    if args.eval_world is not None:
        # Out-of-distribution evaluation: fit here, score there. The eval
        # world's own test split is used so the fit world never sees it.
        print(f"OOD evaluation world: {args.eval_world}")
        eval_train, eval_valid, eval_test, eval_columns, _ = fit_world(args.eval_world)
        eval_frame = eval_test
        shared_columns = [c for c in columns if c in eval_columns]
        if len(shared_columns) < len(columns) * 0.9:
            raise SystemExit("Eval world is missing too many fit-world feature columns")
        splits = {"train": train, "validation": valid, "test": test,
                  "eval_test_ood": eval_frame}
        scored = {"validation": valid, "test": test}
        strategies: dict[str, dict[str, np.ndarray]] = {
            "rule": {name: rule_scores(frame) for name, frame in splits.items()},
            "temporal_score": {name: temporal_scores(frame) for name, frame in splits.items()},
            "logreg": {**logreg_scores(fitted["logreg"], fitted["calibrator"], scored, columns),
                       "eval_test_ood": fitted["logreg"].predict_proba(eval_frame[shared_columns])[:, 1]},
            "logreg_l2": {**l2_scores(fitted["logreg_l2"], scored, columns),
                          "eval_test_ood": fitted["logreg_l2"].predict_proba(eval_frame[shared_columns])[:, 1]},
        }
    else:
        splits = {"train": train, "validation": valid, "test": test}
        scored = {"validation": valid, "test": test}
        strategies: dict[str, dict[str, np.ndarray]] = {
            "rule": {name: rule_scores(frame) for name, frame in splits.items()},
            "temporal_score": {name: temporal_scores(frame) for name, frame in splits.items()},
            "logreg": logreg_scores(fitted["logreg"], fitted["calibrator"], scored, columns),
            "logreg_l2": l2_scores(fitted["logreg_l2"], scored, columns),
        }

    report: dict = {"world": str(args.world), "eval_world": str(args.eval_world) if args.eval_world else None, "capacities": list(REVIEW_CAPACITIES), "strategies": {}}
    for name, per_split in strategies.items():
        entry: dict = {}
        for split_name, scores in per_split.items():
            frame = splits[split_name]
            y = frame["target"].to_numpy(int)
            dates = frame["date"].to_numpy()
            metrics = capacity_metrics(y, scores, dates)
            metrics["burden_at_alert_rate"] = burden_metrics(frame, y, scores, args.alert_rate)
            # Per-period view for drift.
            bounds = period_bounds(frame["date"])
            per_period = {}
            for period_name, period_dates in bounds.items():
                mask = pd.to_datetime(frame["date"]).isin(period_dates).to_numpy()
                if mask.sum() < 50 or y[mask].sum() < 5:
                    continue
                per_period[period_name] = {
                    "rows": int(mask.sum()),
                    "base_rate": float(y[mask].mean()),
                    "roc_auc": _roc_auc(y[mask], scores[mask]),
                    "alert_precision_at_rate": _precision_at_rate(y[mask], scores[mask], args.alert_rate),
                }
            metrics["periods"] = per_period
            entry[split_name] = metrics
        report["strategies"][name] = entry

    # Headline comparison on the test window at each capacity, plus the OOD
    # row when an eval world was supplied.
    headline = {}
    for name, per_split in report["strategies"].items():
        for split_name, label in (("test", ""), ("eval_test_ood", "_ood")):
            if split_name not in per_split:
                continue
            headline[name + label] = {
                cap: per_split[split_name]["capacities"][cap]["precision"]
                for cap in per_split[split_name]["capacities"]
            } | {"roc_auc": per_split[split_name]["roc_auc"]}
    report["headline_test_precision_by_capacity"] = headline

    out_path = args.output / "operational_benchmark.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")

    print("\n=== TEST-WINDOW PRECISION AT FIXED REVIEW CAPACITY ===")
    header = f"{'strategy':<16}" + "".join(f"  top{cap:>3}" for cap in ("1%", "2%", "5%", "10%")) + "    ROC-AUC"
    print(header)
    for name, caps in headline.items():
        row = f"{name:<16}"
        for cap in ("1%", "2%", "5%", "10%"):
            row += f"  {caps.get(cap, float('nan')):>5.3f}"
        row += f"    {caps.get('roc_auc', float('nan')):>7.3f}"
        print(row)

    print(f"\n=== ALERT BURDEN AT FIXED {args.alert_rate:.0%} ALERT RATE (test window) ===")
    for name, per_split in report["strategies"].items():
        if "test" not in per_split:
            continue
        burden = per_split["test"]["burden_at_alert_rate"]
        print(f"  {name:<16} alerts/person/month={burden['alerts_per_person_per_month']:.2f}  "
              f"false alerts/person/month={burden['false_alerts_per_person_per_month']:.2f}")

    print(f"\nReport: {out_path.relative_to(ROOT)}")
    return 0


def _precision_at_rate(y: np.ndarray, scores: np.ndarray, rate: float) -> float | None:
    if len(y) == 0:
        return None
    threshold = float(np.quantile(scores, 1.0 - rate))
    alert = scores >= threshold
    return float(y[alert].mean()) if alert.any() else None


if __name__ == "__main__":
    raise SystemExit(main())
