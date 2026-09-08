from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ComponentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    manufacturer: ShortText
    part_number: ShortText
    description: Annotated[str, StringConstraints(max_length=4000)] = ""
    category: Annotated[str, StringConstraints(max_length=200)] = ""
    package: Annotated[str, StringConstraints(max_length=200)] = ""


class Component(ComponentCreate):
    id: int
    created_at: str


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


class ComponentList(BaseModel):
    items: list[Component]
    total: int
    limit: int
    offset: int
