"""Ingestion API tests: opt-in, infrastructure-gated, validation-only.

Every test that reaches the ingest route isolates its writes under ``tmp_path``
(staging plus a private audit log), so the suite leaves no probe artifacts in
the repository runtime directories.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.api.routes.ingestion as ing
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def staging(tmp_path, monkeypatch):
    """Enable ingestion and point every write at this test's tmp_path."""
    monkeypatch.setenv("FORTIFY_ENABLE_INGEST", "1")
    monkeypatch.setattr(ing, "STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(ing, "AUDIT_PATH", tmp_path / "audit.jsonl")
    return tmp_path / "staging"


INFRA = {"X-Fortify-Role": "SYSTEM_ADMINISTRATOR", "X-Fortify-Purpose": "INFRASTRUCTURE_ADMIN"}
WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}

CSV = (
    "duty_event_id,person_id,date,duration_hours,duty_type,night_shift,intensity_level\n"
    "D-1,P-0001,2026-06-28,8.0,DAY,0,3\n"
    "D-2,P-0002,2026-06-28,9.5,NIGHT,1,4\n"
)


def _post(client: TestClient, *, dataset: str = "duty_events", content: str = CSV,
          batch_id: str = "b1", source: str = "hr-roster",
          headers: dict[str, str] = INFRA, schema_version: int | None = None):
    data = {"source_system": source, "batch_id": batch_id}
    if schema_version is not None:
        data["schema_version"] = str(schema_version)
    return client.post(
        f"/api/ingest/{dataset}",
        headers=headers,
        files={"file": ("batch.csv", content.encode())},
        data=data,
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _expected_runtime_file(relative: str) -> bool:
    # The audit chain's log, anchor, key and lock all share this prefix.
    return relative.startswith("staging/") or relative.startswith("audit.jsonl")


def test_ingestion_is_invisible_when_disabled(client, monkeypatch):
    """EXPECTED: 404 - the surface does not exist by default."""
    monkeypatch.delenv("FORTIFY_ENABLE_INGEST", raising=False)
    r = _post(client, batch_id="b1")
    assert r.status_code == 404
    # The gate is a router dependency: it must answer before field/body
    # validation, including for a malformed multipart payload.
    malformed = client.post(
        "/api/ingest/duty_events",
        headers={**INFRA, "Content-Type": "multipart/form-data; boundary=x"},
        content=b"--x\r\nbad",
    )
    assert malformed.status_code == 404
    assert malformed.json()["detail"] == "Ingestion is not enabled on this deployment."


def test_ingestion_requires_infrastructure_purpose(client, staging):
    """EXPECTED: welfare purpose cannot ingest even when enabled."""
    r = _post(client, headers=WELFARE)
    assert r.status_code == 403
    assert not staging.exists()


def test_valid_batch_is_accepted_and_staged(client, staging):
    """EXPECTED: accepted batch is staged under a server-generated name."""
    r = _post(client, batch_id="b-2026-10-02")
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["provenance"]["source_system"] == "hr-roster"
    assert body["provenance"]["batch_id"] == "b-2026-10-02"
    assert body["provenance"]["validation_status"] == "ACCEPTED"

    ingest_id = body["ingest_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", ingest_id)
    assert body["provenance"]["ingest_id"] == ingest_id

    staged = staging / "duty_events" / f"staged-{ingest_id}.csv"
    report = staging / "duty_events" / f"batch-{ingest_id}.json"
    assert staged.exists()
    assert report.exists()
    # The external id is metadata only - it never shapes a filename.
    assert "b-2026-10-02" not in staged.name
    assert "b-2026-10-02" not in report.name

    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["accepted"] is True
    assert record["provenance"]["batch_id"] == "b-2026-10-02"


def test_invalid_batch_is_rejected_in_full(client, staging):
    """EXPECTED: impossible values reject the WHOLE batch; nothing staged."""
    bad = CSV.replace("8.0", "40.0")
    r = _post(client, content=bad, batch_id="b-bad")
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert any(rj["check"] == "impossible_values" for rj in body["rejections"])
    assert not list(staging.rglob("staged-*.csv"))


def test_rejected_batch_report_uses_server_generated_name(client, staging):
    """EXPECTED: rejection reports are written, but never under the raw id."""
    bad = CSV.replace("8.0", "40.0")
    r = _post(client, content=bad, batch_id="../../outside")
    # A traversal-shaped batch id is refused before validation.
    assert r.status_code == 422
    assert not staging.exists()

    r = _post(client, content=bad, batch_id="b-bad")
    body = r.json()
    ingest_id = body["ingest_id"]
    report = staging / "duty_events" / f"batch-{ingest_id}.json"
    assert report.exists()
    assert "b-bad" not in report.name
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["accepted"] is False
    assert record["provenance"]["batch_id"] == "b-bad"
    assert not list(staging.rglob("staged-*.csv"))


def test_schema_version_mismatch_rejects(client, staging):
    """EXPECTED: a batch declaring a different schema version is refused."""
    r = _post(client, batch_id="b2", schema_version=2)
    body = r.json()
    assert body["accepted"] is False
    assert any(rj["check"] == "schema_version_mismatch" for rj in body["rejections"])
    assert not list(staging.rglob("staged-*.csv"))


def test_duplicate_batch_is_conflict_and_never_overwrites(client, staging):
    """EXPECTED: retrying the same (source_system, batch_id) is a 409."""
    first = _post(client, batch_id="dup-1")
    assert first.status_code == 200 and first.json()["accepted"] is True

    second = _post(client, batch_id="dup-1")
    assert second.status_code == 409

    staged = list(staging.rglob("staged-*.csv"))
    reports = list(staging.rglob("batch-*.json"))
    assert len(staged) == 1
    assert len(reports) == 1


def test_same_batch_id_from_another_source_is_distinct(client, staging):
    """EXPECTED: the idempotency key includes the source system."""
    assert _post(client, batch_id="shared-1", source="hr-roster").status_code == 200
    assert _post(client, batch_id="shared-1", source="duty-system").status_code == 200
    assert len(list(staging.rglob("staged-*.csv"))) == 2


@pytest.mark.parametrize("batch_id", [
    "../escape", "../../escape", "..\\..\\escape", "/tmp/escape",
    "C:\\Windows\\escape", "nested/id", ".", "..", "", "batch id", "a" * 129,
])
def test_batch_id_cannot_shape_a_path(client, staging, tmp_path, batch_id):
    """EXPECTED: invalid ids are 422 and create nothing on disk."""
    before = _tree(tmp_path)
    r = _post(client, batch_id=batch_id)
    assert r.status_code == 422
    after = _tree(tmp_path)
    new = set(after) - set(before)
    assert all(_expected_runtime_file(path) for path in new), new
    assert not staging.exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("dataset", [
    "classified_ops", "DUTY_EVENTS", "duty_events ", "..", "../escape", "a/b",
])
def test_unknown_dataset_is_refused_before_any_staging_write(client, staging, tmp_path, dataset):
    """EXPECTED: only registry datasets reach a filesystem path."""
    before = _tree(tmp_path)
    r = client.post(
        f"/api/ingest/{quote(dataset, safe='')}",
        headers=INFRA,
        files={"file": ("batch.csv", CSV.encode())},
        data={"source_system": "hr", "batch_id": "b1"},
    )
    assert r.status_code in (404, 422), r.status_code
    after = _tree(tmp_path)
    new = set(after) - set(before)
    assert all(_expected_runtime_file(path) for path in new), new
    assert not staging.exists()


def test_dataset_helper_refuses_traversal_shaped_names(staging):
    for name in ("..", "../escape", "..\\escape", "/absolute", "C:\\absolute", "duty_events/../../x"):
        with pytest.raises(HTTPException) as exc:
            ing._dataset_dir(name)
        assert exc.value.status_code == 404


def test_oversize_upload_is_refused_without_writes(client, staging, monkeypatch):
    """EXPECTED: 413 before staging, enforced while streaming."""
    monkeypatch.setattr(ing, "MAX_BATCH_BYTES", 1024)
    r = _post(client, content="x," * 4096, batch_id="big-1")
    assert r.status_code == 413
    assert not staging.exists()


class _FakeUpload:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.calls: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.calls.append(size)
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        return chunk[:size]


def test_bounded_reader_requests_fixed_chunks(monkeypatch):
    """Proves the cap is enforced during reading, not after a full buffer."""
    monkeypatch.setattr(ing, "READ_CHUNK_BYTES", 4)
    monkeypatch.setattr(ing, "MAX_BATCH_BYTES", 10)
    upload = _FakeUpload([b"1234", b"5678", b"90"])
    assert asyncio.run(ing._read_bounded(upload)) == b"1234567890"
    assert upload.calls == [4, 4, 4, 4]

    over = _FakeUpload([b"1234", b"5678", b"90", b"X"])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ing._read_bounded(over))
    assert exc.value.status_code == 413
    assert over.calls == [4, 4, 4, 4]


def test_ingestion_authorization_is_audited(staging, tmp_path):
    """Every authorization decision must leave a tamper-evident record."""
    audit_file = tmp_path / "audit.jsonl"
    with TestClient(app) as c:
        assert c.get("/api/ingest/status", headers=INFRA).status_code == 200
        assert _post(c, headers=WELFARE).status_code == 403

    records = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    decisions = [r for r in records if r.get("event_type") == "ACCESS_CONTROL"]
    outcomes = {(d.get("details") or {}).get("view"): d.get("outcome") for d in decisions}
    assert "infrastructure" in outcomes, f"no infrastructure ACCESS_CONTROL record in {decisions}"
    assert "DENIED" in outcomes.values(), "a refused ingestion attempt was not audited"
    assert any(d.get("resource", "").startswith("/api/ingest/") for d in decisions)
    assert not staging.exists()


def test_ingestion_status_reports_quality(client, staging):
    """EXPECTED: quality report aggregates accepted/rejected/invalid counts."""
    assert _post(client, batch_id="b-ok").status_code == 200
    assert _post(client, content=CSV.replace("8.0", "40.0"), batch_id="b-bad").status_code == 200

    status = client.get("/api/ingest/status", headers=INFRA)
    assert status.status_code == 200
    body = status.json()
    assert body["enabled"] is True
    duty = body["datasets"]["duty_events"]
    assert duty["batches"] == 2
    assert duty["accepted"] == 1
    assert duty["rejected"] == 1
    assert duty["invalid_record_count"] >= 1
    assert duty["last_ingestion"]


def test_attacks_leave_nothing_outside_the_staging_root(client, staging, tmp_path, monkeypatch):
    """Aggregate containment proof: rejected input changes only staging/audit."""
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")

    before = _tree(tmp_path)
    assert _post(client, batch_id="../escape").status_code == 422
    assert client.post(
        "/api/ingest/classified_ops", headers=INFRA,
        files={"file": ("batch.csv", CSV.encode())},
        data={"source_system": "hr", "batch_id": "b1"},
    ).status_code == 404
    assert _post(client, content='a,b\n"unterminated', batch_id="malformed-1").status_code == 422
    monkeypatch.setattr(ing, "MAX_BATCH_BYTES", 1024)
    assert _post(client, content="x," * 4096, batch_id="big-2").status_code == 413
    after = _tree(tmp_path)

    new = set(after) - set(before)
    changed = {path for path in set(after) & set(before) if after[path] != before[path]}
    assert all(_expected_runtime_file(path) for path in new), new
    assert changed <= {"audit.jsonl"} or all(_expected_runtime_file(path) for path in changed)
    assert after["outside/sentinel.txt"] == b"untouched"
    assert not staging.exists()
    assert not any("escape" in path for path in after)


def test_symlinked_dataset_dir_is_refused_before_write(client, staging, tmp_path):
    """A dataset directory swapped for a link outside the root fails closed."""
    outside = tmp_path / "outside"
    outside.mkdir()
    staging.mkdir(parents=True)
    try:
        (staging / "duty_events").symlink_to(outside, target_is_directory=True)
    except OSError as exc:  # Windows without symlink privilege
        pytest.skip(f"symlinks unavailable in this environment: {exc}")

    r = _post(client, batch_id="b1")
    assert r.status_code == 500
    assert r.json()["detail"] == "Invalid ingestion staging path."
    assert list(outside.iterdir()) == []


def test_nginx_ingest_body_limit_matches_backend():
    """The edge and the application must advertise the same maximum."""
    conf = (Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    ingest_block = re.search(r"location\s+/api/ingest/\s*\{(?P<body>.*?)\n    \}", conf, re.S)
    assert ingest_block, "nginx.conf has no dedicated /api/ingest/ location"
    assert f"client_max_body_size {ing.MAX_BATCH_BYTES // (1024 * 1024)}m;" in ingest_block.group("body")

    general_block = re.search(r"location\s+/api/\s*\{(?P<body>.*?)\n    \}", conf, re.S)
    assert general_block, "nginx.conf has no general /api/ location"
    assert "client_max_body_size 64k;" in general_block.group("body")
