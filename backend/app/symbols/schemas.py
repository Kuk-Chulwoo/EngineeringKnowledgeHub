from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CadTool = Literal["PADS_LOGIC"]
SourceType = Literal[
    "EXISTING_COMPANY_LIBRARY",
    "MANUFACTURER_LIBRARY",
    "ENGINEER_CREATED",
    "IMPORTED_VENDOR_LIBRARY",
]
Lifecycle = Literal["DRAFT", "VALIDATED", "ENGINEER_APPROVED", "RELEASED"]
PinValidation = Literal["NOT_CHECKED", "ENGINEER_REVIEWED"]


class SymbolCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cad_tool: CadTool
    cad_version: Text
    symbol_name: Text
    source_type: SourceType
    revision: Text
    notes: Annotated[str, StringConstraints(max_length=4000)] = ""


class SymbolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cad_tool: CadTool | None = None
    cad_version: Text | None = None
    symbol_name: Text | None = None
    source_type: SourceType | None = None
    revision: Text | None = None
    notes: Annotated[str | None, StringConstraints(max_length=4000)] = None

    @model_validator(mode="after")
    def require_non_null_field(self) -> "SymbolUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one symbol metadata field is required")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Symbol metadata cannot be null")
        return self


class SymbolLifecycleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Lifecycle


class PinValidationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: PinValidation


class SchematicSymbol(SymbolCreate):
    model_config = ConfigDict(extra="ignore")
    id: int
    component_id: int
    source_filename: str | None
    lifecycle_status: Lifecycle
    pin_validation_status: PinValidation
    size_bytes: int | None
    sha256: str | None
    created_at: str
    updated_at: str
