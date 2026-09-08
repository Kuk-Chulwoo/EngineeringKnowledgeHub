"""Versioned, provider-independent candidate schema and deterministic engineering rules."""

import hashlib
import json
import re
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    region: Region | None = None
    locator_method: Literal["TEXT", "TABLE", "OCR", "VISION"] = "TEXT"
    locator_version: str = Field(min_length=1, max_length=100)
    evidence_role: Literal["DIRECT", "CONTEXT"] = "DIRECT"

    @model_validator(mode="after")
    def supported(self) -> "Evidence":
        if not (self.source_text and self.source_text.strip()) and self.region is None:
            raise ValueError("Evidence requires text or region")
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


class CandidateSet(StrictModel):
    schema_version: Literal["engineering-extraction/0.1"] = SCHEMA_VERSION
    source_revision_id: int = Field(gt=0)
    provenance: Provenance
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
    raise ValueError(f"Unsupported field {kind}.{key}")


def validate_claim(kind: str, claim: Claim, revision_id: int, page_count: int) -> None:
    value_type = field_type(kind, claim.key)
    for evidence in claim.evidence:
        if evidence.source_revision_id != revision_id:
            raise ValueError("Evidence belongs to another revision")
        if evidence.page_number > page_count:
            raise ValueError("Evidence page outside original PDF")
    if claim.availability != "PRESENT":
        return
    value = claim.value
    if value_type in ("text", "reference", "enum"):
        if type(value) is not str or not value.strip() or len(value) > 2000:
            raise ValueError(f"{claim.key} requires nonempty text")
        if value_type == "enum" and value not in ENUMS[claim.key]:
            raise ValueError(f"Unsupported {claim.key} value")
    elif value_type == "count":
        if type(value) is not int or not 1 <= value <= 2000:
            raise ValueError("lead_count requires positive integer")
    elif value_type == "bool":
        if type(value) is not bool:
            raise ValueError(f"{claim.key} requires a boolean")
    else:
        Quantity.model_validate(value)


def values(entity: Entity) -> dict[str, Any]:
    return {claim.key: claim.value for claim in entity.fields if claim.availability == "PRESENT"}


def validate_candidates(data: CandidateSet, revision_id: int, page_count: int) -> list[str]:
    if data.source_revision_id != revision_id:
        raise ValueError("Candidate source revision mismatch")
    entities = {entity.local_key: entity for entity in data.entities}
    if len(entities) != len(data.entities):
        raise ValueError("Duplicate entity keys")
    if sum(e.kind == "COMPONENT_IDENTITY" for e in data.entities) != 1:
        raise ValueError("Exactly one component identity required")
    packages = [e for e in data.entities if e.kind == "PACKAGE"]
    if not packages:
        raise ValueError("Package coverage is missing")
    warnings: list[str] = []
    for entity in data.entities:
        keys = [claim.key for claim in entity.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate claims")
        if REQUIRED[entity.kind] - set(keys):
            raise ValueError(f"Missing required claim slots for {entity.local_key}")
        for claim in entity.fields:
            validate_claim(entity.kind, claim, revision_id, page_count)
            if claim.availability != "PRESENT":
                warnings.append(f"{entity.local_key}.{claim.key}: {claim.availability}")
            elif field_type(entity.kind, claim.key) == "reference":
                target = entities.get(claim.value)
                if target is None or target.kind != REFS[claim.key]:
                    raise ValueError("Reference target missing or wrong kind")
                if target.scope_key != entity.scope_key:
                    raise ValueError("Package scope mismatch")
        v = values(entity)
        if entity.kind == "PACKAGE":
            for name in ("body_length", "body_width", "body_height", "pitch"):
                bounds = [
                    Decimal(v[f"{name}.{bound}"]["decimal"])
                    for bound in ("minimum", "nominal", "maximum")
                    if f"{name}.{bound}" in v
                ]
                if bounds != sorted(bounds):
                    raise ValueError("Dimension minimum <= nominal <= maximum violated")
        if entity.kind == "INTERFACE_PIN" and "pin_ref" in v and "interface_ref" in v:
            pin = values(entities[v["pin_ref"]])
            interface = values(entities[v["interface_ref"]])
            if pin.get("package_ref") != interface.get("package_ref"):
                raise ValueError("Interface membership crosses packages")
    membership: set[tuple[str, str, str, str]] = set()
    for entity in data.entities:
        if entity.kind == "INTERFACE_PIN":
            v = values(entity)
            pair = (
                v.get("pin_ref", ""),
                v.get("interface_ref", ""),
                v.get("role", ""),
                v.get("mode", ""),
            )
            if pair in membership:
                raise ValueError("Duplicate interface membership")
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
            raise ValueError("Duplicate pin designators")
        if any("number" not in p or "is_exposed_pad" not in p for p in pins):
            warnings.append(f"{package.local_key}: incomplete pin identities")
            continue
        exposed = [p for p in pins if p.get("is_exposed_pad")]
        if "exposed_pad_present" in pv and pv["exposed_pad_present"] != bool(exposed):
            raise ValueError("Exposed pad presence and pin table disagree")
        basis = pv.get("pin_count_basis")
        if basis == "UNSPECIFIED" or "lead_count" not in pv:
            warnings.append(f"{package.local_key}: pin count basis/count unresolved")
        else:
            count = len(pins) - len(exposed) if basis == "LEADS_ONLY" else len(pins)
            if count != pv["lead_count"]:
                raise ValueError("Pin count mismatch: missing or extra pins")
    return warnings
