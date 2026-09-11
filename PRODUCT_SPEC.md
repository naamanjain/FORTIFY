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
