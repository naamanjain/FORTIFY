# FORTIFY model lineage and forensic audit

This document traces every stage from source data to human action, records
what was verified at each stage, and states the architectural decision that
the evidence supports. It is written to be checkable: every claim names the
script or test that backs it.

**Date:** 2026-10-01 · **Pipeline:** `pipeline-v2-latent-aware` · **Seed:** 42

---

## 1. Stage-by-stage trace

| # | Stage | Input → Output | Time window | Verification | Known limits |
|---|---|---|---|---|---|
| 1 | Synthetic world | `generate_synthetic_data.py` → 9 event CSVs | 180 days | `validate_synthetic_data.py`, data-quality audit | Two generator mechanisms (below); neither is real-world data |
| 2 | Target construction | `wellness_events.perceived_stress ≥ 4` in T+1..T+7 → `target` | Future window T+1..T+7 | `validate_model_validity.py` future-leakage probe (features recomputed from truncated sources are identical) | Label exists only where a voluntary report exists in the horizon (~29% of person-days labelled) |
| 3 | Features (Phase 2) | Event CSVs → `person_day_features.csv` | All rolling windows closed at T | Edge-case tests: gap handling, transfer, sparse wellness | Rolling `min_periods=1` means early days have partial windows |
| 4 | Baselines (Phase 3) | Features → `person_day_features_baseline.csv` | Personal: strictly prior days. Cohort/operational: same day, excluding self | `validate_baselines.py`; sufficiency guards tested | Expanding personal mean includes early ramp days (small persistent deviation) |
| 5 | Train split | Labelled rows, dates ≤ day 107 | Disjoint date ranges | Contamination probe (no date overlap; person overlap is by design and disclosed) | Personnel shared across splits |
| 6 | Validation split | Days 108–143 | Disjoint | Same | Used for Platt calibration + threshold selection |
| 7 | Test split | Days 144–179 | Disjoint | Same | Never used for fitting, calibration, or threshold selection |
| 8 | Threshold selection | Candidate sweep on calibrated validation probabilities | Recent half of validation window | Both policy thresholds recorded in model card | Precision floor 0.55 is prototype tuning, not policy |
| 9 | Prediction | Model + calibrator → `risk_decisions.csv` | All 90,000 person-days | Reproducible byte-identical at seed 42 | Calibrated on validation only |
| 10 | Explanation | Feature row → structured factors (`explanations.jsonl`) | Same day T | Fidelity tests: value/reference/window/rule checked against source columns | Associative only; adverse-direction only |
| 11 | Intervention policy | Band + context signals → recommendation + provenance | Same day T | Provenance validated against rule ids; forbidden-terms guard | Deterministic mapping, no outcome simulation |
| 12 | Alert policy | Scores → review queue (persistence, budget, escalation) | Longitudinal | `test_alert_policy.py` (12 cases); fatigue simulation | Policy parameters are documented defaults, not policy |
| 13 | Human workflow | Queue cases → state machine → audit | Human-driven | 20/20 lifecycle; concurrency tests (SQLite + PostgreSQL) | Terminal states human-closed only |

## 2. Generator forensics — the finding that reframed the benchmark

### 2.1 Legacy generator (shipped demo world, `--generator legacy`)

`wellness_row()` computes:

```
pressure = 0.55·max(0, duty_hours−8) + 0.75·max(0, 8−rest) + 0.6·training + 0.9·incidents
perceived_stress = clip(round(2.1 + 0.45·(pressure + N(0, 0.65))), 1, 5)
```

**The label is a same-day noisy linear transform of the same variables the
model sees as features.** Consequences, all measured:

- The Bayes-optimal predictor is a linear function of the features.
- A hand-weighted 5-feature sum, set from domain knowledge with **no
  fitting**, matches or beats the fitted 218-feature model at every review
  capacity (top-1% precision 0.804 vs 0.725; see §3).
- Any "model vs rule" comparison on this world is a test of fitting noise,
  not of predictive value. **No claim of ML value can be made from this
  generator, in either direction.**

### 2.2 Latent generator (`--generator latent`)

Built to remove the shortcut:

```
strain_{t} = (1−φ)·strain_{t−1} + φ·sensitivity_p·load_{t−1} + N(0, 0.12)
perceived_stress = clip(round(1.4 + 2.45·(strain + N(0, 0.45))), 1, 5)
P(report) falls as strain rises (the strained report less often)
sensitivity_p ~ N(1.0, 0.25) per person
```

Properties: the label depends on **past** load (lagged, φ=0.35), with
**person-specific sensitivity** (personal baselines are required), **noisy
measurement**, and **strain-dependent reporting**. Positive-report base rate
24.4% (realistic), versus a same-day linear label in the legacy world.

## 3. Benchmark: strategies at review capacities

`scripts/benchmark_operational.py` (report: `artifacts/benchmark/operational_benchmark.json`).
Metrics are capacity-based, not generic F1: precision@K for K ∈ {1,2,5,10}%
of person-days, ROC-AUC, and alerts-per-person-per-month at a fixed 5% alert
rate. Strategies: the two-variable **rule**, a **temporal score** (5 features,
hand-weighted, no fitting), the deployed **logreg** (calibrated), and
**logreg-L2** (C=0.05). All models fit on the train window only.

### 3.1 Legacy world (in-distribution test window)

| Strategy | top-1% | top-2% | top-5% | top-10% | ROC-AUC |
|---|---|---|---|---|---|
| rule (severity-ordered) | 0.745 | **0.784** | 0.706 | 0.647 | 0.770 |
| temporal_score | **0.804** | **0.784** | **0.773** | **0.741** | 0.760 |
| logreg | 0.725 | 0.716 | 0.706 | 0.643 | 0.763 |
| logreg_l2 | 0.706 | 0.667 | 0.682 | 0.675 | **0.774** |

**The fitted model adds nothing here and is worse at every capacity than the
unfitted temporal score.** Expected from §2.1.

### 3.2 Latent world (in-distribution test window)

| Strategy | top-1% | top-2% | top-5% | top-10% | ROC-AUC |
|---|---|---|---|---|---|
| rule | 0.915 | 0.874 | 0.890 | 0.871 | 0.732 |
| temporal_score | 0.851 | 0.905 | 0.919 | 0.915 | **0.743** |
| logreg | **0.936** | **0.916** | 0.928 | 0.913 | 0.711 |
| logreg_l2 | 0.872 | 0.905 | **0.932** | **0.926** | 0.721 |

At small capacities (where review budgets actually bite) the fitted model is
2–4 pp more precise than the rule. Its ROC-AUC is nonetheless *lower* than the
temporal score's: the model wins at the top of the ranking, not across it.

### 3.3 Out-of-distribution families (fit on latent-DEFAULT, score on family test windows)

| Family | best fitted model top-2% (OOD) | rule top-2% (OOD) | temporal top-2% (OOD) |
|---|---|---|---|
| NOISY_MEASUREMENT | **0.974** (logreg) | 0.872 | 0.859 |
| NEW_COHORT (new personnel) | **0.900** (logreg_l2) | 0.843 | 0.871 |
| HIGHER_TEMPO | 0.923 (logreg_l2) | **0.987** | 0.897 |

The fitted model generalises better than the rule on two of three families and
loses on HIGHER_TEMPO, where elevated prevalence rewards broad flagging. Under
measurement noise and cohort change — the conditions closest to a real
deployment — the fitted model's top-of-ranking advantage persists or grows.

### 3.4 Drift (legacy world, by period, at fixed 5% alert rate)

Validation precision at the operating point transfers imperfectly: the
positive rate drifts 0.455 (train) → 0.355 (validation) → 0.350 (test), and
monthly mean scores drift accordingly. Selecting the threshold on the most
recent validation half (deployed behaviour) transferred better than the
full-window policy (test recall 0.309 vs 0.227 at comparable precision).
Drift is surfaced via `/api/dashboard/system-health` (`score_drift`) as a
review indicator; **no automatic model change is triggered by drift.**

## 4. Alert-fatigue evidence

`scripts/simulate_alert_fatigue.py` on the demo world (500 personnel × 180 days):

| Measure | Value |
|---|---|
| Naive "case per threshold day" | 45,735 cases |
| After alert policy (persistence + suppression + budget) | **183 cases** |
| Duplicate alerts prevented | 45,263 |
| Suppressed by daily budget (recorded, auditable) | 289 |
| New cases per day | mean 3.8, max 25 (budget) |
| Cases per person | mean 1.0, max 1 |
| Personnel generating no case | 317 of 500 |

The workflow now materializes cases **only** from the queue (workflow rows:
90,000 → ~183), while the full recommendation stream stays available for
audit. Human workflow state machines, audit chains and lifecycle tests are
unchanged.

## 5. Architectural decision (evidence-based)

**OPTION B — ML is useful for ranking, not as a classifier — with an honest
qualification.**

- On the legacy generator no model beats the rule (§3.1); the label mechanism
  makes fitted ML pointless there.
- On the latent families the fitted model's advantage exists only at the top
  of the ranking (small review budgets), is 2–4 pp in-distribution, and
  persists or grows OOD on 2 of 3 families (§3.2–3.3). It is never large
  enough to justify autonomous action, and it reverses under high tempo.
- Therefore the deployed design uses the calibrated model **as one ranking
  input to a bounded human review queue**, alongside rule-based and
  personal-baseline evidence, with every case human-owned. The system is
  designed so that its governance properties (audit, purpose limitation,
  budget, explanations) hold **even if the model were uninformative**.
- OPTION A (ML provides meaningful incremental value) is **not supported** by
  this evidence and is not claimed. OPTION C alone (rules only) would forfeit
  the consistent top-of-ranking advantage on the latent families.

## 6. What would change this decision

- A real (non-synthetic) labelled welfare outcome with meaningful prevalence.
- Demonstration, on that data, of a sustained top-K precision advantage over
  the rule + personal-baseline score at the department's actual review
  capacity, evaluated prospectively over time.
- Until then, the model's ranking is treated as one signal among several and
  the model card's prohibited-use list applies.
