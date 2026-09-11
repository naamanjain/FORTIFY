# FORTIFY — Data Specification

## Prototype rule
FORTIFY Phase 1 uses synthetic longitudinal operational data only. Real government personnel data is not required. The generated data models operational conditions and event histories; it does not contain clinical diagnoses or model target labels.

## Phase 1 generated entities

| Dataset | Primary identifier | Key fields |
|---|---|---|
| `personnel.csv` | `person_id` | `unit_id`, `role`, `deployment_type`, `service_years`, `joining_date`, `current_posting_start` |
| `units.csv` | `unit_id` | `unit_type`, operational probabilities/assumptions |
| `deployment_events.csv` | `deployment_event_id` | `person_id`, `deployment_type`, `start_date`, `end_date`, `intensity_level`, `location_type` |
| `duty_events.csv` | `duty_event_id` | `person_id`, `timestamp`, `date`, `duty_type`, `duration_hours`, `night_shift`, `intensity_level`, `deployment_id` |
| `recovery_events.csv` | `recovery_event_id` | `person_id`, `date`, `rest_duration_hours` |
| `leave_events.csv` | `leave_event_id` | `person_id`, `start_date`, `end_date`, `duration_days`, `leave_type`, `status` |
| `training_events.csv` | `training_event_id` | `person_id`, `date`, `duration_hours`, `training_type`, `intensity_level` |
| `incident_events.csv` | `incident_event_id` | `person_id`, `date`, `incident_type`, `intensity_level`, `recovery_requirement` |
| `wellness_events.csv` | `wellness_event_id` | `person_id`, `date`, five 1–5 optional self-report scores, `support_request` |

Formal JSON Schemas are stored under `data/schemas/`.

## Synthetic units
The generator creates 18 synthetic units: three each for FIELD, BORDER, HIGH_INTENSITY, URBAN, TRAINING, and LOGISTICS. Unit profiles affect event distributions only and are explicitly synthetic assumptions:

- FIELD — higher deployment intensity
- BORDER — higher night-duty probability
- HIGH_INTENSITY — higher incident/workload probability
- URBAN — more variable schedules
- TRAINING — higher scheduled training load
- LOGISTICS — different duty and support patterns

These are not exact real-world classifications.

## Roles
The generator uses: OPERATIONS, PATROL, LOGISTICS, COMMUNICATIONS, MEDICAL_SUPPORT, ADMINISTRATION, and TRAINING. Role affects event distributions only; no role is encoded as inherently more stressed.

## Longitudinal generation
Default configuration:

- 500 personnel
- 180 simulation days per person
- seed 42
- simulation start 2026-01-01
- target optional wellness coverage 35% of personnel

CLI parameters allow personnel count, horizon, seed, output directory, start date, and wellness coverage to be changed.

## Temporal relationships
Events are sequence-based rather than independently sampled. The generator models relationships including:

- deployment periods influencing duty patterns and incident probability;
- leave days suppressing ordinary duty;
- prior duty duration affecting subsequent recovery duration;
- night duty reducing subsequent recovery duration on average;
- repeated duty days contributing to shorter recovery;
- training contributing to same-day operational load;
- incidents creating additional recovery requirements;
- scenario controls changing workload/recovery patterns over time.

The Phase 1 generator therefore creates an operational event world suitable for later feature engineering without implementing that later phase itself.

## Scenario archetypes
Scenario types are generator-internal controls only and are never written into the generated event tables as ground-truth labels:

1. STABLE
2. HIGH_LOAD
3. RECOVERY_DEFICIT
4. PROLONGED_DEPLOYMENT
5. VOLATILE
6. RECOVERY_AFTER_PEAK

With the default seed and 500 personnel, the allocation is 84/84/83/83/83/83 respectively. This is a balanced generation control, not a clinical prevalence claim.

## Optional wellness data
Wellness events are sparse, supplementary, and voluntary in the synthetic world. Each score is an integer from 1 to 5. Missing wellness observations are normal and must not be interpreted as elevated risk. Daily reporting is not required for the operational world to exist.

## Deliberate exclusions
The Phase 1 datasets do not contain `stress_score`, `mental_health_score`, depression/anxiety labels, clinical diagnoses, biometric identifiers, or a scenario column intended for ML ground truth. `perceived_stress` exists only as an optional synthetic self-report field and is not a diagnosis.

## Validation requirements implemented
`python scripts/validate_synthetic_data.py` checks file presence, unique IDs, personnel foreign keys, deployment references, valid dates, start/end ordering, duration bounds, categorical values, personnel coverage, night duty representation, duty variety, operational variability, sparse wellness coverage, and forbidden clinical/scenario output fields.

## Limitations
All distributions, thresholds, unit characteristics, event types, and optional wellness responses are synthetic assumptions for prototype simulation. The data is not real CRPF, CAPF, police, Armed Forces, government, or classified operational data. It is not clinically validated and must not be presented as clinical evidence or measured operational prevalence.

## Phase 2 feature output
The Phase 2 feature engine consumes the Phase 1 event tables without changing them and emits `data/generated/person_day_features.csv` at one row per `person_id × date`.

Feature groups include workload, duty density, recovery, leave, deployment, incident exposure, workload change, optional voluntary wellness, data sufficiency, personal-history ingredients, and non-sensitive context. The machine-readable catalog is `data/schemas/feature_schema.json`; the human-readable catalog is `data/generated/FEATURE_CATALOG.md`.

### Phase 2 window semantics
7-day features use exactly T-6 through T. 30-day features use exactly T-29 through T. 90-day features use exactly T-89 through T. Previous-window comparisons use the immediately preceding non-overlapping window. Zero previous values produce null relative change instead of division-by-zero.

### Leakage policy
Every feature at date T uses only observations available on or before T. The implementation keeps this explicit by constructing the complete person-day grid first and then applying grouped rolling/expanding calculations over the already time-ordered rows. An explicit regression test adds a future duty event and verifies that the feature vector at an earlier T is unchanged.

### Operational assumptions
Short rest is defined as less than 6.0 hours; recovery deficit is based on an 8.0-hour operational target. High intensity is level 4 or higher, and emergency duty is `duty_type == EMERGENCY`. These are configurable prototype simulation assumptions, not clinical thresholds.

### Leave limitation
Phase 1's `status` field is not sufficient to infer “pending/delayed” leave under the Phase 2 rules. `pending_or_delayed_leave_indicator` therefore remains nullable rather than inventing a rule.

### Wellness limitation
Voluntary wellness values are never imputed to poor values or forward-filled. Same-day `*_latest` fields represent an observation on that date; absence remains missing. Availability counts describe reporting availability only.


## Phase 3 baseline output
Phase 3 extends the existing Phase 2 person-day representation; it does not create a separate prediction table.

### Personal baseline semantics
For each metric, historical mean, median, sample standard deviation, valid observation count, sufficiency flag, absolute deviation, and relative deviation are calculated from strictly prior person-days only. The configured minimum is 14 valid prior observations. No baseline is fabricated for insufficient history.

### Cohort definition
Cohort = `role + deployment_type`. This avoids very small unit-specific groups while using only attributes already present in the Phase 1/2 data model. Same-day comparisons exclude the current person and require at least 10 other personnel by default. Small cohorts remain missing.

### Operational context definition
Operational context = `unit_type + date`. Same-day unit-type references exclude the current person and require at least 10 comparison personnel by default. Operational descriptive context also includes unit-type person count, median `duty_hours_7d`, median `duty_density_30d`, and date-level person coverage.

### Temporal policy
No date after T can influence any Phase 3 baseline or comparison at T. Personal references are strictly prior-day; cohort and operational references use only rows on T.

### Missingness
Insufficient history/cohort/context remains null and is represented with explicit count/sufficiency columns. Near-zero denominators produce null relative deviations rather than infinities. Missing Phase 2 metric values are not converted to zero.


## Phase 4 model input relationship
The Phase 4 model consumes the existing Phase 3 person-day table at the same `person_id × date` grain. No new prediction table replaces the person-day representation.

The supervised target is constructed separately from `wellness_events.csv`: for prediction date T, the first voluntary wellness observation strictly after T and within seven days is used. A positive target means `perceived_stress >= 4`. This target is a synthetic observed self-report signal and is not a clinical label.

Wellness-derived feature columns are excluded from model inputs. Missing wellness observations are therefore not used as a predictive signal.

## Phase 7 feasibility output
`intervention_feasibility.csv` preserves one row per Phase 6 person/date recommendation and adds operational feasibility state, constraint flags, feasibility rationale, optional timing adjustment, human-review requirement, and policy provenance. It contains no raw wellness responses and no risk/stress/medical/disciplinary score.

## Phase 8 security treatment

Phase 8 does not change the Phase 1–7 operational schemas. It treats existing operational outputs as protected application data and provides security controls for how identifiers and security-relevant metadata are handled.

Security-facing representations must avoid exposing raw voluntary wellness values. Pseudonymous identifiers are suitable for analytics-facing contexts; identity mapping secrets remain external to the analytics layer. No new clinical or personnel-performance fields are introduced.
