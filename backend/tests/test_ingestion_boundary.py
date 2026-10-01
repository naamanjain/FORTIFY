"""Ingestion boundary tests: no external data reaches the model unvalidated."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.ingestion.boundary import validate_batch


def valid_duty_batch(rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame([
        {"duty_event_id": f"D-{i}", "person_id": "P-0001",
         "date": "2026-06-28", "duration_hours": 8.0,
         "duty_type": "DAY", "night_shift": 0, "intensity_level": 3}
        for i in range(rows)
    ])


def test_valid_batch_is_accepted_with_provenance() -> None:
    result = validate_batch("duty_events", valid_duty_batch(),
                            source_system="hr-roster", batch_id="b-1",
                            today=date(2026, 6, 30))
    assert result.accepted
    assert result.rows == 3
    assert result.provenance["source_system"] == "hr-roster"
    assert result.provenance["batch_id"] == "b-1"


def test_schema_violations_reject_the_batch() -> None:
    frame = valid_duty_batch().drop(columns=["duration_hours"])
    result = validate_batch("duty_events", frame, source_system="s", batch_id="b",
                            today=date(2026, 6, 30))
    assert not result.accepted
    assert any(r.check == "schema" for r in result.rejections)


def test_unknown_columns_are_rejected_not_ignored() -> None:
    frame = valid_duty_batch()
    frame["internal_salary_band"] = "N/A"
    result = validate_batch("duty_events", frame, source_system="s", batch_id="b",
                            today=date(2026, 6, 30))
    assert not result.accepted
    assert any("Unknown columns" in r.message for r in result.rejections)


def test_bad_identifiers_reject() -> None:
    frame = valid_duty_batch()
    frame.loc[0, "person_id"] = "person 1"
    result = validate_batch("duty_events", frame, source_system="s", batch_id="b",
                            today=date(2026, 6, 30))
    assert not result.accepted
    assert any(r.check == "identifier_format" for r in result.rejections)


def test_future_dates_reject() -> None:
    frame = valid_duty_batch()
    frame["date"] = "2027-01-01"
    result = validate_batch("duty_events", frame, source_system="s", batch_id="b",
                            today=date(2026, 6, 30))
    assert not result.accepted
    assert any(r.check == "future_dates" for r in result.rejections)


def test_duplicates_reject() -> None:
    frame = valid_duty_batch()
    frame.loc[1, "duty_event_id"] = "D-0"
    result = validate_batch("duty_events", frame, source_system="s", batch_id="b",
                            today=date(2026, 6, 30))
    assert not result.accepted
    assert any(r.check == "duplicate_keys" for r in result.rejections)


def test_impossible_values_reject() -> None:
    frame = valid_duty_batch()
    frame.loc[0, "duration_hours"] = 40.0
    result = validate_batch("duty_events", frame, source_system="s", batch_id="b",
                            today=date(2026, 6, 30))
    assert not result.accepted
    assert any(r.check == "impossible_values" for r in result.rejections)


def test_stale_export_rejects_against_known_latest() -> None:
    frame = valid_duty_batch()
    frame["date"] = "2026-01-01"
    result = validate_batch("duty_events", frame, source_system="s", batch_id="b",
                            known_latest_date=date(2026, 6, 29),
                            today=date(2026, 6, 30))
    assert not result.accepted
    assert any(r.check == "stale_batch" for r in result.rejections)


def test_unknown_dataset_rejects() -> None:
    result = validate_batch("classified_ops", valid_duty_batch(),
                            source_system="s", batch_id="b")
    assert not result.accepted
    assert any(r.check == "unknown_dataset" for r in result.rejections)
