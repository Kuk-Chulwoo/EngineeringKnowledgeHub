import hashlib

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.symbols.storage import MAX_SYMBOL_BYTES


@pytest.fixture
def symbol_context(tmp_path):
    settings = Settings(tmp_path / "hub.sqlite3", tmp_path / "datasheets", 4 * 1024 * 1024)
    with TestClient(create_app(settings)) as client:
        yield client, tmp_path


def component(client):
    response = client.post("/api/v1/components", json={
        "manufacturer": "TI", "part_number": "CC1120", "description": "RF transceiver",
        "category": "RF", "package": "QFN-32",
    })
    assert response.status_code == 201
    return response.json()["id"]


def create_symbol(client, component_id, name="CC1120", revision="A"):
    response = client.post(f"/api/v1/components/{component_id}/symbols", json={
        "cad_tool": "PADS_LOGIC", "cad_version": "VX2.11", "symbol_name": name,
        "source_type": "EXISTING_COMPANY_LIBRARY", "revision": revision, "notes": "",
    })
    assert response.status_code == 201, response.text
    return response.json()


def transition(client, symbol_id, status):
    return client.post(f"/api/v1/symbols/{symbol_id}/lifecycle", json={"status": status})


def test_create_list_detail_update_and_enum_validation(symbol_context):
    client, _ = symbol_context
    component_id = component(client)
    symbol = create_symbol(client, component_id)
    assert symbol["lifecycle_status"] == "DRAFT"
    assert symbol["pin_validation_status"] == "NOT_CHECKED"
    assert symbol["source_filename"] is None
    assert "storage_key" not in symbol
    assert client.get(f"/api/v1/components/{component_id}/symbols").json() == [symbol]
    assert client.get(f"/api/v1/symbols/{symbol['id']}").json() == symbol
    updated = client.patch(f"/api/v1/symbols/{symbol['id']}", json={
        "cad_version": "VX2.12", "notes": "Reviewed source metadata"
    })
    assert updated.status_code == 200
    assert updated.json()["cad_version"] == "VX2.12"
    assert updated.json()["updated_at"] != symbol["updated_at"]
    assert client.patch(f"/api/v1/symbols/{symbol['id']}", json={}).status_code == 422
    invalid_base = {"cad_version": "VX2.11", "symbol_name": "BAD", "revision": "A",
                    "notes": ""}
    assert client.post(f"/api/v1/components/{component_id}/symbols", json={
        **invalid_base, "cad_tool": "OTHER", "source_type": "ENGINEER_CREATED"
    }).status_code == 422
    assert client.post(f"/api/v1/components/{component_id}/symbols", json={
        **invalid_base, "cad_tool": "PADS_LOGIC", "source_type": "AI_GENERATED"
    }).status_code == 422
    assert client.get("/api/v1/symbols/999").status_code == 404


def test_duplicate_symbol_revision_is_case_insensitive(symbol_context):
    client, _ = symbol_context
    component_id = component(client)
    create_symbol(client, component_id, "CC1120", "A")
    response = client.post(f"/api/v1/components/{component_id}/symbols", json={
        "cad_tool": "PADS_LOGIC", "cad_version": "VX2.11", "symbol_name": "cc1120",
        "source_type": "ENGINEER_CREATED", "revision": "a", "notes": "duplicate",
    })
    assert response.status_code == 409


def test_symbol_file_is_hashed_downloadable_separate_and_immutable(symbol_context):
    client, root = symbol_context
    symbol = create_symbol(client, component(client))
    content = b"*PADS-LOGIC-CAE-DECAL*\nSYMBOL CC1120\n"
    response = client.post(
        f"/api/v1/symbols/{symbol['id']}/file", files={"file": ("../CC1120.c", content)}
    )
    assert response.status_code == 200, response.text
    attached = response.json()
    assert attached["source_filename"] == "CC1120.c"
    assert attached["size_bytes"] == len(content)
    assert attached["sha256"] == hashlib.sha256(content).hexdigest()
    assert "storage_key" not in attached
    files = list((root / "library" / "schematic-symbols").rglob("*.c"))
    assert len(files) == 1
    assert not list((root / "datasheets").glob("*.c"))
    downloaded = client.get(f"/api/v1/symbols/{symbol['id']}/file?download=true")
    assert downloaded.content == content
    assert downloaded.headers["content-disposition"].startswith("attachment")
    assert client.post(
        f"/api/v1/symbols/{symbol['id']}/file", files={"file": ("new.c", b"new")}
    ).status_code == 409
    assert files[0].read_bytes() == content


def test_symbol_file_validation(symbol_context):
    client, root = symbol_context
    component_id = component(client)
    cases = [
        ("symbol.d", b"pcb", 422),
        ("symbol.c", b"", 422),
        ("symbol.c", b"\xff\xfe", 422),
        ("symbol.c", b"x" * (MAX_SYMBOL_BYTES + 1), 413),
    ]
    for index, (filename, content, status) in enumerate(cases):
        symbol = create_symbol(client, component_id, f"SYM{index}")
        response = client.post(
            f"/api/v1/symbols/{symbol['id']}/file", files={"file": (filename, content)}
        )
        assert response.status_code == status
    assert not list((root / "library" / "schematic-symbols").rglob("*.c"))


def test_pin_review_lifecycle_and_release_eligibility(symbol_context):
    client, _ = symbol_context
    component_id = component(client)
    without_file = create_symbol(client, component_id, "NOFILE")
    assert transition(client, without_file["id"], "ENGINEER_APPROVED").status_code == 409
    assert transition(client, without_file["id"], "VALIDATED").status_code == 200
    assert transition(client, without_file["id"], "ENGINEER_APPROVED").status_code == 200
    no_file_release = transition(client, without_file["id"], "RELEASED")
    assert no_file_release.status_code == 409
    assert "source file" in no_file_release.json()["detail"]

    symbol = create_symbol(client, component_id, "READY")
    client.post(f"/api/v1/symbols/{symbol['id']}/file", files={"file": ("ready.c", b"CAE")})
    reviewed = client.post(
        f"/api/v1/symbols/{symbol['id']}/pin-validation",
        json={"status": "ENGINEER_REVIEWED"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["pin_validation_status"] == "ENGINEER_REVIEWED"
    assert transition(client, symbol["id"], "VALIDATED").status_code == 200
    assert transition(client, symbol["id"], "ENGINEER_APPROVED").status_code == 200
    no_pins = transition(client, symbol["id"], "RELEASED")
    assert no_pins.status_code == 409
    assert "canonical pins" in no_pins.json()["detail"]

    client.put(f"/api/v1/components/{component_id}/pins", json={
        "source_type": "MANUAL", "pins": [{"pin_number": "1", "pin_name": "GND"}]
    })
    reset = client.post(
        f"/api/v1/symbols/{symbol['id']}/pin-validation", json={"status": "NOT_CHECKED"}
    )
    assert reset.json()["pin_validation_status"] == "NOT_CHECKED"
    no_review = transition(client, symbol["id"], "RELEASED")
    assert no_review.status_code == 409
    assert "engineer pin review" in no_review.json()["detail"]
    client.post(f"/api/v1/symbols/{symbol['id']}/pin-validation", json={
        "status": "ENGINEER_REVIEWED"
    })
    released = transition(client, symbol["id"], "RELEASED")
    assert released.status_code == 200
    assert released.json()["lifecycle_status"] == "RELEASED"
    assert transition(client, symbol["id"], "VALIDATED").status_code == 409
