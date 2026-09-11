# FORTIFY Final Demonstration Runbook

## Purpose

This runbook is the Phase 12 operator guide for demonstrating the completed FORTIFY prototype. It uses only existing synthetic Phase 1–11 artifacts and the deterministic Phase 12 preparation package.

## Prepared hero case

- Person: `P-0002`
- Demonstration date: `2026-02-25`
- Ending operational/welfare signal: `HIGH`
- Recommended action: `PRIORITY_WELFARE_REVIEW`
- Feasibility: `CONSTRAINED`
- Workflow starting state: `NEW`
- Timeline: 22 person-day records

## Demonstration sequence

### 1. Observe

Open the Phase 9 dashboard and show the aggregate welfare overview. Then open the hero case.

Use the prepared 22-day timeline to show that the demonstration is longitudinal rather than a single isolated observation.

### 2. Contextualize

Show the current model probability/risk band and the existing non-clinical operational contributing signals. Do not display raw wellness responses.

### 3. Explain

Use the operational signals already produced by Phase 5, such as elevated duty hours or increased night-shift exposure where present. Describe them as contributing/associated operational signals, not causes.

### 4. Recommend

Show the Phase 6 welfare-support recommendation: `PRIORITY_WELFARE_REVIEW`.

### 5. Constrain

Show the Phase 7 feasibility result and existing constraint flags. Explain that the intervention is constrained by current operational conditions and therefore requires human coordination.

### 6. Human review

Use the Phase 10 workflow panel. The prepared workflow item starts in `NEW`. Perform only supported human transitions during the live demonstration. Do not claim that the system automatically completed an intervention.

### 7. Audit

After a supported transition, show the workflow history/audit indicator. The audit trail contains workflow/reference metadata and does not contain raw voluntary wellness responses.

## Safety language

Use:

> "FORTIFY is an operational/welfare decision-support prototype. The signals are probabilistic and synthetic. Human welfare personnel remain responsible for decisions."

Do not use language that presents the system as diagnosing a medical or psychiatric condition, assigning blame, or taking adverse personnel action.

## Rehearsal checklist

- Backend starts successfully.
- Frontend starts successfully.
- Dashboard overview loads.
- Hero case can be opened.
- Feasibility information is visible.
- Workflow item begins in `NEW`.
- Human transition controls are available to the authorized role/purpose.
- Audit history is visible after a transition.
- Prepared artifacts exist under `artifacts/phase12/`.
- No raw wellness responses are shown.
- Synthetic-data disclaimer is stated during the demonstration.

## Phase boundary

Phase 12 is final demonstration preparation. No new prediction, intervention, optimization, authentication, or product capability is introduced here.
