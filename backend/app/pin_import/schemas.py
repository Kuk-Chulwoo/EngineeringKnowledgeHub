from typing import Literal

from pydantic import BaseModel

from ..schemas import PinIdentity


class PinImportIssue(BaseModel):
    code: str
    row: int | None = None
    field: str | None = None
    message: str


class PinImportPreview(BaseModel):
    filename: str
    format: Literal["csv", "xlsx"] | None
    valid: bool
    count: int
    errors: list[PinImportIssue]
    warnings: list[PinImportIssue]
    pins: list[PinIdentity]
