import sqlite3
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any, BinaryIO, ClassVar

from pypdf import PdfReader

from .repository import Repository
from .schemas import ComponentCreate, ComponentUpdate, LifecycleUpdate, PinTableReplace
from .storage import Storage, UploadTooLarge


class ServiceError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class HubService:
    lifecycle_transitions: ClassVar[dict[str, set[str]]] = {
        "DRAFT": {"VALIDATED"},
        "VALIDATED": {"DRAFT", "ENGINEER_APPROVED"},
        "ENGINEER_APPROVED": {"VALIDATED", "RELEASED"},
        "RELEASED": {"ENGINEER_APPROVED"},
    }
    def __init__(self, repository: Repository, storage: Storage, max_upload_bytes: int):
        self.repository = repository
        self.storage = storage
        self.max_upload_bytes = max_upload_bytes

    def create_component(self, payload: ComponentCreate) -> dict[str, Any]:
        timestamp = utc_now()
        try:
            return self.repository.create_component(
                {**payload.model_dump(), "created_at": timestamp, "updated_at": timestamp}
            )
        except sqlite3.IntegrityError as error:
            raise ServiceError(409, "This company part already exists") from error

    def component(self, component_id: int) -> dict[str, Any]:
        component = self.repository.component(component_id)
        if component is None:
            raise ServiceError(404, "Component not found")
        return component

    def update_component(self, component_id: int, payload: ComponentUpdate) -> dict[str, Any]:
        self.component(component_id)
        values = payload.model_dump(exclude_unset=True)
        values["updated_at"] = utc_now()
        try:
            updated = self.repository.update_component(component_id, values)
        except sqlite3.IntegrityError as error:
            raise ServiceError(409, "This company part already exists") from error
        if updated is None:
            raise ServiceError(404, "Component not found")
        return self.component(component_id)

    def update_lifecycle(self, component_id: int, payload: LifecycleUpdate) -> dict[str, Any]:
        component = self.component(component_id)
        current, target = component["lifecycle_status"], payload.status
        if target not in self.lifecycle_transitions[current]:
            raise ServiceError(409, f"Lifecycle transition from {current} to {target} is not allowed")
        if target == "RELEASED":
            missing = self.release_eligibility_errors(component)
            if missing:
                raise ServiceError(409, "Release requires: " + ", ".join(missing))
        if self.repository.transition_lifecycle(component_id, current, target, utc_now()) is None:
            raise ServiceError(409, "Component lifecycle changed; reload and try again")
        return self.component(component_id)

    @staticmethod
    def release_eligibility_errors(component: dict[str, Any]) -> list[str]:
        required = ("manufacturer", "part_number", "description", "category", "package")
        return [field for field in required if not component[field].strip()]

    def pins(self, component_id: int) -> dict[str, Any]:
        self.component(component_id)
        pins = self.repository.pins(component_id)
        sources = {pin["source_type"] for pin in pins}
        return {"source_type": next(iter(sources)) if len(sources) == 1 else None,
                "count": len(pins), "pins": pins}

    def replace_pins(self, component_id: int, payload: PinTableReplace) -> dict[str, Any]:
        self.component(component_id)
        pins = [pin.model_dump() for pin in payload.pins]
        numbers = [pin["pin_number"].casefold() for pin in pins]
        if len(numbers) != len(set(numbers)):
            raise ServiceError(409, "Duplicate pin number")
        try:
            rows = self.repository.replace_pins(component_id, payload.source_type, pins, utc_now())
        except sqlite3.IntegrityError as error:
            raise ServiceError(409, "Pin table replacement violates component constraints") from error
        return {"source_type": payload.source_type if rows else None, "count": len(rows), "pins": rows}

    def upload(
        self,
        component_id: int,
        title: str,
        revision: str,
        datasheet_date: date | None,
        filename: str,
        source: BinaryIO,
    ) -> dict[str, Any]:
        self.component(component_id)
        title, revision = title.strip(), revision.strip()
        if not title or not revision or len(title) > 200 or len(revision) > 200:
            raise ServiceError(422, "Document title and revision must contain 1–200 characters")
        filename = PurePosixPath(filename.replace("\\", "/")).name
        if (
            not filename.lower().endswith(".pdf")
            or len(filename) > 255
            or any(ord(char) < 32 or ord(char) == 127 for char in filename)
        ):
            raise ServiceError(422, "A valid PDF filename is required")
        source.seek(0, 2)
        if source.tell() > self.max_upload_bytes:
            raise ServiceError(413, "PDF exceeds configured upload limit")
        source.seek(0)
        if source.read(5) != b"%PDF-":
            raise ServiceError(422, "File is not a PDF")
        source.seek(0)
        try:
            reader = PdfReader(source, strict=True)
            if reader.is_encrypted or len(reader.pages) == 0:
                raise ValueError("Encrypted or empty PDF")
        except Exception as error:
            raise ServiceError(422, "PDF is damaged, encrypted, or has no pages") from error
        source.seek(0)
        try:
            stored = self.storage.put(source, self.max_upload_bytes)
        except UploadTooLarge as error:
            raise ServiceError(413, str(error)) from error
        try:
            return self.repository.add_revision(
                component_id,
                title,
                {
                    "revision": revision,
                    "datasheet_date": datasheet_date.isoformat() if datasheet_date else None,
                    "filename": filename,
                    "uploaded_at": utc_now(),
                    "storage_key": stored.key,
                    "size_bytes": stored.size,
                    "sha256": stored.sha256,
                },
            )
        except BaseException as error:
            self.storage.delete(stored.key)
            if isinstance(error, sqlite3.IntegrityError):
                raise ServiceError(409, "This document revision already exists") from error
            raise

    def open_revision(self, revision_id: int) -> tuple[dict[str, Any], BinaryIO]:
        revision = self.repository.revision(revision_id)
        if revision is None:
            raise ServiceError(404, "Revision not found")
        try:
            return revision, self.storage.open(revision["storage_key"])
        except FileNotFoundError as error:
            raise ServiceError(404, "Stored PDF is unavailable; restore it from backup") from error
