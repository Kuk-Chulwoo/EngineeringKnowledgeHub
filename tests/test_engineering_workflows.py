import json
import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.engineering.auth import password_record
from backend.app.engineering.synthetic import candidates, fixture_pdf
from backend.app.main import create_app
from backend.app.services import ServiceError

ORIGIN = {"Origin": "http://127.0.0.1:5173"}


@pytest.fixture
def settings(tmp_path):
    reviewer = tmp_path / "reviewer.json"
    reviewer.write_text(json.dumps(password_record("Test Engineer", "fabricated-test-password")))
    return Settings(tmp_path / "hub.sqlite3", tmp_path / "pdfs", reviewer_file=reviewer)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/reviewer/session",
            headers=ORIGIN,
            json={"name": "Test Engineer", "password": "fabricated-test-password"},
        )
        assert response.status_code == 200, response.text
        client.headers.update({**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]})
        yield client


def source(client):
    component = client.post(
        "/api/v1/components",
        json={
            "manufacturer": "Fabricated Example Instruments",
            "part_number": "SYNTH-DEMO-4",
        },
    ).json()
    revision = client.post(
        f"/api/v1/components/{component['id']}/revisions",
        data={"revision": "TEST-A"},
        files={"file": ("fabricated.pdf", fixture_pdf(), "application/pdf")},
    )
    assert revision.status_code == 201, revision.text
    return revision.json()["id"]


def create(client, revision=None, retry=None):
    if revision is None:
        revision = source(client)
    response = client.post(
        f"/api/v1/revisions/{revision}/extraction-runs",
        json={"provider": "synthetic", "retry_of_run_id": retry},
    )
    assert response.status_code == 201, response.text
    return response.json()


def completed(client):
    run = create(client)
    assert client.app.state.engineering.work_once()
    result = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    assert result["status"] == "SUCCEEDED", result
    return result


def fields(run):
    return [f for entity in run["entities"] for f in entity["fields"]]


def review(client, field, status="ENGINEER_APPROVED"):
    return client.post(
        f"/api/v1/engineering-fields/{field['id']}/reviews",
        json={
            "expected_sequence": field["latest_review_sequence"],
            "status": status,
            "reason": "Synthetic fixture reviewed for test",
        },
    )


def approve_snapshot(client, run):
    for field in fields(run):
        result = review(client, field)
        assert result.status_code == 201, result.text
    package = next(e for e in run["entities"] if e["kind"] == "PACKAGE")
    result = client.post(
        "/api/v1/approved-snapshots",
        json={
            "run_id": run["id"],
            "selected_package_entity_id": package["id"],
            "field_ids": [f["id"] for f in fields(run)],
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_run_and_candidates_survive_restart(client, settings):
    run = completed(client)
    assert len(run["entities"]) > 10
    assert run["synthetic"] and not run["pads_eligible"]
    assert "lease_token" not in run and "storage_key" not in json.dumps(run)
    with TestClient(create_app(settings)) as restarted:
        result = restarted.get(f"/api/v1/extraction-runs/{run['id']}").json()
        assert result == run
        assert restarted.get("/api/v1/reviewer/session").status_code == 401
    for field in fields(run):
        assert field["source_revision_id"] == run["source_revision_id"]
        assert field["review_status"] == "AI_EXTRACTED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(source_revision_id=999),
        lambda data: data["entities"][0]["fields"][0].update(review_status="ENGINEER_APPROVED"),
        lambda data: data["entities"][0]["fields"][0].update(key="invented"),
        lambda data: data["entities"][0]["fields"][0]["evidence"][0].update(page_number=999),
    ],
)
def test_invalid_provider_output_fails_without_partial_data(client, mutate):
    run = create(client)

    class Invalid:
        def extract(self, revision_id):
            data = candidates(revision_id).model_dump()
            mutate(data)
            return data

    client.app.state.engineering.work_once(Invalid())
    result = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    assert result["status"] == "FAILED"
    assert result["entities"] == []


def test_snapshot_requires_approval_then_invalidates(client):
    run = completed(client)
    package = next(e for e in run["entities"] if e["kind"] == "PACKAGE")
    assert (
        client.post(
            "/api/v1/approved-snapshots",
            json={
                "run_id": run["id"],
                "selected_package_entity_id": package["id"],
                "field_ids": [f["id"] for f in fields(run)],
            },
        ).status_code
        == 409
    )
    snapshot = approve_snapshot(client, run)
    assert snapshot["eligibility"] == "ACTIVE"
    assert snapshot["pads_eligible"] is False
    current = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    assert review(client, fields(current)[0], "ENGINEER_REJECTED").status_code == 201
    changed = client.get(f"/api/v1/approved-snapshots/{snapshot['id']}").json()
    assert changed["eligibility"] == "INVALIDATED"
    assert changed["manifest_sha256"] == snapshot["manifest_sha256"]
    assert changed["eligible_for_engineering_review"] is False


def test_correction_history_and_snapshot_replacement(client):
    run = completed(client)
    snapshot = approve_snapshot(client, run)
    current = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    field = next(f for f in fields(current) if f["key"] == "normalized_name")
    claim = {
        k: field[k]
        for k in (
            "key",
            "value",
            "availability",
            "confidence",
            "confidence_basis",
            "evidence",
            "transformation",
        )
    }
    claim["value"] = "NORMALIZED_TEST_CLOCK"
    response = client.post(
        f"/api/v1/engineering-fields/{field['id']}/corrections",
        json={"expected_sequence": field["latest_review_sequence"], "claim": claim},
    )
    assert response.status_code == 201, response.text
    new_id = response.json()["field_id"]
    changed = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    correction = next(f for f in fields(changed) if f["id"] == new_id)
    assert correction["review_status"] == "ENGINEER_DRAFT"
    assert correction["supersedes_field_id"] == field["id"]
    assert correction["content_sha256"] != field["content_sha256"]
    assert changed["candidate_set_sha256"] == run["candidate_set_sha256"]
    assert (
        client.get(f"/api/v1/approved-snapshots/{snapshot['id']}").json()["eligibility"] == "ACTIVE"
    )
    assert review(client, correction).status_code == 201
    changed = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    old = next(f for f in fields(changed) if f["id"] == field["id"])
    assert old["value"] == field["value"]
    assert old["review_status"] == "ENGINEER_REJECTED"
    assert len(old["history"]) == 3
    assert (
        client.get(f"/api/v1/approved-snapshots/{snapshot['id']}").json()["eligibility"]
        == "INVALIDATED"
    )


def test_stale_review_and_ai_cannot_approve(client):
    run = completed(client)
    field = fields(run)[0]
    assert review(client, field).status_code == 201
    assert review(client, field).status_code == 409
    with pytest.raises(ServiceError):
        client.app.state.engineering.repository.review(
            field["id"], 2, "ENGINEER_APPROVED", "fake-ai", "forged", actor_kind="AI"
        )
    with pytest.raises(ServiceError):
        client.app.state.engineering.repository.review(
            field["id"], 2, "AI_CHECKED", "fake-ai", "override", actor_kind="AI"
        )


def test_ai_checked_remains_unapproved(client):
    run = completed(client)
    field = fields(run)[0]
    result = client.app.state.engineering.repository.review(
        field["id"], 1, "AI_CHECKED", "synthetic-checker", "Checked", actor_kind="AI"
    )
    assert result["status"] == "AI_CHECKED"
    assert client.get(f"/api/v1/extraction-runs/{run['id']}").json()["pads_eligible"] is False


def test_retry_isolation_and_cancellation(client):
    run = completed(client)
    assert review(client, fields(run)[0]).status_code == 201
    retry = create(client, run["source_revision_id"], run["id"])
    assert retry["id"] != run["id"] and retry["entities"] == []
    client.app.state.engineering.work_once()
    result = client.get(f"/api/v1/extraction-runs/{retry['id']}").json()
    assert all(f["review_status"] == "AI_EXTRACTED" for f in fields(result))
    queued = create(client, run["source_revision_id"], retry["id"])
    assert client.post(f"/api/v1/extraction-runs/{queued['id']}/cancel").status_code == 200
    assert not client.app.state.engineering.work_once()
    assert client.post(f"/api/v1/extraction-runs/{run['id']}/cancel").status_code == 409


@pytest.mark.parametrize("terminal", ["FAILED", "CANCELLED", "SUCCEEDED"])
def test_terminal_publication_rejected(client, terminal):
    run = create(client)
    repo = client.app.state.engineering.repository
    claimed = repo.claim_next()
    data = candidates(run["source_revision_id"])
    if terminal == "FAILED":
        repo.fail(run["id"], claimed["lease_token"], "TEST_FAILURE")
    elif terminal == "CANCELLED":
        repo.cancel(run["id"])
    else:
        repo.publish(run["id"], claimed["lease_token"], data)
    with pytest.raises(ServiceError):
        repo.publish(run["id"], claimed["lease_token"], data)


def test_cancellation_during_work_cannot_publish(client):
    run = create(client)

    class Cancelled:
        def extract(self, revision_id):
            client.app.state.engineering.repository.cancel(run["id"])
            return candidates(revision_id).model_dump()

    client.app.state.engineering.work_once(Cancelled())
    result = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    assert result["status"] == "CANCELLED" and result["entities"] == []


def test_expired_lease_fails_after_restart(client, settings):
    run = create(client)
    claimed = client.app.state.engineering.repository.claim_next(lease_seconds=-1)
    with TestClient(create_app(settings)) as restarted:
        assert restarted.app.state.engineering.repository.claim_next() is None
    with pytest.raises(ServiceError):
        client.app.state.engineering.repository.publish(
            run["id"], claimed["lease_token"], candidates(run["source_revision_id"])
        )
    assert client.get(f"/api/v1/extraction-runs/{run['id']}").json()["status"] == "FAILED"


def test_database_enforces_immutable_audit_records(client, settings):
    run = completed(client)
    snapshot = approve_snapshot(client, run)
    field = fields(run)[0]
    for sql in [
        f"UPDATE engineering_fields SET key='changed' WHERE id={field['id']}",
        f"DELETE FROM engineering_review_events WHERE field_id={field['id']}",
        f"UPDATE extraction_runs SET status='QUEUED' WHERE id={run['id']}",
        f"UPDATE approved_snapshots SET manifest_sha256='changed' WHERE id={snapshot['id']}",
        f"DELETE FROM approved_snapshot_fields WHERE snapshot_id={snapshot['id']}",
    ]:
        with sqlite3.connect(settings.database_path) as c, pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)


def test_sessions_csrf_and_untrusted_origins(client, settings):
    assert (
        client.post(
            "/api/v1/reviewer/session",
            headers={"Origin": "https://evil.example"},
            json={"name": "Test Engineer", "password": "fabricated-test-password"},
        ).status_code
        == 403
    )
    revision = source(client)
    assert (
        client.post(
            f"/api/v1/revisions/{revision}/extraction-runs",
            headers={"X-CSRF-Token": "invalid"},
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/revisions/{revision}/extraction-runs", json={"provider": "external"}
        ).status_code
        == 422
    )
    assert client.delete("/api/v1/reviewer/session").status_code == 204
    assert client.post(f"/api/v1/revisions/{revision}/extraction-runs", json={}).status_code == 401
    with TestClient(create_app(replace(settings, reviewer_file=None))) as disabled:
        assert (
            disabled.post(
                "/api/v1/reviewer/session", headers=ORIGIN, json={"name": "x", "password": "x"}
            ).status_code
            == 503
        )


def test_source_hash_tampering_blocks_extraction(client, settings):
    revision = source(client)
    next(settings.storage_root.glob("*.pdf")).write_bytes(b"tampered")
    response = client.post(f"/api/v1/revisions/{revision}/extraction-runs", json={})
    assert response.status_code == 409


def test_invalid_correction_returns_422_without_new_version(client):
    run = completed(client)
    field = next(f for f in fields(run) if f["key"] == "package_ref")
    claim = {
        k: field[k]
        for k in (
            "key",
            "value",
            "availability",
            "confidence",
            "confidence_basis",
            "evidence",
            "transformation",
        )
    }
    claim["value"] = "nonexistent-package"
    response = client.post(
        f"/api/v1/engineering-fields/{field['id']}/corrections",
        json={"expected_sequence": 1, "claim": claim},
    )
    assert response.status_code == 422, response.text
    unchanged = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    assert len(fields(unchanged)) == len(fields(run))


def test_evidence_cannot_be_appended_after_publication(client, settings):
    run = completed(client)
    field = fields(run)[0]
    with sqlite3.connect(settings.database_path) as c, pytest.raises(sqlite3.IntegrityError):
        c.execute(
            """INSERT INTO engineering_field_evidence
            (field_id,ordinal,page_number,source_text,locator_method,locator_version,evidence_role)
            VALUES (?,999,1,'tampered','TEXT','test','DIRECT')""",
            (field["id"],),
        )


def test_snapshot_incomplete_or_cross_run_selection_fails(client):
    run = completed(client)
    for field in fields(run):
        assert review(client, field).status_code == 201
    package = next(e for e in run["entities"] if e["kind"] == "PACKAGE")
    payload = {
        "run_id": run["id"],
        "selected_package_entity_id": package["id"],
        "field_ids": [f["id"] for f in fields(run)][:-1],
    }
    assert client.post("/api/v1/approved-snapshots", json=payload).status_code == 409
    payload["field_ids"] = [f["id"] for f in fields(run)]
    payload["purpose"] = "pads-footprint"
    assert client.post("/api/v1/approved-snapshots", json=payload).status_code == 422


def test_wrong_password_rate_limit_and_session_expiry(client):
    for _ in range(5):
        response = client.post(
            "/api/v1/reviewer/session", json={"name": "Engineer", "password": "wrong"}
        )
        assert response.status_code == 401
    assert (
        client.post(
            "/api/v1/reviewer/session", json={"name": "Engineer", "password": "wrong"}
        ).status_code
        == 429
    )
    for session in client.app.state.reviewer.sessions.values():
        session.expires = 0
    assert client.get("/api/v1/reviewer/session").status_code == 401


def test_real_worker_process_publishes_queued_run(client, settings):
    import os
    import subprocess
    import sys
    from pathlib import Path

    run = create(client)
    process = subprocess.run(
        [sys.executable, "-m", "backend.app.engineering.worker", "--once"],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "EKH_DATABASE_PATH": str(settings.database_path),
            "EKH_STORAGE_ROOT": str(settings.storage_root),
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert process.returncode == 0, process.stderr
    result = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    assert result["status"] == "SUCCEEDED"
