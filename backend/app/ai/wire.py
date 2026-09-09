"""Strict transport subset of engineering-extraction/0.1, validated again locally."""

from typing import Literal

from pydantic import Field

from ..engineering.schema import (
    REQUIRED,
    TEXT,
    Claim,
    Entity,
    Evidence,
    PinRecord,
    Quantity,
    StrictModel,
    field_type,
    is_exposed_pad_identifier,
    validate_claim,
)
from ..engineering.validation_errors import prefix_validation, validation_error
from .parsing import resolves_native_evidence


class WireEvidence(StrictModel):
    source_revision_id: int = Field(gt=0)
    page_number: int = Field(gt=0)
    printed_page_label: str | None = Field(default=None, max_length=100)
    source_text: str = Field(min_length=1, max_length=2048)
    source_text_sha256: None = None
    region: None = None
    locator_method: Literal["TEXT", "TABLE"] = "TEXT"
    locator_version: Literal["native-selection/1"] = "native-selection/1"
    evidence_role: Literal["DIRECT", "CONTEXT"] = "DIRECT"


class WireClaim(Claim):
    value: str | int | bool | Quantity | None = None
    evidence: list[WireEvidence] = Field(default_factory=list, max_length=16)


class WireEntity(Entity):
    fields: list[WireClaim] = Field(min_length=1, max_length=100)


class PassOutput(StrictModel):
    schema_version: Literal["engineering-extraction/0.1"]
    source_revision_id: int = Field(gt=0)
    entities: list[WireEntity] = Field(max_length=2000)


class MinimalWirePin(PinRecord):
    source_page: int = Field(gt=0)


class MinimalPinsOutput(StrictModel):
    schema_version: Literal["engineering-extraction/0.1"]
    source_revision_id: int = Field(gt=0)
    pins: list[MinimalWirePin] = Field(max_length=2000)


PASS_KINDS = {
    "identity": ["COMPONENT_IDENTITY"],
    "package": ["PACKAGE"],
    "pins": ["PIN"],
    "interfaces": ["INTERFACE", "INTERFACE_PIN"],
}


def wire_schema(pass_name: str):
    schema = (
        MinimalPinsOutput.model_json_schema() if pass_name == "pins" else PassOutput.model_json_schema()
    )

    def strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                strict(v)
        elif isinstance(node, list):
            for v in node:
                strict(v)

    strict(schema)
    if pass_name == "pins":
        return schema
    schema["$defs"]["WireEntity"]["properties"]["kind"] = {
        "type": "string",
        "enum": PASS_KINDS[pass_name],
    }
    # The closed vocabulary includes all currently supported slots. Arbitrary keys fail locally too.
    keys = set().union(*(TEXT[k] | REQUIRED[k] for k in PASS_KINDS[pass_name]))
    if pass_name == "package":
        keys |= {
            f"{d}.{b}"
            for d in ("body_length", "body_width", "body_height", "pitch")
            for b in ("minimum", "nominal", "maximum")
        }
    # Multiplexed functions use primary_function/functional_group in this initial wire profile.
    schema["$defs"]["WireClaim"]["properties"]["key"] = {"type": "string", "enum": sorted(keys)}
    return schema


def parse_output(
    payload, pass_name, revision_id, page_count, selected, scope, package_ref=None, key_prefix="0"
):
    def required(node, value, loc=()):
        if "$ref" in node:
            return required(schema["$defs"][node["$ref"].split("/")[-1]], value, loc)
        if node.get("type") == "object" and isinstance(value, dict):
            if set(value) != set(node["properties"]):
                missing = sorted(set(node["properties"]) - set(value))
                extra = sorted(set(value) - set(node["properties"]))
                key = missing[0] if missing else extra[0]
                raise validation_error(
                    "Provider object has missing or unknown schema properties",
                    loc + (key,),
                    "missing" if missing else "extra_forbidden",
                )
            if (
                "availability" in node["properties"]
                and value.get("availability") == "PRESENT"
                and value.get("evidence") == []
            ):
                raise validation_error(
                    "Present values require evidence", loc + ("evidence",), "evidence_missing"
                )
            for key, item in value.items():
                required(node["properties"][key], item, loc + (key,))
        if node.get("type") == "array" and isinstance(value, list):
            for index, item in enumerate(value):
                required(node["items"], item, loc + (index,))
        if isinstance(value, dict):
            for variant in node.get("anyOf", []):
                if "$ref" in variant or variant.get("type") == "object":
                    required(variant, value, loc)

    schema = wire_schema(pass_name)
    required(schema, payload)
    if pass_name == "pins":
        output = MinimalPinsOutput.model_validate(payload)
        if output.source_revision_id != revision_id:
            raise validation_error(
                "Provider revision mismatch", ("source_revision_id",), "wrong_revision"
            )
        if not package_ref:
            raise validation_error("Package reference is missing", ("pins",), "invalid_reference")
        entities = []
        for index, pin in enumerate(output.pins):
            loc = ("pins", index)
            if pin.source_page not in selected:
                raise validation_error(
                    "Pin source page is not selected", loc + ("source_page",), "evidence_page_not_selected"
                )
            if pin.availability == "PRESENT":
                for key, value in (("pin_number", pin.pin_number), ("pin_name", pin.pin_name)):
                    if not resolves_native_evidence(value, selected[pin.source_page]):
                        raise validation_error(
                            "Evidence does not resolve to selected native page text",
                            loc + (key,),
                            "evidence_quote_unresolved",
                        )
            availability = pin.availability
            number_evidence = (
                [
                    Evidence(
                        source_revision_id=revision_id,
                        page_number=pin.source_page,
                        source_text=pin.pin_number,
                        locator_method="TABLE",
                        locator_version="native-selection/1",
                        evidence_role="DIRECT",
                    )
                ]
                if availability == "PRESENT"
                else []
            )
            name_evidence = (
                [
                    Evidence(
                        source_revision_id=revision_id,
                        page_number=pin.source_page,
                        source_text=pin.pin_name,
                        locator_method="TABLE",
                        locator_version="native-selection/1",
                        evidence_role="DIRECT",
                    )
                ]
                if availability == "PRESENT"
                else []
            )
            entities.append(
                Entity(
                    local_key=f"pin_{key_prefix}_{index}",
                    kind="PIN",
                    scope_key=scope,
                    fields=[
                        Claim(
                            key="number",
                            value=pin.pin_number,
                            availability=availability,
                            evidence=number_evidence,
                        ),
                        Claim(
                            key="source_name",
                            value=pin.pin_name,
                            availability=availability,
                            evidence=name_evidence,
                        ),
                        Claim(key="primary_function", availability="NOT_FOUND"),
                        Claim(key="electrical_type", availability="NOT_FOUND"),
                        Claim(
                            key="package_ref",
                            value=package_ref if availability == "PRESENT" else None,
                            availability=availability,
                            evidence=number_evidence,
                            transformation="server-assigned package scope",
                        ),
                        Claim(
                            key="is_exposed_pad",
                            value=(
                                is_exposed_pad_identifier(pin.pin_number)
                                if availability == "PRESENT"
                                else None
                            ),
                            availability=availability,
                            evidence=number_evidence,
                            transformation="exact exposed-pad identifier classification",
                        ),
                    ],
                )
            )
        return entities
    output = PassOutput.model_validate(payload)
    if output.source_revision_id != revision_id:
        raise validation_error(
            "Provider revision mismatch", ("source_revision_id",), "wrong_revision"
        )
    allowed = wire_schema(pass_name)["$defs"]["WireClaim"]["properties"]["key"]["enum"]
    entities = []
    for entity_index, wire in enumerate(output.entities):
        entity_loc = ("entities", entity_index)
        if wire.kind not in PASS_KINDS[pass_name] or wire.scope_key != scope:
            raise validation_error(
                "Wrong pass kind or package scope", entity_loc, "wrong_pass_or_scope"
            )
        try:
            entity = Entity.model_validate(wire.model_dump())
        except ValueError as error:
            raise prefix_validation(error, entity_loc)
        for field_index, claim in enumerate(entity.fields):
            field_loc = entity_loc + ("fields", field_index)
            if claim.key not in allowed:
                raise validation_error("Unknown field key", field_loc + ("key",), "unknown_field")
            try:
                field_type(entity.kind, claim.key)
                validate_claim(entity.kind, claim, revision_id, page_count)
            except ValueError as error:
                raise prefix_validation(error, field_loc)
            for evidence_index, evidence in enumerate(claim.evidence):
                evidence_loc = field_loc + ("evidence", evidence_index)
                message = "Evidence does not resolve to selected native page text"
                if evidence.locator_method not in ("TEXT", "TABLE") or evidence.region is not None:
                    raise validation_error(message, evidence_loc, "evidence_locator_unsupported")
                if not evidence.source_text:
                    raise validation_error(
                        message, evidence_loc + ("source_text",), "evidence_missing"
                    )
                if evidence.page_number not in selected:
                    raise validation_error(
                        message, evidence_loc + ("page_number",), "evidence_page_not_selected"
                    )
                if not resolves_native_evidence(
                    evidence.source_text, selected[evidence.page_number]
                ):
                    raise validation_error(
                        message, evidence_loc + ("source_text",), "evidence_quote_unresolved"
                    )
        entities.append(entity)
    return entities
