"""Versioned, provider-independent candidate schema and deterministic engineering rules."""

import hashlib
import json
import re
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .validation_errors import prefix_validation, validation_error

SCHEMA_VERSION = "engineering-extraction/0.1"


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReviewStatus(StrEnum):
    AI_EXTRACTED = "AI_EXTRACTED"
    AI_CHECKED = "AI_CHECKED"
    ENGINEER_DRAFT = "ENGINEER_DRAFT"
    ENGINEER_APPROVED = "ENGINEER_APPROVED"
    ENGINEER_REJECTED = "ENGINEER_REJECTED"


class Region(StrictModel):
    x0: float = Field(ge=0, le=1, allow_inf_nan=False)
    y0: float = Field(ge=0, le=1, allow_inf_nan=False)
    x1: float = Field(ge=0, le=1, allow_inf_nan=False)
    y1: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> "Region":
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("Region must have positive area")
        return self


class Evidence(StrictModel):
    source_revision_id: int = Field(gt=0)
    page_number: int = Field(gt=0)
    printed_page_label: str | None = Field(default=None, max_length=100)
    source_text: str | None = Field(default=None, min_length=1, max_length=2048)
    source_text_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    region: Region | None = None
    locator_method: Literal["TEXT", "TABLE", "OCR", "VISION"] = "TEXT"
    locator_version: str = Field(min_length=1, max_length=100)
    evidence_role: Literal["DIRECT", "CONTEXT"] = "DIRECT"

    @model_validator(mode="after")
    def supported(self) -> "Evidence":
        if not (self.source_text and self.source_text.strip()) and self.region is None:
            raise ValueError("Evidence requires text or region")
        if self.source_text:
            expected = hashlib.sha256(self.source_text.encode()).hexdigest()
            if self.source_text_sha256 is not None and self.source_text_sha256 != expected:
                raise ValueError("Source text hash mismatch")
            self.source_text_sha256 = expected
        elif self.source_text_sha256 is not None:
            raise ValueError("Source text hash requires text")
        return self


class Quantity(StrictModel):
    decimal: str = Field(pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,9})?$")
    unit: Literal["mm"] = "mm"

    @model_validator(mode="after")
    def positive(self) -> "Quantity":
        if Decimal(self.decimal) <= 0:
            raise ValueError("Package dimensions must be positive")
        return self


class Claim(StrictModel):
    key: str = Field(min_length=1, max_length=100)
    value: Any = None
    availability: Literal["PRESENT", "NOT_FOUND", "AMBIGUOUS", "NOT_APPLICABLE"] = "PRESENT"
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    confidence_basis: Literal["MODEL_SELF_REPORT", "CHECKER_ESTIMATE", "NOT_PROVIDED"] = (
        "NOT_PROVIDED"
    )
    evidence: list[Evidence] = Field(default_factory=list, max_length=16)
    transformation: str | None = Field(default=None, max_length=1000)
    review_status: Literal["AI_EXTRACTED"] = "AI_EXTRACTED"

    @model_validator(mode="after")
    def available(self) -> "Claim":
        if self.availability == "PRESENT":
            if self.value is None or not self.evidence:
                raise ValueError("Present values require evidence")
        elif self.value is not None:
            raise ValueError("Unavailable claims must have null values")
        if (self.confidence is None) != (self.confidence_basis == "NOT_PROVIDED"):
            raise ValueError("Confidence and its basis must agree")
        return self


Kind = Literal["COMPONENT_IDENTITY", "PACKAGE", "PIN", "INTERFACE", "INTERFACE_PIN"]


class Entity(StrictModel):
    local_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    kind: Kind
    scope_key: str = Field(min_length=1, max_length=100)
    fields: list[Claim] = Field(min_length=1, max_length=100)


class Provenance(StrictModel):
    pipeline_version: str = Field(min_length=1, max_length=100)
    parser_version: str = Field(min_length=1, max_length=100)
    provider: Literal["synthetic"]
    model_identifier: Literal["none-synthetic"]
    model_version: str = Field(min_length=1, max_length=100)
    prompt_version: Literal["not-applicable"]
    synthetic: Literal[True] = True


class PassProvenance(StrictModel):
    pass_name: Literal["identity", "package", "pins", "interfaces"]
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, max_length=100)
    model_version: str | None = Field(max_length=200)
    selected_pages: list[int]
    selected_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    truncated_pages: list[int]


class RealProvenance(StrictModel):
    pipeline_version: Literal["native-focused/1"] = "native-focused/1"
    parser_version: str = Field(min_length=1, max_length=100)
    provider: Literal["openai"] = "openai"
    model_identifier: str = Field(min_length=1, max_length=200)
    model_version: str | None = None
    prompt_version: str = Field(min_length=1, max_length=100)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_settings: dict
    external_transmission_authorized: Literal[True]
    synthetic: Literal[False] = False
    passes: list[PassProvenance] = Field(default_factory=list, max_length=4)


class CandidateSet(StrictModel):
    schema_version: Literal["engineering-extraction/0.1"] = SCHEMA_VERSION
    source_revision_id: int = Field(gt=0)
    provenance: Provenance | RealProvenance
    entities: list[Entity] = Field(min_length=1, max_length=2000)


TEXT = {
    "COMPONENT_IDENTITY": {"manufacturer", "part_number", "description"},
    "PACKAGE": {"family", "type", "manufacturer_package_code", "variant_selector"},
    "PIN": {"number", "source_name", "normalized_name", "primary_function", "functional_group"},
    "INTERFACE": {"name", "function"},
    "INTERFACE_PIN": {"role", "mode"},
}
ENUMS = {
    "pin_count_basis": {"LEADS_ONLY", "INCLUDING_EXPOSED_PAD", "UNSPECIFIED"},
    "electrical_type": {
        "INPUT",
        "OUTPUT",
        "BIDIRECTIONAL",
        "POWER_IN",
        "POWER_OUT",
        "GROUND",
        "PASSIVE",
        "OPEN_DRAIN",
        "NO_CONNECT",
        "OTHER",
        "UNKNOWN",
    },
    "kind": {"SPI", "UART", "I2C", "GPIO", "RF", "POWER", "ANALOG", "CLOCK_RESET", "OTHER"},
}
REQUIRED = {
    "COMPONENT_IDENTITY": {"manufacturer", "part_number", "description"},
    "PACKAGE": {
        "family",
        "manufacturer_package_code",
        "lead_count",
        "pin_count_basis",
        "exposed_pad_present",
        "variant_selector",
    },
    "PIN": {
        "number",
        "source_name",
        "primary_function",
        "electrical_type",
        "package_ref",
        "is_exposed_pad",
    },
    "INTERFACE": {"kind", "name", "package_ref"},
    "INTERFACE_PIN": {"interface_ref", "pin_ref", "role"},
}
REFS = {"package_ref": "PACKAGE", "interface_ref": "INTERFACE", "pin_ref": "PIN"}
QUANTITY_KEY = re.compile(
    r"^(body_length|body_width|body_height|pitch)\.(minimum|nominal|maximum)$"
)


def field_type(kind: str, key: str) -> str:
    if key in TEXT[kind] or (
        kind == "PIN" and re.fullmatch(r"alternate_function\.[a-z0-9_-]+", key)
    ):
        return "text"
    if kind == "PACKAGE" and QUANTITY_KEY.fullmatch(key):
        return "quantity"
    if (kind, key) in {("PACKAGE", "exposed_pad_present"), ("PIN", "is_exposed_pad")}:
        return "bool"
    if kind == "PACKAGE" and key == "lead_count":
        return "count"
    if (kind, key) in {
        ("PACKAGE", "pin_count_basis"),
        ("PIN", "electrical_type"),
        ("INTERFACE", "kind"),
    }:
        return "enum"
    if (kind in ("PIN", "INTERFACE") and key == "package_ref") or (
        kind == "INTERFACE_PIN" and key in ("pin_ref", "interface_ref")
    ):
        return "reference"
    raise validation_error(f"Unsupported field {kind}.{key}", ("key",), "unknown_field")


def validate_claim(kind: str, claim: Claim, revision_id: int, page_count: int) -> None:
    value_type = field_type(kind, claim.key)
    for evidence_index, evidence in enumerate(claim.evidence):
        if evidence.source_revision_id != revision_id:
            raise validation_error(
                "Evidence belongs to another revision",
                ("evidence", evidence_index, "source_revision_id"),
                "evidence_wrong_revision",
            )
        if evidence.page_number > page_count:
            raise validation_error(
                "Evidence page outside original PDF",
                ("evidence", evidence_index, "page_number"),
                "evidence_page_out_of_range",
            )
    if claim.availability != "PRESENT":
        return
    value = claim.value
    if value_type in ("text", "reference", "enum"):
        if type(value) is not str or not value.strip() or len(value) > 2000:
            raise validation_error(
                f"{claim.key} requires nonempty text", ("value",), "invalid_text"
            )
        if value_type == "enum" and value not in ENUMS[claim.key]:
            raise validation_error(f"Unsupported {claim.key} value", ("value",), "invalid_enum")
    elif value_type == "count":
        if type(value) is not int or not 1 <= value <= 2000:
            raise validation_error(
                "lead_count requires positive integer", ("value",), "invalid_count"
            )
    elif value_type == "bool":
        if type(value) is not bool:
            raise validation_error(f"{claim.key} requires a boolean", ("value",), "invalid_boolean")
    else:
        try:
            Quantity.model_validate(value)
        except ValueError as error:
            raise prefix_validation(error, ("value",))


def values(entity: Entity) -> dict[str, Any]:
    return {claim.key: claim.value for claim in entity.fields if claim.availability == "PRESENT"}


def validate_candidates(data: CandidateSet, revision_id: int, page_count: int) -> list[str]:
    if data.source_revision_id != revision_id:
        raise validation_error(
            "Candidate source revision mismatch", ("source_revision_id",), "wrong_revision"
        )
    entities = {entity.local_key: entity for entity in data.entities}
    if len(entities) != len(data.entities):
        raise validation_error("Duplicate entity keys", ("entities",), "duplicate_entity")
    if sum(e.kind == "COMPONENT_IDENTITY" for e in data.entities) != 1:
        raise validation_error(
            "Exactly one component identity required", ("entities",), "identity_count"
        )
    packages = [e for e in data.entities if e.kind == "PACKAGE"]
    if not packages:
        raise validation_error("Package coverage is missing", ("entities",), "package_missing")
    warnings: list[str] = []
    for entity_index, entity in enumerate(data.entities):
        entity_loc = ("entities", entity_index)
        keys = [claim.key for claim in entity.fields]
        if len(keys) != len(set(keys)):
            raise validation_error("Duplicate claims", entity_loc + ("fields",), "duplicate_claim")
        if REQUIRED[entity.kind] - set(keys):
            raise validation_error(
                f"Missing required claim slots for {entity.local_key}",
                entity_loc + ("fields",),
                "missing",
            )
        for field_index, claim in enumerate(entity.fields):
            field_loc = entity_loc + ("fields", field_index)
            try:
                validate_claim(entity.kind, claim, revision_id, page_count)
            except ValueError as error:
                raise prefix_validation(error, field_loc)
            if claim.availability != "PRESENT":
                warnings.append(f"{entity.local_key}.{claim.key}: {claim.availability}")
            elif field_type(entity.kind, claim.key) == "reference":
                target = entities.get(claim.value)
                if target is None or target.kind != REFS[claim.key]:
                    raise validation_error(
                        "Reference target missing or wrong kind",
                        field_loc + ("value",),
                        "invalid_reference",
                    )
                if target.scope_key != entity.scope_key:
                    raise validation_error(
                        "Package scope mismatch", field_loc + ("value",), "scope_mismatch"
                    )
        v = values(entity)
        if entity.kind == "PACKAGE":
            for name in ("body_length", "body_width", "body_height", "pitch"):
                bounds = [
                    Decimal(v[f"{name}.{bound}"]["decimal"])
                    for bound in ("minimum", "nominal", "maximum")
                    if f"{name}.{bound}" in v
                ]
                if bounds != sorted(bounds):
                    raise validation_error(
                        "Dimension minimum <= nominal <= maximum violated",
                        entity_loc + ("fields",),
                        "dimension_order",
                    )
        if entity.kind == "INTERFACE_PIN" and "pin_ref" in v and "interface_ref" in v:
            pin = values(entities[v["pin_ref"]])
            interface = values(entities[v["interface_ref"]])
            if pin.get("package_ref") != interface.get("package_ref"):
                raise validation_error(
                    "Interface membership crosses packages",
                    entity_loc + ("fields",),
                    "membership_scope_mismatch",
                )
    membership: set[tuple[str, str, str, str]] = set()
    for entity_index, entity in enumerate(data.entities):
        entity_loc = ("entities", entity_index)
        if entity.kind == "INTERFACE_PIN":
            v = values(entity)
            pair = (
                v.get("pin_ref", ""),
                v.get("interface_ref", ""),
                v.get("role", ""),
                v.get("mode", ""),
            )
            if pair in membership:
                raise validation_error(
                    "Duplicate interface membership", entity_loc, "duplicate_membership"
                )
            membership.add(pair)
    for package in packages:
        pv = values(package)
        pins = [
            values(e)
            for e in data.entities
            if e.kind == "PIN" and values(e).get("package_ref") == package.local_key
        ]
        designators = [p["number"].strip().casefold() for p in pins if "number" in p]
        if len(designators) != len(set(designators)):
            raise validation_error("Duplicate pin designators", ("entities",), "duplicate_pin")
        if any("number" not in p or "is_exposed_pad" not in p for p in pins):
            warnings.append(f"{package.local_key}: incomplete pin identities")
            continue
        exposed = [p for p in pins if p.get("is_exposed_pad")]
        if "exposed_pad_present" in pv and pv["exposed_pad_present"] != bool(exposed):
            raise validation_error(
                "Exposed pad presence and pin table disagree", ("entities",), "exposed_pad_mismatch"
            )
        basis = pv.get("pin_count_basis")
        if basis == "UNSPECIFIED" or "lead_count" not in pv:
            warnings.append(f"{package.local_key}: pin count basis/count unresolved")
        else:
            count = len(pins) - len(exposed) if basis == "LEADS_ONLY" else len(pins)
            if count != pv["lead_count"]:
                raise validation_error(
                    "Pin count mismatch: missing or extra pins", ("entities",), "pin_count_mismatch"
                )
    return warnings
