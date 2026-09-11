# Model Specification

## Intelligence pipeline
1. Data ingestion
2. Feature engineering
3. Personal baseline
4. Cohort baseline
5. Operational baseline
6. Temporal / trajectory analysis
7. Risk forecasting
8. Uncertainty / data sufficiency
9. Explainability
10. Intervention simulation
11. Operational constraint engine
12. Recommendation ranking
13. Outcome tracking

## Model requirements
Prefer simple, deterministic, and explainable approaches. The architecture must support longitudinal trends rather than isolated observations and must contextualize deviations against appropriate baselines.

## Later-stage output contract
The eventual system output contract includes risk level, trajectory, confidence, data sufficiency, human-readable contributors, and ranked recommended interventions. Phase 4 implements only the predictive probability/risk-level portion; trajectory interpretation, uncertainty presentation, explainability, and intervention ranking belong to later phases.

## Guardrails
Never output mental-health diagnoses. Never fabricate accuracy metrics. Never treat missing voluntary wellness data as stress evidence. Do not use an LLM as the welfare decision-maker. Synthetic demonstration numbers are not clinical validation.

## Phase 2 status — feature inputs only
Phase 2 creates model-ready operational features from the Phase 1 longitudinal event world. It does **not** train a model, calculate a welfare-risk score, forecast trajectory, establish personal/cohort/operational baselines, provide explainability, or generate interventions.

Primary output: `data/generated/person_day_features.csv`.

The output preserves optional wellness missingness, contains data-sufficiency indicators, and includes cumulative personal-history ingredients for later baseline work. All calculations are restricted to information available through the feature date.


## Phase 3 — Contextual baselines
Phase 3 produces model-ready contextual reference features but does not train or invoke a model.

The baseline layer provides three references: personal historical context, cohort context, and operational context. Personal statistics are strictly prior-day. Cohort and operational references are same-day, self-excluded contextual aggregates with minimum sample-size guards. Each reference exposes sufficiency/count metadata and safe deviations.

These outputs must not be interpreted as stress scores, risk scores, diagnoses, predictions, or intervention decisions. Phase 4 consumes the baseline-extended person-day table for predictive modeling. Phase 5 and later phases may add trajectory interpretation, uncertainty, explainability, and interventions.


## Phase 4 — Predictive Risk Modeling
Phase 4 implements the first predictive layer using the Phase 3 baseline-extended person-day table.

### Target
`future_high_perceived_stress_7d` is 1 when the same person's observed synthetic voluntary `perceived_stress_latest` reaches 4 or 5 on any observed day in T+1..T+7. If no future wellness observation exists in that horizon, the row is unlabeled for supervised training. The target is an observed synthetic self-report outcome, not clinical ground truth.

### Inputs
The model uses existing operational/context and Phase 3 baseline features. Wellness-derived features are excluded from model inputs. Missing operational numeric values are median-imputed within the training pipeline; categorical context is imputed and one-hot encoded.

### Model
The baseline model is deterministic scikit-learn logistic regression with class weighting and fixed `random_state=42`. It produces a probability in [0,1]. The prototype maps probability to `LOW` (<0.33), `MODERATE` (0.33–<0.66), or `ELEVATED` (>=0.66). These thresholds are prototype display conventions, not clinical thresholds.

### Temporal evaluation
Dates are split chronologically into 60% train, 20% validation, and 20% test dates among labeled rows. No future dates are used to train earlier dates.

### Phase 4 outputs
- saved serialized model artifact
- model metadata and feature list
- evaluation report
- person-day prediction output with `welfare_risk_probability` and `risk_level`

Explainability, uncertainty presentation, intervention simulation, optimization, and dashboard work remain outside Phase 4.


## Phase 4 evaluation
On the supplied 90,000-row Phase 3 dataset, the target construction produced 26,085 usable labeled prediction dates and excluded 63,915 dates without an observed future wellness report within the 7-day horizon. The chronological split was 15,662 train / 5,325 validation / 5,098 test rows. Validation ROC AUC was 0.74575; test ROC AUC was 0.76340; test average precision was 0.57910. These figures are synthetic-prototype evaluation metrics only and are not clinical validation.

## Phase 5 — Risk Decision Layer
Phase 5 wraps the Phase 4 Logistic Regression probability output with a validation-only calibration and operating-point layer. It does not retrain the Phase 4 model and does not create a clinical diagnosis.

### Calibration
Platt scaling is fitted using validation-set Phase 4 probabilities and observed synthetic future wellness targets. Test labels are not used to fit calibration. Calibration diagnostics include Brier score, ROC AUC, average precision, reliability bins, and expected calibration error.

### Operating point
Candidate thresholds 0.10 through 0.60 are evaluated on validation data. The selected threshold is the highest-validation-F1 candidate meeting the configured validation recall floor of 0.80; ties prefer higher precision and then the lower threshold. For the current dataset the locked threshold is 0.25. The old 0.50 Phase 4 operating point is retained only as an evaluation reference because its recall was low.

### Risk bands
- LOW: probability < 0.25
- MODERATE: 0.25 <= probability < 0.50
- HIGH: probability >= 0.50

Risk bands describe operational/welfare monitoring signals only. They are not diagnoses, stress labels, or predictions of a medical state.

### Explanations
Phase 5 exposes up to three contributing operational signals based on existing operational/baseline features. Wording is associative (for example, “contributing operational signals” or “factors associated with elevated predicted risk”) and never claims that an individual feature caused a wellness outcome. Raw wellness responses are excluded from explanations.

### Output
`data/generated/risk_decisions.csv` is the Phase 5 frontend-facing decision output. `data/generated/risk_predictions.csv` remains the Phase 4 source artifact and is not overwritten.



## Phase 6 — Welfare Intervention / Decision Support
Phase 6 consumes the Phase 5 calibrated probability/risk-band decision output and applies deterministic welfare-support policy. It does not retrain or alter the Phase 4 predictive model.

### Risk-to-action mapping
- LOW → `ROUTINE_MONITORING`
- MODERATE → context-sensitive `RECOVERY_SUPPORT`, `SUPERVISOR_WELFARE_REVIEW`, or `WELLNESS_CHECK_IN`
- HIGH → `PRIORITY_WELFARE_REVIEW` with human review required

### Rationale and safety
Recommendations use existing operational contributing signals and baseline/context features. Wording is non-causal and non-clinical. The output does not expose raw wellness responses and does not produce diagnosis, disciplinary action, or autonomous intervention.

### Cooldown
When the same person would receive the same action on the next consecutive day without a material probability increase or risk-band increase, the output becomes `CONTINUE_EXISTING_SUPPORT`. The cooldown is deterministic and configurable.

### Phase 7 handoff
Staffing, mandatory-role coverage, deployment requirements, operational readiness, and intervention feasibility are intentionally not implemented in Phase 6 and are delegated to Phase 7.

## Phase 7 boundary
Phase 7 does not train or alter predictive models. It consumes the Phase 5/6 decision outputs plus existing operational event data to determine operational feasibility. Feasibility is a rule-based operational state, not a risk score or medical classification.

## Phase 9 dashboard boundary

Phase 9 presents existing Phase 5 predicted welfare signals and downstream Phase 6/7 decisions. It does not retrain models, alter thresholds, expose raw wellness responses, or create new prediction targets.

## Phase 10 boundary
Phase 10 consumes the already-produced risk/intervention/feasibility outputs. It does not train, calibrate, retune, or modify any model. Workflow state is a human decision record, not a model output or risk score.


## Phase 13 — Product presentation boundary

Phase 13 is a presentation/integration layer over the existing model and decision artifacts. It does not retrain or retune predictive models, create new targets, or expose raw voluntary wellness responses. Model probability remains secondary technical detail; the primary user-facing hierarchy is signal → change → baseline/context → support → feasibility → human review.
