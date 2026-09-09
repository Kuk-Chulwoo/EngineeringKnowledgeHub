"""Provider-independent four-pass orchestration and local evidence validation."""

from ..engineering.repository import require
from ..engineering.schema import CandidateSet, RealProvenance, digest
from .config import ExtractionSettings
from .parsing import PARSER_VERSION, analyze
from .prompts import PROMPT_VERSION, prompt, prompt_hash
from .providers.base import ProviderFailure
from .wire import PASS_KINDS, parse_output, wire_schema

PIN_CHUNK_PAGES = 2


def pin_chunks(selected):
    """Split deterministic physical page ranges without rewriting native text."""
    chunks = []
    pages = sorted(selected)
    for offset in range(0, len(pages), PIN_CHUNK_PAGES):
        page_range = pages[offset : offset + PIN_CHUNK_PAGES]
        chunk_selected = {page: selected[page] for page in page_range}
        chunks.append(
            {
                "selected": chunk_selected,
                "page_start": page_range[0],
                "page_end": page_range[-1],
            }
        )
    return chunks


def generate_with_timeout_retry(service, run, provider, frozen, pass_name, content, settings):
    timeout_retried = False
    while True:
        try:
            return provider.generate(
                frozen["model_identifier"],
                prompt(pass_name),
                content,
                wire_schema(pass_name),
                settings.max_output_tokens,
            )
        except ProviderFailure as error:
            if error.code != "PROVIDER_TIMEOUT" or timeout_retried:
                raise
            current = service.repository.read_run(run["id"])
            require(current["status"] == "RUNNING", "Run cancelled")
            timeout_retried = True


def pin_sort_key(entity):
    number = next(
        (str(claim.value) for claim in entity.fields if claim.key == "number" and claim.value),
        "",
    )
    return (number.casefold(), entity.local_key)


def provenance(model, settings):
    return RealProvenance(
        parser_version=PARSER_VERSION,
        model_identifier=model,
        prompt_version=PROMPT_VERSION,
        prompt_sha256=prompt_hash(),
        extraction_settings=settings.model_dump(),
        external_transmission_authorized=True,
    ).model_dump()


def extract(service, run, provider, *, on_progress=None):
    def progress(stage, current_pass=None):
        if on_progress is not None:
            on_progress(stage, current_pass)

    progress("preprocessing")
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
        progress("page_selection", pass_name)
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
        if pass_name == "pins":
            chunk_records = []
            merged = []
            package_ref = next(entity.local_key for entity in entities if entity.kind == "PACKAGE")
            for chunk_index, chunk in enumerate(pin_chunks(selected)):
                service.policy.authorize(document.revision_id)
                current = service.repository.read_run(run["id"])
                require(current["status"] == "RUNNING", "Run cancelled")
                chunk_selected = chunk["selected"]
                chunk_content = {
                    **content,
                    "physical_pages": {str(k): v for k, v in chunk_selected.items()},
                }
                progress("provider_request", pass_name)
                try:
                    result = generate_with_timeout_retry(
                        service, run, provider, frozen, pass_name, chunk_content, settings
                    )
                except ProviderFailure as error:
                    if error.request_sha256:
                        chunk_records.append(
                            {
                                "chunk_index": chunk_index,
                                "page_start": chunk["page_start"],
                                "page_end": chunk["page_end"],
                                "selected_pages": list(chunk_selected),
                                "selected_text_sha256": digest(
                                    {str(k): v for k, v in chunk_selected.items()}
                                ),
                                "request_sha256": error.request_sha256,
                                "response_sha256": error.response_sha256,
                                "model_version": None,
                                "error_code": error.code,
                            }
                        )
                        service.repository.record_pass(
                            run["id"],
                            run["lease_token"],
                            {
                                **record,
                                "request_sha256": digest(
                                    [item["request_sha256"] for item in chunk_records]
                                ),
                                "response_sha256": None,
                                "model_version": None,
                                "error_code": error.code,
                                "pin_chunks": chunk_records,
                            },
                        )
                    raise
                chunk_records.append(
                    {
                        "chunk_index": chunk_index,
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                        "selected_pages": list(chunk_selected),
                        "selected_text_sha256": digest(
                            {str(k): v for k, v in chunk_selected.items()}
                        ),
                        "request_sha256": result.request_sha256,
                        "response_sha256": result.response_sha256,
                        "model_version": result.model_version,
                        "error_code": None,
                    }
                )
                progress("evidence_validation", pass_name)
                try:
                    merged.extend(
                        parse_output(
                            result.payload,
                            pass_name,
                            document.revision_id,
                            document.page_count,
                            chunk_selected,
                            settings.package_scope,
                            package_ref,
                            str(chunk_index),
                        )
                    )
                except ValueError:
                    service.repository.record_pass(
                        run["id"],
                        run["lease_token"],
                        {
                            **record,
                            "request_sha256": digest(
                                [item["request_sha256"] for item in chunk_records]
                            ),
                            "response_sha256": digest(
                                [item["response_sha256"] for item in chunk_records]
                            ),
                            "model_version": result.model_version,
                            "pin_chunks": chunk_records,
                        },
                    )
                    raise
            record.update(
                request_sha256=digest([item["request_sha256"] for item in chunk_records]),
                response_sha256=digest([item["response_sha256"] for item in chunk_records]),
                model_version=chunk_records[-1]["model_version"],
                pin_chunks=chunk_records,
            )
            progress("pass_audit", pass_name)
            service.repository.record_pass(run["id"], run["lease_token"], record)
            entities.extend(sorted(merged, key=pin_sort_key))
            continue

        progress("provider_request", pass_name)
        try:
            result = generate_with_timeout_retry(
                service, run, provider, frozen, pass_name, content, settings
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
        progress("pass_audit", pass_name)
        service.repository.record_pass(run["id"], run["lease_token"], record)
        progress("evidence_validation", pass_name)
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
    progress("candidate_assembly")
    return CandidateSet(
        source_revision_id=document.revision_id,
        entities=entities,
        provenance=service.repository.read_run(run["id"])["provenance"],
    )
