"""Production data ingestion boundary.

External departmental systems (HR, duty roster, incident reporting) must not
be able to feed arbitrary data into FORTIFY. Every external record passes
through this module, which validates:

* **schema** - exactly the expected columns are present and typed;
* **identifiers** - person/unit identifiers match the deployed format;
* **timestamps** - ISO dates, no future dates, no pre-history dates;
* **duplicates** - primary keys are unique within the payload;
* **missingness** - required fields are present; optional sparseness is
  distinguished from faults (see ``app.ml.data_quality.NULLABLE_BY_DOMAIN``);
* **impossible values** - ranges per field (a rest record of 40 hours is a
  fault, not data);
* **freshness** - the payload's latest event must be within ``max_age_days``
  of the newest record already known, so a stale export cannot silently
  replace a current one;
* **provenance** - every accepted batch records the source system, batch id,
  and receipt time.

The boundary is validation-only: it never writes to the model's feature
store. Accepted batches are staged and the deterministic pipeline remains the
only path from raw records to features and scores - external data cannot
short-circuit the leakage-safe feature construction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

PERSON_ID_PATTERN = re.compile(r"^P-\d{3,}$")
UNIT_ID_PATTERN = re.compile(r"^U-\d{2,3}$")

# Field ranges copied from the data-quality expectations so ingestion and the
# pipeline agree on what "impossible" means.
FIELD_RANGES: dict[str, tuple[float | None, float | None]] = {
    "duration_hours": (0.0, 24.0),
    "rest_duration_hours": (0.0, 24.0),
    "recovery_requirement": (0.0, 24.0),
    "intensity_level": (1.0, 5.0),
    "mood_score": (1.0, 5.0),
    "energy_score": (1.0, 5.0),
    "sleep_quality": (1.0, 5.0),
    "perceived_stress": (1.0, 5.0),
    "workload_manageability": (1.0, 5.0),
    "night_shift": (0.0, 1.0),
}

DATASET_SCHEMAS: dict[str, dict[str, set[str]]] = {
    "duty_events": {"required": {"duty_event_id", "person_id", "date", "duration_hours"},
                    "optional": {"timestamp", "duty_type", "night_shift", "intensity_level", "deployment_id"}},
    "recovery_events": {"required": {"recovery_event_id", "person_id", "date", "rest_duration_hours"},
                        "optional": set()},
    "incident_events": {"required": {"incident_event_id", "person_id", "date", "intensity_level"},
                        "optional": {"incident_type", "recovery_requirement"}},
    "training_events": {"required": {"training_event_id", "person_id", "date"},
                        "optional": {"duration_hours", "training_type", "intensity_level"}},
    "wellness_events": {"required": {"wellness_event_id", "person_id", "date"},
                        "optional": {"mood_score", "energy_score", "sleep_quality",
                                     "perceived_stress", "workload_manageability", "support_request"}},
    "leave_events": {"required": {"leave_event_id", "person_id", "start_date", "end_date"},
                     "optional": {"leave_type", "status"}},
    "deployment_events": {"required": {"deployment_event_id", "person_id", "start_date", "end_date"},
                          "optional": {"intensity_level", "location_type"}},
}


@dataclass
class Rejection:
    dataset: str
    check: str
    message: str
    count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "check": self.check,
                "message": self.message, "count": self.count}


@dataclass
class IngestionResult:
    dataset: str
    accepted: bool
    rows: int = 0
    rejections: list[Rejection] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "accepted": self.accepted,
            "rows": self.rows,
            "rejections": [r.as_dict() for r in self.rejections],
            "provenance": self.provenance,
        }


def _reject(result: IngestionResult, check: str, message: str, count: int = 0) -> None:
    result.rejections.append(Rejection(result.dataset, check, message, count))
    result.accepted = False


def validate_batch(
    dataset: str,
    frame: pd.DataFrame,
    *,
    source_system: str,
    batch_id: str,
    known_latest_date: date | None = None,
    max_age_days: int = 14,
    today: date | None = None,
) -> IngestionResult:
    """Validate one external batch against the dataset schema.

    Returns an :class:`IngestionResult`; never raises. A batch with any
    rejection is not accepted - partial ingestion of unvalidated welfare data
    is worse than none.
    """
    result = IngestionResult(
        dataset=dataset,
        accepted=True,
        provenance={
            "source_system": source_system,
            "batch_id": batch_id,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "row_count": int(len(frame)),
        },
    )

    schema = DATASET_SCHEMAS.get(dataset)
    if schema is None:
        _reject(result, "unknown_dataset", f"Dataset '{dataset}' is not an ingestable source.")
        return result

    today = today or date.today()

    # Schema: required columns present, no unknown columns.
    missing = sorted(schema["required"] - set(frame.columns))
    if missing:
        _reject(result, "schema", f"Missing required columns: {missing}")
    unknown = sorted(set(frame.columns) - schema["required"] - schema["optional"])
    if unknown:
        _reject(result, "schema", f"Unknown columns not accepted: {unknown}")
    if result.rejections:
        return result

    result.rows = int(len(frame))
    if frame.empty:
        _reject(result, "empty_batch", "Batch contains no rows.")
        return result

    # Identifiers.
    person_ids = frame["person_id"].astype(str)
    bad_ids = int((~person_ids.str.match(PERSON_ID_PATTERN)).sum())
    if bad_ids:
        _reject(result, "identifier_format", f"{bad_ids} person_id values do not match the deployed identifier format.", bad_ids)

    # Timestamps: parseable, not in the future, not before 2000 (catches unit errors).
    date_columns = [c for c in ("date", "start_date", "end_date") if c in frame.columns]
    parsed: dict[str, pd.Series] = {}
    for column in date_columns:
        values = pd.to_datetime(frame[column], errors="coerce")
        parsed[column] = values
        unparseable = int((values.isna() & frame[column].notna()).sum())
        if unparseable:
            _reject(result, "invalid_dates", f"Column '{column}' has {unparseable} unparseable dates.", unparseable)
        future = int((values > pd.Timestamp(today)).sum())
        if future:
            _reject(result, "future_dates", f"Column '{column}' has {future} dates in the future.", future)
        ancient = int((values < pd.Timestamp("2000-01-01")).sum())
        if ancient:
            _reject(result, "implausible_dates", f"Column '{column}' has {ancient} dates before 2000.", ancient)

    # Interval sanity.
    if "start_date" in parsed and "end_date" in parsed:
        inverted = int((parsed["end_date"] < parsed["start_date"]).sum())
        if inverted:
            _reject(result, "inverted_interval", f"{inverted} rows have end before start.", inverted)

    # Duplicates on the primary key.
    key_column = next((c for c in frame.columns if c.endswith("_event_id")), None)
    if key_column:
        duplicates = int(frame[key_column].duplicated().sum())
        if duplicates:
            _reject(result, "duplicate_keys", f"{duplicates} duplicate {key_column} values in the batch.", duplicates)

    # Missingness: required fields must be present (optional sparseness is fine).
    for column in sorted(schema["required"]):
        missing_values = int(frame[column].isna().sum())
        if missing_values:
            _reject(result, "missing_required", f"Required column '{column}' has {missing_values} missing values.", missing_values)

    # Impossible values.
    for column, (low, high) in FIELD_RANGES.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        bad = int((values.lt(low) | values.gt(high)).sum())
        if bad:
            _reject(result, "impossible_values",
                    f"Column '{column}' has {bad} values outside [{low}, {high}].", bad)

    # Freshness: a stale export must not silently replace current data.
    all_dates = [v.dropna().max() for v in parsed.values()] if parsed else []
    if all_dates:
        latest = max(all_dates).date()
        result.provenance["latest_event_date"] = latest.isoformat()
        if known_latest_date is not None and (known_latest_date - latest).days > max_age_days:
            _reject(result, "stale_batch",
                    f"Batch's latest event ({latest}) is more than {max_age_days} days "
                    f"older than the known latest ({known_latest_date}); a stale export "
                    "must not replace current data.")

    return result
