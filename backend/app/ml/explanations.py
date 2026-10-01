"""Deterministic, provenance-carrying explanations for FORTIFY predictions.

An explanation is a *claim*, so it must be auditable. This module produces
structured factors where every field traces back to a computed value in the
feature row:

    what changed        - the operational quantity and its direction
    how much            - the measured value and the size of the change
    compared with what  - the reference it is measured against
    over what period    - the window the measurement covers
    why it contributed  - the rule that admitted it and the weight it carried

Nothing here is free text that a reader must take on faith. Two runs over the
same feature row produce identical output, and every number is reproducible
from the generated CSVs.

The factors are operational context only. They are *associated with* the
prediction through the model's own coefficients - no SHAP-style attribution is
claimed, because a linear model's contribution is a coefficient-times-value and
saying more would be unsupported. Raw wellness responses are never read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# The 8-hour recovery reference is an operational planning figure, not a
# clinical sleep recommendation. It is stated in the explanation so the reader
# can see what they are being compared against.
RECOVERY_HOURS_REFERENCE = 8.0
DEPLOYMENT_WINDOW_DAYS = 30

# Minimum relative change for a deviation to be worth mentioning. Below this a
# factor would say "nothing meaningful changed", which is worse than silence.
MIN_RELATIVE_DEVIATION = 0.05


@dataclass(frozen=True)
class Factor:
    """One contributing operational factor, with full provenance."""

    factor_id: str
    signal: str
    direction: str
    value: float
    value_display: str
    comparison: str
    reference: str | None
    reference_display: str | None
    window: str
    change: float | None
    change_display: str | None
    weight: float
    rule: str
    comparison_kind: str  # personal | operational | cohort | absolute
    metric_column: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "signal": self.signal,
            "direction": self.direction,
            "value": self.value,
            "value_display": self.value_display,
            "comparison": self.comparison,
            "reference": self.reference,
            "reference_display": self.reference_display,
            "window": self.window,
            "change": self.change,
            "change_display": self.change_display,
            "weight": round(self.weight, 4),
            "rule": self.rule,
            "comparison_kind": self.comparison_kind,
            "metric_column": self.metric_column,
        }

    def as_sentence(self) -> str:
        """Human-readable form with every provenance element present."""
        ref = f" vs {self.reference_display}" if self.reference_display else ""
        change = (
            f", changed by {self.change_display} over the same window"
            if self.change_display else ""
        )
        return (
            f"{self.signal}: {self.value_display}{ref}{change} "
            f"({self.window}; compared with {self.comparison})."
        )


def _number(value: Any) -> float | None:
    """Return a finite float, or None. NaN/inf/None all mean 'not measurable'."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _present(value: Any) -> bool:
    return _number(value) is not None


def _rule(
    comparison_kind: str,
    window: str,
) -> str:
    """The admission rule, stated in terms a reviewer can re-derive."""
    return (
        f"Admitted because the {window} value deviates by more than "
        f"{int(MIN_RELATIVE_DEVIATION * 100)}% from the {comparison_kind} reference."
    )


def _personal_factor(
    row: pd.Series,
    *,
    factor_id: str,
    signal: str,
    metric_column: str,
    deviation_column: str,
    relative_column: str,
    reference_column: str,
    window: str,
    units: str,
) -> Factor | None:
    """Build a factor measured against the person's own history.

    The reference is strictly prior-day history; if there is not enough history
    the reference column is NaN and the factor is withheld rather than
    fabricated from a population average.

    Only adverse deviations are admitted. A drop in incident exposure is a
    favourable change, and presenting it as a factor "contributing" to an
    elevated-risk prediction would be misleading even though the model does use
    the quantity. Silence here is the honest outcome when nothing adverse
    changed.
    """
    deviation = _number(row.get(deviation_column))
    if deviation is None or deviation <= 0:
        # Not adverse (or not measurable): not a contributing factor.
        return None
    relative = _number(row.get(relative_column))
    if relative is None or relative < MIN_RELATIVE_DEVIATION:
        # Either no usable reference or an increase too small to be a signal.
        return None

    value = _number(row.get(metric_column))
    if value is None:
        return None

    reference = _number(row.get(reference_column))
    if reference is None:
        # Personal reference exists (the deviation is finite) but was not
        # carried into this row; do not invent one.
        return None

    return Factor(
        factor_id=factor_id,
        signal=signal,
        direction="higher",
        value=value,
        value_display=f"{value:.1f} {units}",
        comparison="the person's own prior history",
        reference=reference,
        reference_display=f"{reference:.1f} {units}",
        window=window,
        change=deviation,
        change_display=f"{deviation:+.1f} {units}",
        weight=relative,
        rule=_rule("personal history", window),
        comparison_kind="personal",
        metric_column=metric_column,
    )


def _relative_factor(
    row: pd.Series,
    *,
    factor_id: str,
    signal: str,
    value_column: str,
    relative_column: str,
    reference_column: str | None,
    window: str,
    units: str,
    comparison: str,
    comparison_kind: str,
) -> Factor | None:
    """A factor measured against a same-day peer reference.

    Admitted only when the person is *above* the reference: being below peer
    workload is not a plausible contributor to an elevated-risk flag, and
    saying so would make the explanation read as filler.
    """
    value = _number(row.get(value_column))
    if value is None:
        return None
    relative = _number(row.get(relative_column))
    if relative is None or relative < MIN_RELATIVE_DEVIATION:
        return None
    reference = _number(row.get(reference_column)) if reference_column else None
    if reference_column is not None and reference is None:
        return None

    return Factor(
        factor_id=factor_id,
        signal=signal,
        direction="higher",
        value=value,
        value_display=f"{value:.1f} {units}",
        comparison=comparison,
        reference=reference,
        reference_display=f"{reference:.1f} {units}" if reference is not None else None,
        window=window,
        change=None,
        change_display=None,
        weight=relative,
        rule=_rule(comparison_kind, window),
        comparison_kind=comparison_kind,
        metric_column=value_column,
    )


def _recovery_factor(row: pd.Series) -> Factor | None:
    """Reduced recent recovery, measured against the operational reference.

    This is an absolute comparison on purpose: rest below an operational
    planning figure is a direct signal, and a personal-history reference is not
    available on a person's first days.
    """
    value = _number(row.get("avg_rest_7d"))
    if value is None or value >= RECOVERY_HOURS_REFERENCE:
        return None
    deficit = RECOVERY_HOURS_REFERENCE - value
    return Factor(
        factor_id="recovery_deficit_7d",
        signal="reduced recent recovery",
        direction="lower",
        value=value,
        value_display=f"{value:.1f} hours average rest",
        comparison=f"the {RECOVERY_HOURS_REFERENCE:.0f}-hour operational recovery reference",
        reference=RECOVERY_HOURS_REFERENCE,
        reference_display=f"{RECOVERY_HOURS_REFERENCE:.0f} hours",
        window="last 7 days",
        change=None,
        change_display=None,
        weight=deficit,
        rule=(
            f"Admitted because average rest over the last 7 days is below the "
            f"{RECOVERY_HOURS_REFERENCE:.0f}-hour operational recovery reference."
        ),
        comparison_kind="absolute",
        metric_column="avg_rest_7d",
    )


def _deployment_factor(row: pd.Series) -> Factor | None:
    days = _number(row.get("deployment_days_30d"))
    if days is None or days <= 0:
        return None
    return Factor(
        factor_id="deployment_exposure_30d",
        signal="sustained deployment exposure",
        direction="present",
        value=days,
        value_display=f"{days:.0f} deployment days",
        comparison="no deployment exposure",
        reference=0.0,
        reference_display="0 days",
        window=f"last {DEPLOYMENT_WINDOW_DAYS} days",
        change=None,
        change_display=None,
        weight=min(days / DEPLOYMENT_WINDOW_DAYS, 1.0),
        rule=(
            f"Admitted because the person has recorded deployment days within the "
            f"last {DEPLOYMENT_WINDOW_DAYS} days."
        ),
        comparison_kind="absolute",
        metric_column="deployment_days_30d",
    )


def build_factors(row: pd.Series, max_factors: int = 5) -> list[Factor]:
    """Return the contributing operational factors for one person-day.

    Ordering is deterministic: larger normalised deviation first, then by
    factor id, so identical input always yields identical output.
    """
    factors: list[Factor] = []

    personal = [
        dict(
            factor_id="duty_hours_7d_personal_deviation",
            signal="elevated recent duty hours",
            metric_column="duty_hours_7d",
            deviation_column="duty_hours_7d_personal_deviation",
            relative_column="duty_hours_7d_personal_relative_deviation",
            reference_column="duty_hours_7d_personal_history_mean",
            window="last 7 days",
            units="hours/week",
        ),
        dict(
            factor_id="night_shifts_30d_personal_deviation",
            signal="increased night-shift exposure",
            metric_column="night_shifts_30d",
            deviation_column="night_shifts_30d_personal_deviation",
            relative_column="night_shifts_30d_personal_relative_deviation",
            reference_column="night_shifts_30d_personal_history_mean",
            window="last 30 days",
            units="shifts/month",
        ),
        dict(
            factor_id="incident_count_30d_personal_deviation",
            signal="increased recent incident exposure",
            metric_column="incident_count_30d",
            deviation_column="incident_count_30d_personal_deviation",
            relative_column="incident_count_30d_personal_relative_deviation",
            reference_column="incident_count_30d_personal_history_mean",
            window="last 30 days",
            units="incidents/month",
        ),
    ]
    for spec in personal:
        factor = _personal_factor(row, **spec)
        if factor is not None:
            factors.append(factor)

    contextual = [
        dict(
            factor_id="duty_hours_30d_cohort_relative_deviation",
            signal="duty load above the cohort reference",
            value_column="duty_hours_30d",
            relative_column="duty_hours_30d_cohort_relative_deviation",
            reference_column="duty_hours_30d_cohort_baseline_mean",
            window="last 30 days",
            units="hours over 30 days",
            comparison="peers in the same role and deployment type on the same day",
            comparison_kind="cohort",
        ),
        dict(
            factor_id="duty_hours_30d_operational_relative_deviation",
            signal="duty load above the operational reference",
            value_column="duty_hours_30d",
            relative_column="duty_hours_30d_operational_relative_deviation",
            reference_column="duty_hours_30d_operational_baseline_mean",
            window="last 30 days",
            units="hours over 30 days",
            comparison="others in the same unit type on the same day",
            comparison_kind="operational",
        ),
    ]
    for spec in contextual:
        factor = _relative_factor(row, **spec)
        if factor is not None:
            factors.append(factor)

    for builder in (_recovery_factor, _deployment_factor):
        factor = builder(row)
        if factor is not None:
            factors.append(factor)

    factors.sort(key=lambda f: (-f.weight, f.factor_id))
    return factors[:max_factors]


def render_factors(factors: list[Factor]) -> str:
    """Backwards-compatible single-string form for the generated CSV column."""
    return " | ".join(factor.as_sentence() for factor in factors)


def explain_row(row: pd.Series, max_factors: int = 5) -> dict[str, Any]:
    """Full structured explanation for one person-day row.

    Includes the factor list plus the model's own feature contributions for the
    factors shown, so a reader can see both the operational story and the
    model's stated reliance on each quantity.
    """
    factors = build_factors(row, max_factors=max_factors)
    return {
        "factors": [f.as_dict() for f in factors],
        "summary": render_factors(factors),
        "note": (
            "Operational context only. Each factor states what changed, by how "
            "much, compared with what, over what period, and the rule that "
            "admitted it. These factors are associated with the prediction; they "
            "are not a clinical or psychological interpretation."
        ),
    }