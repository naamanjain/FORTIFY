# FORTIFY Phase 1 — Generated Synthetic Operational World

All files in this directory are **synthetic prototype data** generated for FORTIFY Phase 1. They are not real government personnel records, not classified operational information, and not clinically validated data.

## Generation parameters

- Personnel: 500
- Simulation days per personnel: 180
- Start date: 2026-01-01
- Seed: 42
- Optional wellness personnel target: 0.35

## Scenario archetypes

Scenario archetypes are generator-internal controls used to create varied operational trajectories. They are **not clinical labels, ground truth stress labels, or model targets**, and no scenario column is written to the event datasets.

- STABLE: normal workload and recovery
- HIGH_LOAD: sustained higher operational workload
- RECOVERY_DEFICIT: repeated shorter recovery periods
- PROLONGED_DEPLOYMENT: longer deployment periods with reduced leave opportunities
- VOLATILE: irregular duty and schedule changes
- RECOVERY_AFTER_PEAK: temporary high load followed by easing recovery conditions

Generation-only scenario allocation: {'STABLE': 84, 'HIGH_LOAD': 84, 'RECOVERY_DEFICIT': 83, 'PROLONGED_DEPLOYMENT': 83, 'VOLATILE': 83, 'RECOVERY_AFTER_PEAK': 83}

## Output files

- `personnel.csv` — synthetic personnel master records
- `units.csv` — synthetic unit types and generator assumptions
- `duty_events.csv` — longitudinal duty events
- `recovery_events.csv` — daily rest/recovery events
- `leave_events.csv` — leave intervals
- `deployment_events.csv` — deployment intervals
- `training_events.csv` — training events
- `incident_events.csv` — synthetic operational incidents
- `wellness_events.csv` — sparse, optional voluntary self-report observations

Formal schemas are under `../schemas/`.

## Temporal behavior

Events are generated as sequences rather than independent random rows. Leave suppresses ordinary duty on affected dates; deployment status affects duty generation; prior duty duration and night duty influence subsequent recovery; training adds workload to the day; incidents create additional recovery requirements; and scenario controls vary these operational relationships over time.

## Limitations

This is a demonstration-oriented synthetic world. Unit characteristics, duty distributions, incident types, and wellness observations are synthetic assumptions intended to provide realistic-looking longitudinal relationships. They are not estimates of actual CRPF, Armed Forces, CAPF, police, or any other organization's operational distributions.

The `perceived_stress` field is an optional synthetic self-report and must not be interpreted as a clinical diagnosis. Missing wellness observations are expected and are not treated as evidence of elevated risk.

## Validation

Run from the repository root:

```bash
python scripts/validate_synthetic_data.py --output data/generated --personnel 500 --days 180
```

