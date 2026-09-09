import hashlib
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.app.config import PROJECT_ROOT, Settings
from backend.app.main import create_app
from backend.app.storage import LocalStorage, UploadTooLarge


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "hub.sqlite3", tmp_path / "files", 1024 * 1024)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def pdf():
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(stream)
    return stream.getvalue()


def register(client, part="ABC123"):
    response = client.post(
        "/api/v1/components",
        json={
            "manufacturer": "Acme",
            "part_number": part,
            "description": "Precision voltage reference",
            "category": "Analog",
            "package": "SOIC-8",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, component_id, pdf, revision="A", title="Datasheet", **kwargs):
    return client.post(
        f"/api/v1/components/{component_id}/revisions",
        data={"revision": revision, "document_title": title, **kwargs},
        files={"file": ("datasheet.pdf", pdf, "application/pdf")},
    )


def test_register_search_and_validation(client):
    component_id = register(client)
    for query in ["acme", "abc123", "voltage", "analog"]:
        result = client.get("/api/v1/components", params={"q": query}).json()
        assert result["total"] == 1
        assert result["items"][0]["id"] == component_id
    assert client.get("/api/v1/components", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/v1/components", params={"q": "' OR 1=1 --"}).json()["total"] == 0
    assert (
        client.post(
            "/api/v1/components", json={"manufacturer": "acme", "part_number": "abc123"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/components", json={"manufacturer": " ", "part_number": "x"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/components?limit=0").status_code == 422
    assert client.get("/api/v1/components/999").status_code == 404


def test_company_part_metadata_search_and_uniqueness(client):
    component_id = register(client)
    created = client.post("/api/v1/components", json={
        "manufacturer": "Other", "part_number": "P-2", "internal_part_number": "NEW-002"
    })
    assert created.status_code == 201
    assert created.json()["lifecycle_status"] == "DRAFT"
    assert created.json()["created_at"] == created.json()["updated_at"]
    response = client.patch(
        f"/api/v1/components/{component_id}",
        json={"internal_part_number": "INT-001", "package": "QFN-32"},
    )
    assert response.status_code == 200
    assert response.json()["internal_part_number"] == "INT-001"
    assert response.json()["package"] == "QFN-32"
    assert client.get("/api/v1/components?q=int-001").json()["total"] == 1
    assert client.get("/api/v1/components?q=qfn-32").json()["total"] == 1
    other = register(client, "OTHER")
    assert client.patch(
        f"/api/v1/components/{other}", json={"internal_part_number": "int-001"}
    ).status_code == 409
    assert client.patch(
        f"/api/v1/components/{other}", json={"manufacturer": "Acme", "part_number": "ABC123"}
    ).status_code == 409
    assert client.patch(f"/api/v1/components/{other}", json={}).status_code == 422
    assert client.patch(f"/api/v1/components/{other}", json={"manufacturer": None}).status_code == 422
    assert client.patch("/api/v1/components/999", json={"category": "RF"}).status_code == 404


def test_lifecycle_transitions_and_release_requirements(client):
    component_id = register(client)
    endpoint = f"/api/v1/components/{component_id}/lifecycle"
    original_updated_at = client.get(f"/api/v1/components/{component_id}").json()["updated_at"]
    assert client.post(endpoint, json={"status": "ENGINEER_APPROVED"}).status_code == 409
    validated = client.post(endpoint, json={"status": "VALIDATED"}).json()
    assert validated["lifecycle_status"] == "VALIDATED"
    assert validated["updated_at"] != original_updated_at
    assert client.post(endpoint, json={"status": "ENGINEER_APPROVED"}).json()["lifecycle_status"] == "ENGINEER_APPROVED"
    assert client.post(endpoint, json={"status": "RELEASED"}).json()["lifecycle_status"] == "RELEASED"
    assert client.post(endpoint, json={"status": "DRAFT"}).status_code == 409

    incomplete = client.post(
        "/api/v1/components", json={"manufacturer": "Acme", "part_number": "EMPTY"}
    ).json()["id"]
    url = f"/api/v1/components/{incomplete}/lifecycle"
    assert client.post(url, json={"status": "VALIDATED"}).status_code == 200
    assert client.post(url, json={"status": "ENGINEER_APPROVED"}).status_code == 200
    failed = client.post(url, json={"status": "RELEASED"})
    assert failed.status_code == 409
    assert "description" in failed.json()["detail"]


def test_canonical_pin_table_replace_is_strict_atomic_and_ordered(client):
    component_id = register(client)
    endpoint = f"/api/v1/components/{component_id}/pins"
    replacement = {
        "source_type": "MANUAL",
        "pins": [
            {"pin_number": "EP", "pin_name": "GND"},
            {"pin_number": "2", "pin_name": "MISO"},
            {"pin_number": "1", "pin_name": "MOSI"},
            {"pin_number": "A1", "pin_name": "VCC"},
            {"pin_number": "PAD", "pin_name": "GROUND_PAD"},
        ],
    }
    result = client.put(endpoint, json=replacement)
    assert result.status_code == 200, result.text
    assert [pin["pin_number"] for pin in result.json()["pins"]] == ["1", "2", "A1", "EP", "PAD"]
    detail = client.get(f"/api/v1/components/{component_id}").json()
    assert detail["pin_summary"] == {"count": 5, "source_type": "MANUAL"}
    duplicate = client.put(
        endpoint,
        json={"source_type": "USER_IMPORT", "pins": [
            {"pin_number": "A1", "pin_name": "ONE"},
            {"pin_number": "a1", "pin_name": "TWO"},
        ]},
    )
    assert duplicate.status_code == 409
    assert client.get(endpoint).json()["pins"] == result.json()["pins"]
    assert client.put(
        endpoint, json={"source_type": "MANUAL", "pins": [{"pin_number": 1, "pin_name": "X"}]}
    ).status_code == 422
    assert client.put(
        endpoint, json={"source_type": "MANUAL", "pins": [{"pin_number": " ", "pin_name": "X"}]}
    ).status_code == 422
    assert client.put(
        endpoint, json={"source_type": "MANUAL", "pins": [{"pin_number": "1", "pin_name": " "}]}
    ).status_code == 422
    assert client.put(endpoint, json={"source_type": "UNKNOWN", "pins": []}).status_code == 422
    assert client.get("/api/v1/components/999/pins").status_code == 404


def test_multiple_documents_revisions_and_original_bytes(client, pdf, settings):
    component_id = register(client)
    first = upload(client, component_id, pdf, datasheet_date="2026-09-01")
    assert first.status_code == 201, first.text
    revision = first.json()
    assert revision["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert revision["datasheet_date"] == "2026-09-01"
    assert revision["size_bytes"] == len(pdf)
    assert "storage_key" not in revision
    assert upload(client, component_id, pdf, revision="B").status_code == 201
    assert upload(client, component_id, pdf, title="Errata").status_code == 201
    assert upload(client, component_id, pdf, revision="a").status_code == 409
    assert len(list(settings.storage_root.glob("*.pdf"))) == 3
    documents = client.get(f"/api/v1/components/{component_id}").json()["documents"]
    assert len(documents) == 2
    assert [r["revision"] for r in documents[0]["revisions"]] == ["B", "A"]
    for suffix, disposition in [("", "inline"), ("?download=true", "attachment")]:
        result = client.get(f"/api/v1/revisions/{revision['id']}/file{suffix}")
        assert result.status_code == 200
        assert result.content == pdf
        assert result.headers["content-type"] == "application/pdf"
        assert result.headers["content-disposition"].startswith(disposition)


def test_restart_persistence(settings, pdf):
    with TestClient(create_app(settings)) as first:
        component_id = register(first)
        revision_id = upload(first, component_id, pdf).json()["id"]
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/v1/components").json()["total"] == 1
        assert restarted.get(f"/api/v1/revisions/{revision_id}/file").content == pdf


@pytest.mark.parametrize("content", [b"", b"not a pdf", b"%PDF-1.7\nbroken"])
def test_invalid_pdf_leaves_no_files(client, settings, content):
    component_id = register(client)
    assert upload(client, component_id, content).status_code == 422
    assert not list(settings.storage_root.glob("*"))
    assert client.get(f"/api/v1/components/{component_id}").json()["documents"] == []


def test_invalid_metadata_and_missing_resources(client, pdf):
    component_id = register(client)
    assert upload(client, component_id, pdf, datasheet_date="bad").status_code == 422
    assert upload(client, component_id, pdf, revision=" ").status_code == 422
    assert upload(client, 999, pdf).status_code == 404
    assert client.get("/api/v1/revisions/999/file").status_code == 404


def test_size_limit(client, settings):
    component_id = register(client)
    assert (
        upload(client, component_id, b"%PDF-" + b"x" * settings.max_upload_bytes).status_code == 413
    )
    assert upload(client, component_id, b"x" * (3 * settings.max_upload_bytes)).status_code == 413
    assert not list(settings.storage_root.glob("*"))


def test_database_failure_cleans_file(client, pdf, settings, monkeypatch):
    component_id = register(client)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated transaction failure")

    monkeypatch.setattr(client.app.state.service.repository, "add_revision", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        upload(client, component_id, pdf)
    assert not list(settings.storage_root.glob("*"))


def test_missing_binary(client, pdf, settings):
    component_id = register(client)
    revision_id = upload(client, component_id, pdf).json()["id"]
    next(settings.storage_root.glob("*.pdf")).unlink()
    assert client.get(f"/api/v1/revisions/{revision_id}/file").status_code == 404


def test_storage_bounds_and_traversal(tmp_path):
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.open("../secret")
    with pytest.raises(UploadTooLarge):
        storage.put(io.BytesIO(b"12345"), 4)
    assert list(tmp_path.iterdir()) == []


def test_pagination(client):
    register(client, "B")
    register(client, "A")
    result = client.get("/api/v1/components?limit=1&offset=1").json()
    assert result["total"] == 2
    assert result["items"][0]["part_number"] == "B"


def test_concurrent_revision_conflict(client, pdf, settings):
    component_id = register(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: upload(client, component_id, pdf), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert len(list(settings.storage_root.glob("*.pdf"))) == 1


def test_default_paths(monkeypatch):
    monkeypatch.delenv("EKH_DATABASE_PATH", raising=False)
    assert Settings.from_env().database_path == PROJECT_ROOT / "data/hub.sqlite3"
    assert (PROJECT_ROOT / "backend").is_dir()


def test_unsupported_schema(settings):
    import sqlite3

    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="Unsupported"), TestClient(create_app(settings)):
        pass
