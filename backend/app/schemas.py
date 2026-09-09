from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalShortText = Annotated[
    str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
LifecycleStatus = Literal["DRAFT", "VALIDATED", "ENGINEER_APPROVED", "RELEASED"]
PinSourceType = Literal["AI_EXTRACTED", "USER_IMPORT", "MANUAL"]


class ComponentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    manufacturer: ShortText
    part_number: ShortText
    description: Annotated[str, StringConstraints(max_length=4000)] = ""
    category: Annotated[str, StringConstraints(max_length=200)] = ""
    package: Annotated[str, StringConstraints(max_length=200)] = ""
    internal_part_number: OptionalShortText = None


class Component(ComponentCreate):
    id: int
    lifecycle_status: LifecycleStatus
    created_at: str
    updated_at: str


class ComponentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    internal_part_number: OptionalShortText = None
    manufacturer: ShortText | None = None
    part_number: ShortText | None = None
    description: Annotated[str | None, StringConstraints(max_length=4000)] = None
    category: Annotated[str | None, StringConstraints(max_length=200)] = None
    package: Annotated[str | None, StringConstraints(max_length=200)] = None

    @model_validator(mode="after")
    def not_empty(self) -> "ComponentUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one metadata field is required")
        for field in self.model_fields_set - {"internal_part_number"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class LifecycleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: LifecycleStatus


class PinIdentity(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", strict=True)
    pin_number: ShortText
    pin_name: ShortText


class PinTableReplace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_type: PinSourceType
    pins: list[PinIdentity]


class ComponentPin(PinIdentity):
    id: int
    component_id: int
    source_type: PinSourceType
    source_run_id: int | None
    source_revision_id: int | None
    created_at: str
    updated_at: str


class PinTable(BaseModel):
    source_type: PinSourceType | None
    count: int
    pins: list[ComponentPin]


class PinSummary(BaseModel):
    count: int
    source_type: PinSourceType | None


class Revision(BaseModel):
    id: int
    document_id: int
    revision: str
    datasheet_date: date | None
    filename: str
    uploaded_at: str
    size_bytes: int
    sha256: str


class Document(BaseModel):
    id: int
    component_id: int
    title: str
    revisions: list[Revision]


class ComponentDetail(Component):
    documents: list[Document]
    pin_summary: PinSummary


class ComponentList(BaseModel):
    items: list[Component]
    total: int
    limit: int
    offset: int
