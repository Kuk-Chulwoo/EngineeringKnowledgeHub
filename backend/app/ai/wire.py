"""Strict transport subset of engineering-extraction/0.1, validated again locally."""

from typing import Literal

from pydantic import Field

from ..engineering.schema import (
    REQUIRED,
    TEXT,
    Claim,
    Entity,
    Quantity,
    StrictModel,
    field_type,
    validate_claim,
)
from .parsing import normalized


class WireClaim(Claim):
    value: str | int | bool | Quantity | None = None


class WireEntity(Entity):
    fields: list[WireClaim] = Field(min_length=1, max_length=100)


class PassOutput(StrictModel):
    schema_version: Literal["engineering-extraction/0.1"]
    source_revision_id: int = Field(gt=0)
    entities: list[WireEntity] = Field(max_length=2000)


PASS_KINDS = {
    "identity": ["COMPONENT_IDENTITY"],
    "package": ["PACKAGE"],
    "pins": ["PIN"],
    "interfaces": ["INTERFACE", "INTERFACE_PIN"],
}


def wire_schema(pass_name: str):
    schema = PassOutput.model_json_schema()

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


def parse_output(payload, pass_name, revision_id, page_count, selected, scope):
    def required(node, value):
        if "$ref" in node:
            return required(schema["$defs"][node["$ref"].split("/")[-1]], value)
        if node.get("type") == "object" and isinstance(value, dict):
            if set(value) != set(node["properties"]):
                raise ValueError("Provider object has missing or unknown schema properties")
            for key, item in value.items():
                required(node["properties"][key], item)
        if node.get("type") == "array" and isinstance(value, list):
            for item in value:
                required(node["items"], item)
        if isinstance(value, dict):
            for variant in node.get("anyOf", []):
                if "$ref" in variant or variant.get("type") == "object":
                    required(variant, value)

    schema = wire_schema(pass_name)
    required(schema, payload)
    output = PassOutput.model_validate(payload)
    if output.source_revision_id != revision_id:
        raise ValueError("Provider revision mismatch")
    allowed = wire_schema(pass_name)["$defs"]["WireClaim"]["properties"]["key"]["enum"]
    entities = []
    for wire in output.entities:
        if wire.kind not in PASS_KINDS[pass_name] or wire.scope_key != scope:
            raise ValueError("Wrong pass kind or package scope")
        entity = Entity.model_validate(wire.model_dump())
        for claim in entity.fields:
            if claim.key not in allowed:
                raise ValueError("Unknown field key")
            field_type(entity.kind, claim.key)
            validate_claim(entity.kind, claim, revision_id, page_count)
            for evidence in claim.evidence:
                if (
                    evidence.locator_method not in ("TEXT", "TABLE")
                    or evidence.region is not None
                    or not evidence.source_text
                    or evidence.page_number not in selected
                    or normalized(evidence.source_text)
                    not in normalized(selected[evidence.page_number])
                ):
                    raise ValueError("Evidence does not resolve to selected native page text")
        entities.append(entity)
    return entities
