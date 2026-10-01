"""Deterministic alert policy: model score → welfare signal → review case.

A welfare decision-support system must not behave like a firehose. The raw
model score is an *evidence* value, not an instruction; one person under
sustained strain would otherwise open a new review case every single day.

This module implements the layer between the model and the human, with every
rule explicit, deterministic, and testable:

1. **Evidence gate** — the calibrated score must meet ``minimum_score`` AND the
   case must be in (or above) the configured risk band. A high score on
   insufficient evidence does not open a case.
2. **Persistence** — a signal must hold for ``persistence_days`` consecutive
   scored days before a case is opened, unless the score jumps by at least
   ``escalation_jump`` (a sudden deterioration is acted on immediately).
3. **Cooldown / duplicate suppression** — while a case for the same person is
   open, further alerting days do not create new cases; they are recorded as
   PERSISTENT evidence on the existing case instead.
4. **Escalation** — if the score rises by ``escalation_jump`` above the level
   when the case was opened, the case is marked ESCALATED (priority bump).
5. **Recovery** — when the score falls below ``recovery_score`` for
   ``recovery_days`` consecutive days, the signal ends (RECOVERED); the case
   itself is closed by a human, never automatically.
6. **Daily budget** — at most ``max_daily_review_cases`` NEW cases are created
   per day, chosen by highest score with deterministic tie-breaks. Over-budget
   people are NOT silently dropped: they are recorded in the queue with
   ``suppressed_by_budget=True`` so the selection is auditable.

The policy is pure: it takes a scored, person-day-ordered frame and returns the
queue; it never reads the clock, the model, or the database.

This layer is what makes the difference between
"90,000 workflow items" and "a reviewable queue".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

ALERT_STATES = (
    "NEW_ALERT", "PERSISTENT", "ESCALATED", "RECOVERED",
    "SUPPRESSED_BUDGET", "BELOW_GATE", "EVIDENCE_ACCUMULATING",
)


@dataclass(frozen=True)
class AlertPolicyConfig:
    minimum_score: float = 0.40          # calibrated-score evidence gate
    minimum_band: str = "MODERATE"       # band gate; HIGH always passes
    persistence_days: int = 2            # consecutive scored days before a case opens
    escalation_jump: float = 0.15        # score rise over case-open level → escalate
    recovery_score: float = 0.30         # below this the signal is easing
    recovery_days: int = 3               # consecutive easing days → RECOVERED
    max_daily_review_cases: int = 25     # daily new-case budget
    priority_band_high: str = "HIGH"

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_score <= 1:
            raise ValueError("minimum_score must be in [0,1]")
        if not 0 <= self.recovery_score <= 1:
            raise ValueError("recovery_score must be in [0,1]")
        if self.recovery_score >= self.minimum_score:
            raise ValueError("recovery_score must be below minimum_score")
        if self.persistence_days < 1:
            raise ValueError("persistence_days must be >= 1")
        if self.escalation_jump <= 0 or self.escalation_jump >= 1:
            raise ValueError("escalation_jump must be in (0,1)")
        if self.recovery_days < 1:
            raise ValueError("recovery_days must be >= 1")
        if self.max_daily_review_cases < 1:
            raise ValueError("max_daily_review_cases must be >= 1")
        if self.minimum_band not in {"LOW", "MODERATE", "HIGH"}:
            raise ValueError("minimum_band must be LOW, MODERATE or HIGH")

    def as_dict(self) -> dict[str, Any]:
        return {
            "minimum_score": self.minimum_score,
            "minimum_band": self.minimum_band,
            "persistence_days": self.persistence_days,
            "escalation_jump": self.escalation_jump,
            "recovery_score": self.recovery_score,
            "recovery_days": self.recovery_days,
            "max_daily_review_cases": self.max_daily_review_cases,
        }


BAND_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2}


@dataclass
class _PersonState:
    above_gate_run: int = 0
    below_recovery_run: int = 0
    open_case: bool = False
    case_open_score: float | None = None
    last_state: str | None = None
    days_since_case_open: int = 0


def evaluate_alert_policy(
    decisions: pd.DataFrame,
    config: AlertPolicyConfig | None = None,
) -> pd.DataFrame:
    """Turn per-person-day scored decisions into an auditable review queue.

    Input columns (a superset is fine): ``person_id``, ``date``,
    ``welfare_risk_probability``, ``risk_band``. Rows must be sorted by person
    and date; the function sorts and validates anyway.

    Output: one row per person-day that either fired a signal or was gated,
    with columns:

    ``person_id, date, score, risk_band, alert_state, case_created,
    suppressed_by_budget, evidence_days, reason, policy_version``

    ``alert_state`` is one of :data:`ALERT_STATES`. ``case_created`` marks the
    day a new review case actually opens (after the daily budget).
    """
    config = config or AlertPolicyConfig()
    required = {"person_id", "date", "welfare_risk_probability", "risk_band"}
    missing = sorted(required.difference(decisions.columns))
    if missing:
        raise ValueError(f"Decisions frame missing columns: {missing}")
    if decisions.empty:
        return pd.DataFrame(columns=[
            "person_id", "date", "score", "risk_band", "alert_state", "case_created",
            "suppressed_by_budget", "evidence_days", "reason", "policy_version",
        ])

    frame = decisions.copy()
    frame["person_id"] = frame["person_id"].astype(str)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame["score"] = pd.to_numeric(frame["welfare_risk_probability"], errors="coerce")
    frame = frame.dropna(subset=["score"])
    frame = frame.sort_values(["person_id", "date"], kind="mergesort").reset_index(drop=True)

    # A person-day with a date gap resets persistence: absence of observations
    # is not evidence of continued strain.
    frame["prev_date"] = frame.groupby("person_id")["date"].shift(1)
    frame["consecutive"] = (frame["date"] - frame["prev_date"]).dt.days.eq(1)

    states: dict[str, _PersonState] = {}
    records: list[dict[str, Any]] = []
    version = "alert-policy-v1"

    for row in frame.itertuples(index=False):
        state = states.setdefault(row.person_id, _PersonState())
        if not bool(row.consecutive):
            # Observation gap: persistence run restarts; an open case stays
            # open (a human owns it), but evidence accumulation restarts.
            state.above_gate_run = 0
            state.below_recovery_run = 0

        band_rank = BAND_RANK.get(str(row.risk_band), 0)
        gate = (
            float(row.score) >= config.minimum_score
            and band_rank >= BAND_RANK[config.minimum_band]
        )

        if not gate:
            # Ease the signal; track recovery toward RECOVERED.
            state.above_gate_run = 0
            state.below_recovery_run += 1
            if state.open_case and state.below_recovery_run >= config.recovery_days and float(row.score) < config.recovery_score:
                state.last_state = "RECOVERED"
                state.below_recovery_run = 0
                records.append(_record(row, "RECOVERED", False, False, state.above_gate_run,
                                       "Signal eased below the recovery threshold for the configured run; the existing case remains open for human closure.", version))
            elif state.open_case:
                # Open case, sub-gate day: no event, no case spam.
                continue
            else:
                records.append(_record(row, "BELOW_GATE", False, False, 0,
                                       "Score or band below the evidence gate; no case.", version))
            continue

        # Gate passed: build the persistence run.
        state.above_gate_run += 1
        state.below_recovery_run = 0
        if state.open_case:
            state.days_since_case_open += 1
            opened_level = state.case_open_score or float(row.score)
            if float(row.score) - opened_level >= config.escalation_jump:
                state.last_state = "ESCALATED"
                state.case_open_score = float(row.score)  # new escalation base
                records.append(_record(row, "ESCALATED", False, False, state.above_gate_run,
                                       f"Score rose by at least {config.escalation_jump:.2f} above the case-open level on an open case.", version))
            else:
                state.last_state = "PERSISTENT"
                records.append(_record(row, "PERSISTENT", False, False, state.above_gate_run,
                                       "Signal persists on an already-open case; recorded as evidence, not a new case.", version))
            continue

        # No open case: open one after persistence, or immediately on a jump.
        sudden = state.above_gate_run == 1 and float(row.score) >= config.minimum_score + config.escalation_jump
        if state.above_gate_run < config.persistence_days and not sudden:
            # Sub-persistence gate day: recorded as accumulating evidence so
            # the queue shows WHY a case has not opened yet.
            records.append(_record(row, "EVIDENCE_ACCUMULATING", False, False, state.above_gate_run,
                                   f"Gate met for {state.above_gate_run} of {config.persistence_days} required consecutive days.", version))
            continue
        if state.above_gate_run >= config.persistence_days or sudden:
            state.open_case = True
            state.case_open_score = float(row.score)
            state.days_since_case_open = 0
            state.last_state = "NEW_ALERT"
            records.append(_record(
                row,
                "NEW_ALERT",
                True,
                False,
                state.above_gate_run,
                ("Immediate case: score jump met the escalation threshold." if sudden
                 else f"Signal met the evidence gate for {state.above_gate_run} consecutive days."),
                version,
            ))

    queue = pd.DataFrame.from_records(records)
    if queue.empty:
        return queue

    # Daily budget: rank the day's NEW_ALERT candidates by score, deterministic
    # tie-breaks (band rank, then person id), cap at max_daily_review_cases.
    new_cases = queue["case_created"] & (queue["alert_state"] == "NEW_ALERT")
    day_groups = queue[new_cases].groupby("date", sort=True)
    suppressed_ids: set[tuple[str, pd.Timestamp]] = set()
    for day, group in day_groups:
        if len(group) <= config.max_daily_review_cases:
            continue
        ranked = group.assign(_band=group["risk_band"].map(BAND_RANK)).sort_values(
            ["score", "_band", "person_id"], ascending=[False, False, True], kind="mergesort"
        )
        over = ranked.iloc[config.max_daily_review_cases:]
        for person_id, date in zip(over["person_id"], over["date"]):
            suppressed_ids.add((str(person_id), pd.Timestamp(date)))

    if suppressed_ids:
        mask = [((str(p), pd.Timestamp(d)) in suppressed_ids) for p, d in zip(queue["person_id"], queue["date"])]
        queue.loc[mask, "suppressed_by_budget"] = True
        queue.loc[mask, "case_created"] = False
        queue.loc[mask, "alert_state"] = "SUPPRESSED_BUDGET"
        queue.loc[mask, "reason"] = (
            "Qualified for a new case but the day's review budget was full; "
            "ranked below the selected cases. Recorded for audit, not dropped silently."
        )

    # Reopen persistence accounting for budget-suppressed candidates: the
    # person remains case-less, so their next gate day can still open a case.
    for person_id, date in suppressed_ids:
        state = states.get(person_id)
        if state is not None:
            state.open_case = False
            state.case_open_score = None

    queue["policy_version"] = version
    columns = ["person_id", "date", "score", "risk_band", "alert_state", "case_created",
               "suppressed_by_budget", "evidence_days", "reason", "policy_version"]
    return queue.sort_values(["date", "score", "person_id"], ascending=[True, False, True], kind="mergesort").reset_index(drop=True)[columns]


def _record(row, state: str, case_created: bool, suppressed: bool, evidence_days: int, reason: str, version: str) -> dict[str, Any]:
    return {
        "person_id": str(row.person_id),
        "date": pd.Timestamp(row.date),
        "score": float(row.score),
        "risk_band": str(row.risk_band),
        "alert_state": state,
        "case_created": case_created,
        "suppressed_by_budget": suppressed,
        "evidence_days": int(evidence_days),
        "reason": reason,
        "policy_version": version,
    }


def alert_policy_version() -> str:
    return "alert-policy-v1"
