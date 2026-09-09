"""Worker diagnostics must stay useful without becoming a second document store."""

import json
import os
import subprocess
import sys

import pytest
import test_real_extraction as real
from pydantic import ValidationError

from backend.app.engineering.diagnostics import RunDiagnostics, sanitized_message
from backend.app.engineering.schema import Claim
from backend.app.services import ServiceError

client = real.client
settings = real.settings
no_external_network = real.no_external_network
SECRET = "sk-test-secret-canary"
SOURCE = "CONFIDENTIAL_DATASHEET_CANARY"
RAW = "RAW_PROVIDER_RESPONSE_CANARY"
UNSAFE = f"Authorization: Bearer {SECRET} source={SOURCE} response={RAW}"


def events(caplog):
    records = [r for r in caplog.records if r.name == "ekh.worker"]
    for record in records:
        assert not record.exc_info and not record.stack_info
        assert not record.args  # Never hand the logger an exception or raw payload.
        for forbidden in (SECRET, SOURCE, RAW, "Authorization", "Bearer", "Fabricated Example"):
            assert forbidden not in record.getMessage()
    return [json.loads(r.getMessage()) for r in records]


@pytest.mark.parametrize("pass_name", ["identity", "package", "pins", "interfaces"])
def test_failed_pass_and_sanitized_validation_details_keep_db_contract(client, caplog, pass_name):
    def mutate(output, current):
        if current == pass_name:
            output["entities"][0]["fields"][0]["confidence"] = UNSAFE

    run, _ = real.run_real(client, mutate)
    assert run["status"] == "FAILED" and run["error_code"] == "INVALID_OUTPUT"
    assert run["error_summary"] == "Extraction failed; original PDF is unchanged"
    assert run["entities"] == []
    (log,) = events(caplog)
    assert log["run_id"] == run["id"] and log["provider"] == "openai"
    assert log["model"] == real.MODEL and log["current_pass"] == pass_name
    assert log["stage"] == "evidence_validation" and log["exception_class"] == "ValidationError"
    assert "entities.0.fields.0.confidence: float_type" in log["sanitized_error_message"]
    assert "sanitized_error_message" not in run


@pytest.mark.parametrize(
    "error,code,message",
    [
        (
            ValueError(UNSAFE),
            "INVALID_OUTPUT",
            "Candidate validation failed; dynamic detail withheld",
        ),
        (
            RuntimeError(UNSAFE),
            "SOURCE_OR_WORKER_ERROR",
            "Worker operation failed; exception detail withheld",
        ),
        (
            ServiceError(422, UNSAFE),
            "PUBLICATION_OR_SOURCE_REJECTED",
            "Source or publication validation failed; dynamic detail withheld",
        ),
    ],
)
def test_unknown_exceptions_and_chains_never_leak(client, caplog, error, code, message):
    run = real.workflows.create(client)

    class BrokenProvider:
        def extract(self, revision_id):
            raise error from RuntimeError(UNSAFE)

    service = client.app.state.engineering
    service.work_once(BrokenProvider())
    failed = service.repository.read_run(run["id"])
    assert failed["error_code"] == code and failed["entities"] == []
    (log,) = events(caplog)
    assert log["current_pass"] == "synthetic" and log["model"] == "none-synthetic"
    assert log["exception_class"] == type(error).__name__
    assert log["sanitized_error_message"] == message


def test_pydantic_extra_keys_inputs_and_context_are_not_logged(caplog):
    try:
        Claim.model_validate({"key": "manufacturer", "value": UNSAFE, SOURCE: RAW})
    except ValidationError as error:
        RunDiagnostics().failure(
            {
                "id": 1,
                "provider": "openai",
                "provenance_json": json.dumps({"model_identifier": SECRET}),
            },
            error,
            SECRET,
        )
    (log,) = events(caplog)
    assert log["model"] == "withheld"
    assert "*: extra_forbidden" in log["sanitized_error_message"]


def test_known_evidence_error_is_actionable_and_next_run_has_fresh_context(client, caplog):
    def mutate(output, name):
        if name == "pins":
            output["entities"][0]["fields"][0]["evidence"][0]["source_text"] = SOURCE

    failed, _ = real.run_real(client, mutate)
    (first,) = events(caplog)
    assert first["current_pass"] == "pins"
    assert (
        first["sanitized_error_message"] == "Evidence does not resolve to selected native page text"
    )
    service = client.app.state.engineering
    retry = real.start(client, failed["source_revision_id"], failed["id"])
    from dataclasses import replace

    service.policy = replace(service.policy, enabled=False)
    service.work_once()
    second = events(caplog)[1]
    assert second["run_id"] == retry["id"] and second["current_pass"] is None
    assert second["stage"] == "policy"
    assert second["sanitized_error_message"] == "External AI transmission is disabled"


def test_provider_timeout_logs_safe_reason_without_chained_http_data(client, caplog):
    import httpx

    from backend.app.ai.providers.openai_provider import OpenAIProvider

    service, _ = real.configure(client)
    revision = real.source(client)

    def timeout(request):
        raise httpx.ReadTimeout(UNSAFE, request=request)

    service.providers["openai"] = lambda: OpenAIProvider(SECRET, httpx.MockTransport(timeout))
    run = real.start(client, revision)
    service.work_once()
    assert service.repository.read_run(run["id"])["error_code"] == "PROVIDER_TIMEOUT"
    (log,) = events(caplog)
    assert log["stage"] == "provider_request" and log["current_pass"] == "identity"
    assert log["exception_class"] == "ProviderFailure"
    assert log["sanitized_error_message"] == "Provider request timed out"


def test_success_and_idle_worker_do_not_emit_failure_logs(client, caplog):
    run, _ = real.run_real(client)
    assert run["status"] == "SUCCEEDED"
    assert not client.app.state.engineering.work_once()
    assert events(caplog) == []


def test_worker_cli_emits_single_json_error_on_console(client, settings):
    service, _ = real.configure(client)
    revision = real.source(client)
    run = real.start(client, revision)
    env = {
        **os.environ,
        "EKH_DATABASE_PATH": str(settings.database_path),
        "EKH_STORAGE_ROOT": str(settings.storage_root),
        "EKH_EXTERNAL_AI_ENABLED": "false",
        "OPENAI_API_KEY": SECRET,
        "EKH_AI_DENIED_REVISIONS": "",
    }
    process = subprocess.run(
        [sys.executable, "-m", "backend.app.engineering.worker", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    log = json.loads(process.stderr.strip())
    assert process.stdout == ""
    assert log["run_id"] == run["id"] and log["provider"] == "openai"
    assert log["model"] == real.MODEL and log["current_pass"] is None
    assert log["exception_class"] == "ServiceError"
    assert SECRET not in process.stderr and "Traceback" not in process.stderr
    assert service.repository.read_run(run["id"])["error_code"] == "PUBLICATION_OR_SOURCE_REJECTED"


def test_sanitizer_does_not_stringify_arbitrary_exception():
    class BadError(Exception):
        def __str__(self):
            raise AssertionError("Do not stringify untrusted exceptions")

    assert (
        sanitized_message(BadError(UNSAFE)) == "Worker operation failed; exception detail withheld"
    )


def test_validation_context_message_and_custom_error_names_are_not_logged(caplog):
    error = ValidationError.from_exception_data(
        "Untrusted payload",
        [
            {
                "type": "value_error",
                "loc": (SOURCE, "value"),
                "input": RAW,
                "ctx": {"error": ValueError(UNSAFE)},
            }
        ],
    )
    RunDiagnostics().failure(
        {
            "id": 5,
            "provider": "openai",
            "provenance_json": json.dumps({"model_identifier": "safe-model"}),
        },
        error,
        SECRET,
    )
    (log,) = events(caplog)
    assert (
        log["sanitized_error_message"]
        == "Schema validation failed (1 errors): *.value: value_error"
    )
