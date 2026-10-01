# Product Specification

## Purpose
FORTIFY supports early identification and practical intervention for emerging operational welfare strain in uniformed personnel.

## Product loop
1. Observe longitudinal operational patterns.
2. Contextualize against personal, cohort, and operational baselines.
3. Forecast the direction of welfare-risk trajectory.
4. Explain contributing operational factors.
5. Simulate policy-approved interventions.
6. Apply staffing, role, duty, deployment, readiness, and mandatory-assignment constraints.
7. Rank feasible interventions for an authorized welfare decision-maker.
8. Track outcomes.

## Output vocabulary
- `risk_level`: LOW / MODERATE / ELEVATED
- `trajectory`: STABLE / RISING / FALLING
- `confidence`: numeric or categorical
- `data_sufficiency`: numeric or categorical
- `contributors`: human-readable contributing factors
- `recommended_interventions`: ranked actions

The system must say **"Elevated welfare-risk trajectory detected."**, not diagnose a mental illness.

## Hero feature
The intervention simulator is the hero feature in later phases. Candidate actions include reducing night duties, increasing recovery time, granting leave, redistributing workload, and temporary lower-intensity assignment. Simulation should estimate projected welfare-risk change, operational disruption, staffing/coverage impact, and recommendation suitability.

Demonstration values are synthetic and must never be described as clinically validated results.

## Implementation status (honesty note)

This spec is the original product intent; the completed prototype implements it with the following precise vocabulary and scope:

- Phase 4 model output exposes `risk_level` (`LOW` / `MODERATE` / `ELEVATED`) using fixed display bands (<0.33 / 0.33–<0.66 / >=0.66). Phase 5+ decision outputs expose the calibrated `risk_band` (`LOW` / `MODERATE` / `HIGH`) with bands derived from the validation-selected operating threshold (currently 0.45; bands <0.25 / 0.25–<0.50 / >=0.50). Both terms appear in artifacts; they are different layers of the same pipeline, not synonyms.
- The planned intervention **simulator** was implemented as a deterministic welfare-support policy (Phase 6: risk-band → action mapping with rationales and cooldown suppression) plus an operational feasibility/constraint layer (Phase 7). The prototype does **not** produce numeric projected-strain estimates for candidate actions; the illustrative simulation numbers in [DEMO_SCENARIO.md](DEMO_SCENARIO.md) are examples, not system outputs.
- `trajectory`, `confidence`, and `data_sufficiency` exist as engineered features and sufficiency indicators; the user-facing contract shipped in the prototype is the calibrated probability, risk band, contributing operational signals, recommendation, feasibility state, and human workflow record.
