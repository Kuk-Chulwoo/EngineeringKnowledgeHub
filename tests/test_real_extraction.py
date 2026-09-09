"""All provider traffic uses MockTransport; facts are fabricated fixture facts, never CC1120."""

import copy
import hashlib
import io
import json
import sqlite3
from dataclasses import replace

import httpx
import pytest
import test_engineering_workflows as workflows
from pypdf import PdfReader
from test_migration import populated_v1

from backend.app.ai.config import ExtractionSettings, ProviderPolicy
from backend.app.ai.golden import compare
from backend.app.ai.parsing import DocumentText, analyze
from backend.app.ai.providers.openai_provider import READ_TIMEOUT_SECONDS, OpenAIProvider
from backend.app.ai.wire import PASS_KINDS, wire_schema
from backend.app.database import Database
from backend.app.engineering.repository import EngineeringRepository
from backend.app.engineering.schema import canonical
from backend.app.engineering.synthetic import PROVENANCE, candidates, fixture_pdf
from backend.app.migrations import migrate_v1_to_v2

client = workflows.client
settings = workflows.settings
fields = workflows.fields
review = workflows.review
source = workflows.source

SCOPE = "FAB-PKG-A"
MODEL = "mock-structured-model"


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("EKH_EXTERNAL_AI_ENABLED", "false")

    def fail(*args, **kwargs):
        pytest.fail("A test attempted a real network request")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)


def pass_payload(revision, pass_name):
    data = candidates(revision).model_dump()
    entities = [e for e in data["entities"] if e["kind"] in PASS_KINDS[pass_name]]
    for e in entities:
        e["fields"] = [f for f in e["fields"] if not f["key"].startswith("alternate_function.")]
    for entity in entities:
        for claim in entity["fields"]:
            for evidence in claim["evidence"]:
                evidence["source_text_sha256"] = None
                evidence["locator_version"] = "native-selection/1"
    return {
        "schema_version": data["schema_version"],
        "source_revision_id": revision,
        "entities": entities,
    }


def transport(calls, mutation=None):
    def handle(request):
        payload = json.loads(request.content)
        content = json.loads(payload["input"][1]["content"])
        name = next(p for p in PASS_KINDS if "Focused pass: " + p in payload["input"][0]["content"])
        calls.append((request, payload))
        output = pass_payload(content["source_revision_id"], name)
        if mutation:
            mutation(output, name)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": MODEL + "-version-1",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": canonical(output)}],
                    }
                ],
            },
        )

    return httpx.MockTransport(handle)


def configure(client, mutation=None):
    service = client.app.state.engineering
    service.policy = ProviderPolicy(True, MODEL, "fake-key-for-mocked-transport")
    calls = []
    service.providers["openai"] = lambda: OpenAIProvider(
        service.policy.api_key, transport(calls, mutation)
    )
    return service, calls


def start(client, revision, retry=None):
    response = client.post(
        f"/api/v1/revisions/{revision}/extraction-runs",
        json={
            "provider": "openai",
            "external_transmission_authorized": True,
            "settings": {"package_scope": SCOPE},
            "retry_of_run_id": retry,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def run_real(client, mutation=None):
    service, calls = configure(client, mutation)
    revision = source(client)
    run = start(client, revision)
    assert not calls  # Queuing and uploading do not transmit document contents.
    service.work_once()
    result = service.repository.read_run(run["id"])
    return result, calls


def test_four_pass_provider_provenance_and_review_survive_restart(client):
    run, calls = run_real(client)
    assert run["status"] == "SUCCEEDED", run
    assert len(calls) == 4
    assert not run["synthetic"] and not run["pads_eligible"]
    assert all(f["review_status"] == "AI_EXTRACTED" for f in fields(run))
    p = run["provenance"]
    assert p["model_identifier"] == MODEL and len(p["prompt_sha256"]) == 64
    assert p["extraction_settings"]["package_scope"] == SCOPE
    assert len(p["passes"]) == 4
    for record, (request, body) in zip(p["passes"], calls, strict=True):
        assert record["model_version"] == MODEL + "-version-1"
        assert len(record["request_sha256"]) == len(record["response_sha256"]) == 64
        assert body["text"]["format"]["strict"] is True and body["store"] is False
        assert request.url == "https://api.openai.com/v1/responses"
        assert "tools" not in body and "file" not in body
        assert "fake-key" not in canonical(body)
    assert "fake-key" not in canonical(run)
    repo = EngineeringRepository(client.app.state.engineering.repository.database)
    assert repo.read_run(run["id"]) == run
    assert review(client, fields(run)[0]).status_code == 201
    retry = start(client, run["source_revision_id"], run["id"])
    client.app.state.engineering.work_once()
    retried = repo.read_run(retry["id"])
    assert retried["status"] == "SUCCEEDED"
    assert all(f["review_status"] == "AI_EXTRACTED" for f in fields(retried))


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_root",
        "unknown_claim",
        "unknown_field",
        "human",
        "no_evidence",
        "wrong_revision",
        "wrong_page",
        "invented_quote",
        "wrong_scope",
        "wrong_kind",
    ],
)
def test_untrusted_provider_output_rejected_atomically(client, mutation):
    def alter(output, name):
        if name != "identity":
            return
        entity = output["entities"][0]
        field = entity["fields"][0]
        if mutation == "unknown_root":
            output["unrestricted_analysis"] = "bad"
        if mutation == "unknown_claim":
            field["voltage"] = 3.3
        if mutation == "unknown_field":
            field["key"] = "register_map"
        if mutation == "human":
            field["review_status"] = "ENGINEER_APPROVED"
        if mutation == "no_evidence":
            field["evidence"] = []
        if mutation == "wrong_revision":
            field["evidence"][0]["source_revision_id"] += 1
        if mutation == "wrong_page":
            field["evidence"][0]["page_number"] = 999
        if mutation == "invented_quote":
            field["evidence"][0]["source_text"] = "This quotation never appeared in the PDF"
            field["evidence"][0]["source_text_sha256"] = None
        if mutation == "wrong_scope":
            entity["scope_key"] = "another-package"
        if mutation == "wrong_kind":
            entity["kind"] = "PIN"

    run, calls = run_real(client, alter)
    assert run["status"] == "FAILED" and run["entities"] == []
    assert len(calls) == 1
    assert len(run["provenance"]["passes"]) == 1  # Metadata retained even for rejected output.


@pytest.mark.parametrize(
    "mode,code",
    [
        ("timeout", "PROVIDER_TIMEOUT"),
        ("http", "PROVIDER_HTTP_FAILURE"),
        ("malformed", "PROVIDER_MALFORMED"),
        ("incomplete", "PROVIDER_INCOMPLETE"),
        ("refusal", "PROVIDER_REFUSAL_OR_MALFORMED"),
        ("huge", "PROVIDER_RESPONSE_TOO_LARGE"),
    ],
)
def test_provider_failures_are_redacted_and_retry_is_explicit(client, mode, code):
    service, calls = configure(client)
    revision = source(client)

    def handle(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("sensitive document detail")
        if mode == "http":
            return httpx.Response(503, text="sensitive response")
        if mode == "malformed":
            return httpx.Response(200, text="not-json")
        if mode == "huge":
            return httpx.Response(200, content=b" " * 2_000_001)
        return httpx.Response(
            200,
            json={
                "status": "incomplete" if mode == "incomplete" else "completed",
                "output": [
                    {"type": "message", "content": [{"type": "refusal", "refusal": "sensitive"}]}
                ],
            },
        )

    service.providers["openai"] = lambda: OpenAIProvider("fake", httpx.MockTransport(handle))
    run = start(client, revision)
    service.work_once()
    failed = service.repository.read_run(run["id"])
    assert failed["status"] == "FAILED" and failed["error_code"] == code
    assert "sensitive" not in canonical(failed)
    assert len(calls) == (2 if mode == "timeout" else 1)
    assert failed["provenance"]["passes"][0]["error_code"] == code
    assert len(failed["provenance"]["passes"][0]["request_sha256"]) == 64
    if mode in ("timeout", "http", "huge"):
        assert failed["provenance"]["passes"][0]["response_sha256"] is None
    service, calls = configure(client)
    retry = start(client, revision, run["id"])
    service.work_once()
    assert service.repository.read_run(retry["id"])["status"] == "SUCCEEDED"
    assert len(calls) == 4


def test_provider_read_timeout_is_180_seconds():
    assert READ_TIMEOUT_SECONDS == 180


def test_focused_pass_retries_once_after_timeout_then_succeeds(client):
    service, successful_calls = configure(client)
    revision = source(client)
    attempts = []
    successful = transport(successful_calls)

    def flaky(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("withheld", request=request)
        return successful.handle_request(request)

    service.providers["openai"] = lambda: OpenAIProvider("fake", httpx.MockTransport(flaky))
    run = start(client, revision)
    service.work_once()
    completed = service.repository.read_run(run["id"])
    assert completed["status"] == "SUCCEEDED"
    assert len(attempts) == 5 and len(successful_calls) == 4


def test_validation_failure_is_not_retried(client):
    def invalid(output, name):
        if name == "identity":
            output["entities"][0]["fields"][0]["evidence"] = []

    run, calls = run_real(client, invalid)
    assert run["status"] == "FAILED" and run["error_code"] == "INVALID_OUTPUT"
    assert len(calls) == 1


def test_cancellation_after_timeout_prevents_retry(client):
    service, _ = configure(client)
    revision = source(client)
    run = start(client, revision)
    calls = []

    def cancel_then_timeout(request):
        calls.append(request)
        service.repository.cancel(run["id"])
        raise httpx.ReadTimeout("withheld", request=request)

    service.providers["openai"] = lambda: OpenAIProvider(
        "fake", httpx.MockTransport(cancel_then_timeout)
    )
    service.work_once()
    assert service.repository.read_run(run["id"])["status"] == "CANCELLED"
    assert len(calls) == 1


def test_policy_default_disabled_consent_required_and_worker_kill_switch(client):
    revision = source(client)
    url = f"/api/v1/revisions/{revision}/extraction-runs"
    payload = {
        "provider": "openai",
        "settings": {"package_scope": SCOPE},
        "external_transmission_authorized": True,
    }
    assert client.post(url, json=payload).status_code == 403
    service, calls = configure(client)
    assert (
        client.post(url, json={**payload, "external_transmission_authorized": False}).status_code
        == 422
    )
    service.policy = replace(service.policy, denied_revisions=frozenset({revision}))
    assert client.post(url, json=payload).status_code == 403
    service.policy = replace(service.policy, denied_revisions=frozenset())
    run = start(client, revision)
    service.policy = replace(service.policy, enabled=False)
    service.work_once()
    assert not calls and service.repository.read_run(run["id"])["status"] == "FAILED"


def test_worker_rejects_changed_model_and_cancel_stops_later_passes(client):
    service, calls = configure(client)
    revision = source(client)
    run = start(client, revision)
    service.policy = replace(service.policy, model="changed")
    service.work_once()
    assert not calls and service.repository.read_run(run["id"])["status"] == "FAILED"
    service, calls = configure(client)
    run = start(client, revision)

    def cancel(output, name):
        service.repository.cancel(run["id"])

    service.providers["openai"] = lambda: OpenAIProvider("fake", transport(calls, cancel))
    service.work_once()
    assert len(calls) == 1 and service.repository.read_run(run["id"])["status"] == "CANCELLED"


def test_selection_and_parser_bounds(client):
    settings = ExtractionSettings(
        package_scope=SCOPE, pages_per_pass=2, chars_per_page=1000, chars_per_pass=1500
    )
    doc = DocumentText(
        1,
        "a" * 64,
        20,
        {n: ("pins terminal " * 1000 if n == 12 else "x" * 2000) for n in range(1, 21)},
        [],
    )
    selected = doc.select("pins", settings)
    assert 12 in selected and len(selected) <= 2 and sum(map(len, selected.values())) <= 1500
    assert all(len(text) <= 1000 for text in selected.values())
    revision = source(client)
    actual = analyze(client.app.state.engineering.hub, revision, settings)
    assert all(len(text) <= 1000 for text in actual.pages.values())
    assert actual.truncated_pages
    with pytest.raises(Exception, match="page bound"):
        analyze(
            client.app.state.engineering.hub,
            revision,
            settings.model_copy(update={"max_document_pages": 1}),
        )


def test_transport_schema_is_closed_at_every_object_and_unknown_keys_fail():
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    for name in PASS_KINDS:
        check(wire_schema(name))


def golden(revision):
    # Test-only expected fixture; production has no API to derive golden data from AI.
    data = candidates(revision).model_dump()
    return {
        "schema_version": "engineering-golden/0.1",
        "manufacturer": "Fabricated Example Instruments",
        "part_number": "SYNTH-DEMO-4",
        "source_revision_id": revision,
        "document_revision": "TEST-A",
        "pdf_sha256": hashlib.sha256(fixture_pdf()).hexdigest(),
        "page_count": len(PdfReader(io.BytesIO(fixture_pdf())).pages),
        "source_url": None,
        "retrieved_at": None,
        "curation_notes": "Fabricated unit test fixture, never CC1120 expected facts",
        "package_scope": SCOPE,
        "entities": [
            dict(
                e,
                fields=[
                    {k: f[k] for k in ("key", "value", "evidence")}
                    for f in e["fields"]
                    if not f["key"].startswith("alternate_function.")
                ],
            )
            for e in data["entities"]
        ],
    }


def test_golden_requires_independent_attestation_approval_and_hash_pin(client):
    run, _ = run_real(client)
    manifest = golden(run["source_revision_id"])
    bad = {**manifest, "pdf_sha256": "f" * 64}
    url = "/api/v1/golden-references"
    assert client.post(url, json={"manifest": manifest}).status_code == 422
    assert (
        client.post(url, json={"manifest": bad, "manually_curated_from_source": True}).status_code
        == 422
    )
    response = client.post(url, json={"manifest": manifest, "manually_curated_from_source": True})
    assert response.status_code == 201, response.text
    g = response.json()
    evaluation_url = f"{url}/{g['id']}/evaluations/{run['id']}"
    assert client.get(evaluation_url).status_code == 409
    approval_url = f"{url}/{g['id']}/approval"
    assert (
        client.post(
            approval_url, json={"expected_sha256": "a" * 64, "reviewed_against_original_pdf": True}
        ).status_code
        == 409
    )
    assert (
        client.post(
            approval_url,
            json={"expected_sha256": g["manifest_sha256"], "reviewed_against_original_pdf": True},
        ).status_code
        == 200
    )
    before = client.app.state.engineering.repository.read_run(run["id"])
    report = client.get(evaluation_url)
    assert report.status_code == 200, report.text
    report = report.json()
    assert (
        report["wrong_value_count"]
        == report["missing_value_count"]
        == report["invented_value_count"]
        == 0
    )
    assert all(m["match"] == m["expected"] for m in report["metrics"].values())
    assert before == client.app.state.engineering.repository.read_run(run["id"])
    assert review(client, fields(run)[0]).status_code == 201
    assert client.get(evaluation_url).json() == report


def test_comparison_classifies_values_missing_extras_and_evidence_separately():
    expected = candidates(1).entities
    actual = copy.deepcopy(expected)
    identity = actual[0]
    identity.fields[0].value = "Wrong vendor"
    identity.fields[1].value = None
    identity.fields[1].availability = "NOT_FOUND"
    identity.fields[1].evidence = []
    identity.fields[2].evidence[0].page_number = 99
    pkg = next(e for e in actual if e.kind == "PACKAGE")
    new = pkg.fields[0].model_copy(deep=True)
    new.key, new.value = "type", "invented-extra"
    pkg.fields = [f for f in pkg.fields if f.key != "type"] + [new]
    exp_pkg = next(e for e in expected if e.kind == "PACKAGE")
    exp_pkg.fields = [f for f in exp_pkg.fields if f.key != "type"]
    report = compare(expected, actual)
    assert {"MATCH", "MISMATCH", "MISSING", "EXTRA"} <= {r["status"] for r in report["rows"]}
    assert (
        report["wrong_value_count"]
        == report["missing_value_count"]
        == report["invented_value_count"]
        == 1
    )
    assert report["metrics"]["Identity"]["expected"] == 3
    assert report["metrics"]["Identity"]["covered"] == 2
    assert report["metrics"]["Evidence"]["mismatch"] == 1


def test_v2_migration_preserves_populated_review_lineage_and_all_triggers(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    populated_v1(path)
    with sqlite3.connect(path) as c:
        c.execute("BEGIN IMMEDIATE")
        migrate_v1_to_v2(c)
    repo = EngineeringRepository(Database(path))
    run = repo.create_run(1, "b" * 64, 10, PROVENANCE, "Engineer")
    lease = repo.claim_next()
    repo.publish(run["id"], lease["lease_token"], candidates(1))
    result = repo.read_run(run["id"])
    for f in fields(result):
        repo.review(f["id"], 1, "ENGINEER_APPROVED", "Engineer", "Fixture checked")
    pkg = next(e for e in result["entities"] if e["kind"] == "PACKAGE")
    snapshot = repo.snapshot(run["id"], pkg["id"], [f["id"] for f in fields(result)], "Engineer")
    with sqlite3.connect(path) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
    Database(path).initialize()
    assert repo.read_snapshot(snapshot["id"]) == snapshot
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
        assert before == {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM engineering_fields")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE extraction_runs SET status='RUNNING'")
    assert len(list(tmp_path.glob("*.v2-backup-*"))) == 1


def test_scanned_pdf_is_rejected_before_any_provider_call():
    from pypdf import PdfWriter

    from backend.app.services import ServiceError

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)
    raw = buffer.getvalue()

    class Hub:
        def open_revision(self, revision_id):
            return {"sha256": hashlib.sha256(raw).hexdigest()}, io.BytesIO(raw)

    with pytest.raises(ServiceError, match="No native text"):
        analyze(Hub(), 1, ExtractionSettings(package_scope=SCOPE))


def test_golden_rejects_other_revision_and_comparison_ignores_corrections(client):
    from backend.app.ai.golden import GoldenManifest, GoldenService

    run, _ = run_real(client)
    service = GoldenService(client.app.state.engineering)
    manifest = GoldenManifest.model_validate(golden(run["source_revision_id"]))
    reference = service.create(manifest, "Engineer")
    service.approve(reference["id"], reference["manifest_sha256"], "Engineer")
    before = service.evaluate(reference["id"], run["id"])
    first = fields(run)[0]
    claim = {k: first[k] for k in ("key", "value", "availability", "evidence")}
    claim["value"] = "Engineer corrected value"
    correction = client.post(
        f"/api/v1/engineering-fields/{first['id']}/corrections",
        json={"expected_sequence": 1, "claim": claim},
    )
    assert correction.status_code == 201, correction.text
    assert service.evaluate(reference["id"], run["id"]) == before
    altered = manifest.model_copy(update={"document_revision": "another-revision"})
    from backend.app.services import ServiceError

    with pytest.raises(ServiceError, match="revision/hash mismatch"):
        service.create(altered, "Engineer")


def test_semantic_matching_ignores_provider_entity_ids():
    from backend.app.ai.golden import compare

    original = candidates(1).entities
    renamed = copy.deepcopy(original)
    mapping = {e.local_key: "renamed_" + e.local_key for e in renamed}
    for e in renamed:
        e.local_key = mapping[e.local_key]
        for f in e.fields:
            if f.key in ("package_ref", "pin_ref", "interface_ref") and f.value:
                f.value = mapping[f.value]
    result = compare(original, renamed)
    assert all(row["status"] == "MATCH" for row in result["rows"])


def test_runtime_secrets_and_originals_are_ignored():
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    names = [
        ".env",
        ".env.local",
        "data/reviewer.json",
        "data/hub.sqlite3",
        "data/engineering/raw-response.json",
        "data/datasheets/CC1120.pdf",
        "data/hub.sqlite3.v2-backup-test",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        cwd=root,
        input="\0".join(names).encode(),
        capture_output=True,
        check=True,
    )
    assert set(result.stdout.decode().strip("\0").split("\0")) == set(names)
