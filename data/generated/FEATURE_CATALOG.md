# FORTIFY Phase 2 — Feature Catalog

Feature count: **{len(features)}**.

Output grain: one row per `person_id × date`. A 7-day window is exactly T-6 through T; a 30-day window is T-29 through T; a 90-day window is T-89 through T. Event-derived features use only information available on or before T.

## Context

- `unit_id` — Operational context value: unit_id.
- `role` — Operational context value: role.
- `deployment_type` — Operational context value: deployment_type.
- `service_years` — Synthetic years of service.
- `unit_type` — Operational context value: unit_type.

## Workload

- `duty_hours_1d` — Operational feature `duty_hours_1d`.
- `duty_hours_7d` — Operational feature `duty_hours_7d`.
- `duty_days_7d` — Operational feature `duty_days_7d`.
- `night_shifts_7d` — Operational feature `night_shifts_7d`.
- `duty_hours_30d` — Operational feature `duty_hours_30d`.
- `duty_days_30d` — Operational feature `duty_days_30d`.
- `night_shifts_30d` — Operational feature `night_shifts_30d`.
- `duty_hours_90d` — Operational feature `duty_hours_90d`.
- `duty_days_90d` — Operational feature `duty_days_90d`.
- `night_shifts_90d` — Operational feature `night_shifts_90d`.
- `high_intensity_duties_7d` — Operational feature `high_intensity_duties_7d`.
- `emergency_duties_7d` — Operational feature `emergency_duties_7d`.
- `training_hours_7d` — Operational feature `training_hours_7d`.
- `high_intensity_duties_30d` — Operational feature `high_intensity_duties_30d`.
- `emergency_duties_30d` — Operational feature `emergency_duties_30d`.
- `training_hours_30d` — Operational feature `training_hours_30d`.
- `duty_hours_personal_history_mean` — Cumulative person-specific historical statistic for later baseline work.
- `duty_hours_personal_history_std` — Cumulative person-specific historical statistic for later baseline work.

## Duty density

- `duty_density_7d` — Operational feature `duty_density_7d`.
- `duty_density_30d` — Operational feature `duty_density_30d`.
- `night_shift_ratio_30d` — Operational feature `night_shift_ratio_30d`.
- `duty_gap_mean_7d` — Operational feature `duty_gap_mean_7d`.
- `duty_gap_mean_30d` — Operational feature `duty_gap_mean_30d`.
- `consecutive_duty_days` — Operational feature `consecutive_duty_days`.
- `longest_duty_streak_30d` — Operational feature `longest_duty_streak_30d`.

## Recovery

- `avg_rest_7d` — Operational feature `avg_rest_7d`.
- `min_rest_7d` — Operational feature `min_rest_7d`.
- `short_rest_count_7d` — Operational feature `short_rest_count_7d`.
- `recovery_deficit_7d` — Operational feature `recovery_deficit_7d`.
- `avg_rest_30d` — Operational feature `avg_rest_30d`.
- `min_rest_30d` — Operational feature `min_rest_30d`.
- `short_rest_count_30d` — Operational feature `short_rest_count_30d`.
- `recovery_deficit_30d` — Operational feature `recovery_deficit_30d`.
- `recovery_variability_30d` — Operational feature `recovery_variability_30d`.

## Leave

- `days_since_last_leave` — Operational feature `days_since_last_leave`.
- `leave_days_30d` — Operational feature `leave_days_30d`.
- `leave_days_90d` — Operational feature `leave_days_90d`.
- `leave_count_90d` — Operational feature `leave_count_90d`.
- `leave_gap_90d` — Operational feature `leave_gap_90d`.
- `pending_or_delayed_leave_indicator` — Nullable leave-status indicator; not inferred because Phase 1 status lacks sufficient semantics.
- `leave_data_available` — Input dataset availability indicator.

## Deployment

- `current_deployment_days` — Operational feature `current_deployment_days`.
- `current_deployment_intensity` — Operational feature `current_deployment_intensity`.
- `days_since_deployment_start` — Operational feature `days_since_deployment_start`.
- `days_since_deployment_end` — Operational feature `days_since_deployment_end`.
- `deployment_days_30d` — Operational feature `deployment_days_30d`.
- `deployment_days_90d` — Operational feature `deployment_days_90d`.
- `deployment_count_180d` — Operational feature `deployment_count_180d`.

## Incident exposure

- `incident_count_7d` — Operational feature `incident_count_7d`.
- `incident_count_30d` — Operational feature `incident_count_30d`.
- `incident_count_90d` — Operational feature `incident_count_90d`.
- `high_intensity_incident_count_30d` — Operational feature `high_intensity_incident_count_30d`.
- `incident_recovery_requirement_30d` — Operational feature `incident_recovery_requirement_30d`.
- `incident_density_30d` — Operational feature `incident_density_30d`.
- `incident_count_30d_vs_previous_30d_abs` — Absolute operational change versus the previous non-overlapping window.
- `incident_count_30d_vs_previous_30d_relative` — Relative operational change versus the previous non-overlapping window.

## Workload change

- `duty_hours_7d_vs_previous_7d_abs` — Absolute operational change versus the previous non-overlapping window.
- `duty_hours_7d_vs_previous_7d_relative` — Relative operational change versus the previous non-overlapping window.
- `duty_hours_30d_vs_previous_30d_abs` — Absolute operational change versus the previous non-overlapping window.
- `duty_hours_30d_vs_previous_30d_relative` — Relative operational change versus the previous non-overlapping window.
- `night_shifts_30d_vs_previous_30d_abs` — Absolute operational change versus the previous non-overlapping window.
- `night_shifts_30d_vs_previous_30d_relative` — Relative operational change versus the previous non-overlapping window.
- `training_hours_30d_vs_previous_30d_abs` — Absolute operational change versus the previous non-overlapping window.
- `training_hours_30d_vs_previous_30d_relative` — Relative operational change versus the previous non-overlapping window.
- `incident_count_30d_vs_previous_30d_abs` — Absolute operational change versus the previous non-overlapping window.
- `incident_count_30d_vs_previous_30d_relative` — Relative operational change versus the previous non-overlapping window.
- `rest_7d_vs_previous_7d_abs` — Absolute operational change versus the previous non-overlapping window.
- `rest_7d_vs_previous_7d_relative` — Relative operational change versus the previous non-overlapping window.

## Voluntary wellness

- `mood_latest` — Voluntary wellness-derived feature `mood_latest`.
- `mood_7d_mean` — Voluntary wellness-derived feature `mood_7d_mean`.
- `mood_30d_mean` — Voluntary wellness-derived feature `mood_30d_mean`.
- `mood_change_7d` — Voluntary wellness-derived feature `mood_change_7d`.
- `mood_change_30d` — Voluntary wellness-derived feature `mood_change_30d`.
- `energy_latest` — Voluntary wellness-derived feature `energy_latest`.
- `energy_7d_mean` — Voluntary wellness-derived feature `energy_7d_mean`.
- `energy_30d_mean` — Voluntary wellness-derived feature `energy_30d_mean`.
- `sleep_quality_latest` — Voluntary wellness-derived feature `sleep_quality_latest`.
- `sleep_quality_7d_mean` — Voluntary wellness-derived feature `sleep_quality_7d_mean`.
- `sleep_quality_30d_mean` — Voluntary wellness-derived feature `sleep_quality_30d_mean`.
- `sleep_quality_change_7d` — Voluntary wellness-derived feature `sleep_quality_change_7d`.
- `sleep_quality_change_30d` — Voluntary wellness-derived feature `sleep_quality_change_30d`.
- `perceived_stress_latest` — Voluntary wellness-derived feature `perceived_stress_latest`.
- `perceived_stress_7d_mean` — Voluntary wellness-derived feature `perceived_stress_7d_mean`.
- `perceived_stress_30d_mean` — Voluntary wellness-derived feature `perceived_stress_30d_mean`.
- `perceived_stress_change_7d` — Voluntary wellness-derived feature `perceived_stress_change_7d`.
- `perceived_stress_change_30d` — Voluntary wellness-derived feature `perceived_stress_change_30d`.
- `workload_manageability_latest` — Voluntary wellness-derived feature `workload_manageability_latest`.
- `workload_manageability_7d_mean` — Voluntary wellness-derived feature `workload_manageability_7d_mean`.
- `workload_manageability_30d_mean` — Voluntary wellness-derived feature `workload_manageability_30d_mean`.
- `support_request_recent` — Recent voluntary support-request indicator.

## Data sufficiency

- `days_observed` — Simulation days observed through T.
- `wellness_available_today` — Whether a voluntary wellness observation exists on T.
- `wellness_days_7d` — Number of person-days containing a voluntary wellness observation.
- `wellness_days_30d` — Number of person-days containing a voluntary wellness observation.
- `leave_data_available` — Input dataset availability indicator.
- `deployment_data_available` — Input dataset availability indicator.
- `duty_data_days_30d` — Days with at least one duty event in the 30-day window.
- `feature_completeness_ratio` — Fraction of required operational feature fields that are non-null.

## Personal-history ingredients

- `duty_hours_personal_history_mean` — Cumulative person-specific historical statistic for later baseline work.
- `duty_hours_personal_history_std` — Cumulative person-specific historical statistic for later baseline work.
- `night_shift_personal_history_mean` — Cumulative person-specific historical statistic for later baseline work.
- `rest_personal_history_mean` — Cumulative person-specific historical statistic for later baseline work.
- `personal_history_length` — Cumulative person-specific historical statistic for later baseline work.
- `personal_history_std_available` — Cumulative person-specific historical statistic for later baseline work.

## Configurable operational assumptions

- Short rest threshold: **6.0 hours**.
- Recovery target: **8.0 hours**.
- High intensity: intensity level **4 or higher**.
- Emergency duty: `duty_type == EMERGENCY`.
- These are prototype simulation assumptions, not clinical thresholds; they are configurable in `FeatureConfig`.

## Leave-status limitation

`pending_or_delayed_leave_indicator` remains nullable because Phase 1 `status` alone is not enough to establish “delayed” leave.

## Optional wellness

Missing wellness remains missing. No poor-value imputation or forward-fill is used. Availability counters indicate data availability, not welfare risk.