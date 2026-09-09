"""Issue #1: diagnostics identify structure/rules, never untrusted values."""

import json

import pytest
import test_real_extraction as real
from pydantic import ValidationError

from backend.app.engineering.diagnostics import RunDiagnostics, validation_metadata
from backend.app.engineering.synthetic import candidates

client = real.client
settings = real.settings
no_external_network = real.no_external_network
PRIVATE = "candidate-value-DO-NOT-LOG"
QUOTE = "datasheet-quote-DO-NOT-LOG"
SECRET = "credential-DO-NOT-LOG"
RAW = "provider-raw-output-DO-NOT-LOG"


def logged(caplog):
    records = [r for r in caplog.records if r.name == "ekh.worker"]
    (record,) = records
    assert not record.exc_info and not record.stack_info and not record.args
    message = record.getMessage()
    for forbidden in (
        PRIVATE,
        QUOTE,
        SECRET,
        RAW,
        "Authorization",
        "Bearer",
        "TEST-QFN",
        "Fabricated Example Instruments",
    ):
        assert forbidden not in message
    result = json.loads(message)
    assert all(set(item) == {"loc", "type"} for item in result["validation_errors"])
    return result


@pytest.mark.parametrize(
    "case,kind,suffix",
    [
        ("quote", "evidence_quote_unresolved", "evidence.0.source_text"),
        ("not_selected", "evidence_page_not_selected", "evidence.0.page_number"),
        ("out_of_range", "evidence_page_out_of_range", "evidence.0.page_number"),
        ("wrong_revision", "evidence_wrong_revision", "evidence.0.source_revision_id"),
        ("missing", "evidence_missing", "evidence"),
        ("enum", "invalid_enum", "value"),
        ("unknown_field", "unknown_field", "key"),
        ("confidence", "float_type", "confidence"),
        ("required", "missing", "confidence"),
    ],
)
def test_actionable_field_rules_preserve_failed_run_contract(client, caplog, case, kind, suffix):
    def mutate(output, name):
        if name != "package":
            return
        entity = output["entities"][0]
        claim = entity["fields"][0]
        if case == "quote":
            claim["evidence"][0]["source_text"] = QUOTE
        if case in ("not_selected", "out_of_range"):
            claim["evidence"][0]["page_number"] = 2 if case == "not_selected" else 999
        if case == "wrong_revision":
            claim["evidence"][0]["source_revision_id"] += 1
        if case == "missing":
            claim["evidence"] = []
        if case == "enum":
            claim["key"] = "pin_count_basis"
            claim["value"] = PRIVATE
        if case == "unknown_field":
            claim["key"] = PRIVATE
        if case == "confidence":
            claim["confidence"] = PRIVATE
        if case == "required":
            del claim["confidence"]

    service, _ = real.configure(client, mutate)
    revision = real.source(client)
    response = client.post(
        f"/api/v1/revisions/{revision}/extraction-runs",
        json={
            "provider": "openai",
            "external_transmission_authorized": True,
            "settings": {"package_scope": real.SCOPE, "pages_per_pass": 1},
        },
    )
    assert response.status_code == 201
    # Select only physical page 1, preserving the same bound/evidence rules.
    from unittest.mock import patch

    from backend.app.ai.parsing import DocumentText

    with patch.object(DocumentText, "select", lambda self, name, settings: {1: self.pages[1]}):
        service.work_once()
    run = service.repository.read_run(response.json()["id"])
    assert run["status"] == "FAILED" and run["error_code"] == "INVALID_OUTPUT"
    assert run["error_summary"] == "Extraction failed; original PDF is unchanged"
    assert run["entities"] == []
    event = logged(caplog)
    assert event["field_path"] == "entities.0.fields.0." + suffix
    assert event["validation_type"] == kind
    assert event["pass_name"] == event["current_pass"] == "package"
    assert event["stage"] == "evidence_validation" and event["error_count"] == 1
    assert "validation_errors" not in run


def test_publication_wrapper_preserves_field_rule_without_logging_value(client, caplog):
    run = real.workflows.create(client)

    class Provider:
        def extract(self, revision):
            value = candidates(revision).model_dump()
            pin = next(e for e in value["entities"] if e["kind"] == "PIN")
            field = next(f for f in pin["fields"] if f["key"] == "electrical_type")
            field["value"] = PRIVATE
            return value

    service = client.app.state.engineering
    service.work_once(Provider())
    failed = service.repository.read_run(run["id"])
    assert failed["error_code"] == "PUBLICATION_OR_SOURCE_REJECTED"
    event = logged(caplog)
    assert event["validation_type"] == "invalid_enum"
    assert event["field_path"].startswith("entities.") and event["field_path"].endswith(".value")
    assert event["stage"] == "publication" and event["exception_class"] == "ServiceError"


def test_pydantic_loc_type_only_masks_extra_keys_and_context(caplog):
    error = ValidationError.from_exception_data(
        RAW,
        [
            {
                "type": "value_error",
                "loc": ("entities", 0, "fields", 3, "value"),
                "input": PRIVATE,
                "ctx": {"error": ValueError(SECRET + QUOTE)},
            },
            {"type": "extra_forbidden", "loc": (RAW,), "input": SECRET},
        ],
    )
    RunDiagnostics("package", "evidence_validation").failure(
        {
            "id": 1,
            "provider": "openai",
            "provenance_json": json.dumps({"model_identifier": "test-model"}),
        },
        error,
        SECRET,
    )
    event = logged(caplog)
    assert event["validation_errors"] == [
        {"loc": ["entities", 0, "fields", 3, "value"], "type": "value_error"},
        {"loc": ["*"], "type": "extra_forbidden"},
    ]
    assert event["error_count"] == 2


def test_structural_details_are_bounded():
    error = ValidationError.from_exception_data(
        "test",
        [{"type": "extra_forbidden", "loc": (RAW,) * 20, "input": PRIVATE} for _ in range(20)],
    )
    detail = validation_metadata(error)
    assert detail["error_count"] == 20 and len(detail["validation_errors"]) == 8
    assert all(
        item == {"loc": ["*"] * 12, "type": "extra_forbidden"}
        for item in detail["validation_errors"]
    )


def test_missing_claim_slots_at_publication_have_structural_reason(client, caplog):
    run = real.workflows.create(client)

    class Provider:
        def extract(self, revision):
            data = candidates(revision).model_dump()
            data["entities"][0]["local_key"] = PRIVATE
            data["entities"][0]["fields"] = data["entities"][0]["fields"][:1]
            return data

    service = client.app.state.engineering
    service.work_once(Provider())
    assert service.repository.read_run(run["id"])["error_code"] == "PUBLICATION_OR_SOURCE_REJECTED"
    event = logged(caplog)
    assert event["validation_type"] == "missing"
    assert event["field_path"] == "entities.0.fields"


def test_nested_quantity_pydantic_error_keeps_full_publication_path(client, caplog):
    run = real.workflows.create(client)

    class Provider:
        def extract(self, revision):
            data = candidates(revision).model_dump()
            package = next(e for e in data["entities"] if e["kind"] == "PACKAGE")
            field = next(f for f in package["fields"] if f["key"].startswith("body_length."))
            field["value"] = {"decimal": PRIVATE, "unit": "mm"}
            return data

    service = client.app.state.engineering
    service.work_once(Provider())
    assert service.repository.read_run(run["id"])["error_code"] == "PUBLICATION_OR_SOURCE_REJECTED"
    event = logged(caplog)
    assert event["validation_type"] == "string_pattern_mismatch"
    assert event["field_path"].startswith("entities.")
    assert event["field_path"].endswith(".value.decimal")
