"""Provider-independent four-pass orchestration and local evidence validation."""

from ..engineering.repository import require
from ..engineering.schema import CandidateSet, RealProvenance, digest
from .config import ExtractionSettings
from .parsing import PARSER_VERSION, analyze
from .prompts import PROMPT_VERSION, prompt, prompt_hash
from .providers.base import ProviderFailure
from .wire import PASS_KINDS, parse_output, wire_schema


def provenance(model, settings):
    return RealProvenance(
        parser_version=PARSER_VERSION,
        model_identifier=model,
        prompt_version=PROMPT_VERSION,
        prompt_sha256=prompt_hash(),
        extraction_settings=settings.model_dump(),
        external_transmission_authorized=True,
    ).model_dump()


def extract(service, run, provider):
    frozen = service.repository.read_run(run["id"])["provenance"]
    settings = ExtractionSettings.model_validate(frozen["extraction_settings"])
    require(
        frozen == provenance(service.policy.model, settings),
        "Worker model/prompt/parser changed; explicitly retry as new run",
    )
    document = analyze(service.hub, run["source_revision_id"], settings)
    require(
        document.sha256 == run["source_sha256"] and document.page_count == run["page_count"],
        "Run/source mismatch",
    )
    entities = []
    for pass_name in PASS_KINDS:
        service.policy.authorize(document.revision_id)
        current = service.repository.read_run(run["id"])
        require(current["status"] == "RUNNING", "Run cancelled")
        selected = document.select(pass_name, settings)
        context = [
            {
                "local_key": e.local_key,
                "kind": e.kind,
                "scope_key": e.scope_key,
                "fields": [
                    {"key": f.key, "value": f.value}
                    for f in e.fields
                    if f.availability == "PRESENT"
                    and f.key
                    in (
                        "manufacturer_package_code",
                        "variant_selector",
                        "number",
                        "source_name",
                        "package_ref",
                    )
                ],
            }
            for e in entities
            if e.kind in ("PACKAGE", "PIN")
        ]
        content = {
            "source_revision_id": document.revision_id,
            "package_scope": settings.package_scope,
            "physical_pages": {str(k): v for k, v in selected.items()},
            "reference_entities": context,
        }
        record = {
            "pass_name": pass_name,
            "prompt_sha256": digest(prompt(pass_name)),
            "selected_pages": list(selected),
            "selected_text_sha256": digest({str(k): v for k, v in selected.items()}),
            "truncated_pages": document.truncated_pages,
        }
        try:
            result = provider.generate(
                frozen["model_identifier"],
                prompt(pass_name),
                content,
                wire_schema(pass_name),
                settings.max_output_tokens,
            )
        except ProviderFailure as error:
            if error.request_sha256:
                service.repository.record_pass(
                    run["id"],
                    run["lease_token"],
                    {
                        **record,
                        "request_sha256": error.request_sha256,
                        "response_sha256": error.response_sha256,
                        "model_version": None,
                        "error_code": error.code,
                    },
                )
            raise
        record.update(
            request_sha256=result.request_sha256,
            response_sha256=result.response_sha256,
            model_version=result.model_version,
        )
        # Persist metadata even if subsequent local candidate validation fails; never raw responses.
        service.repository.record_pass(run["id"], run["lease_token"], record)
        entities.extend(
            parse_output(
                result.payload,
                pass_name,
                document.revision_id,
                document.page_count,
                selected,
                settings.package_scope,
            )
        )
    return CandidateSet(
        source_revision_id=document.revision_id,
        entities=entities,
        provenance=service.repository.read_run(run["id"])["provenance"],
    )
