import sqlite3
from pathlib import PurePosixPath
from typing import Any, BinaryIO, ClassVar

from ..services import HubService, ServiceError, utc_now
from .repository import SymbolRepository
from .schemas import (
    PinValidationUpdate,
    SymbolCreate,
    SymbolLifecycleUpdate,
    SymbolUpdate,
)
from .storage import MAX_SYMBOL_BYTES, SymbolStorage


class SymbolService:
    transitions: ClassVar[dict[str, set[str]]] = {
        "DRAFT": {"VALIDATED"},
        "VALIDATED": {"DRAFT", "ENGINEER_APPROVED"},
        "ENGINEER_APPROVED": {"VALIDATED", "RELEASED"},
        "RELEASED": {"ENGINEER_APPROVED"},
    }

    def __init__(self, repository: SymbolRepository, storage: SymbolStorage, hub: HubService):
        self.repository = repository
        self.storage = storage
        self.hub = hub

    def create(self, component_id: int, payload: SymbolCreate) -> dict[str, Any]:
        self.hub.component(component_id)
        timestamp = utc_now()
        try:
            return self.repository.create(
                component_id,
                {**payload.model_dump(), "created_at": timestamp, "updated_at": timestamp},
            )
        except sqlite3.IntegrityError as error:
            raise ServiceError(409, "This schematic symbol revision already exists") from error

    def list_for_component(self, component_id: int) -> list[dict[str, Any]]:
        self.hub.component(component_id)
        return self.repository.list_for_component(component_id)

    def get(self, symbol_id: int) -> dict[str, Any]:
        symbol = self.repository.get(symbol_id)
        if symbol is None:
            raise ServiceError(404, "Schematic symbol not found")
        return symbol

    def update(self, symbol_id: int, payload: SymbolUpdate) -> dict[str, Any]:
        self.get(symbol_id)
        try:
            updated = self.repository.update(
                symbol_id, {**payload.model_dump(exclude_unset=True), "updated_at": utc_now()}
            )
        except sqlite3.IntegrityError as error:
            raise ServiceError(409, "This schematic symbol revision already exists") from error
        if updated is None:
            raise ServiceError(404, "Schematic symbol not found")
        return updated

    def upload_file(
        self, symbol_id: int, filename: str, source: BinaryIO
    ) -> dict[str, Any]:
        symbol = self.get(symbol_id)
        if symbol["storage_key"] is not None:
            raise ServiceError(409, "A source file is already attached to this symbol")
        filename = PurePosixPath(filename.replace("\\", "/")).name
        if (
            not filename.lower().endswith(".c")
            or len(filename) > 255
            or any(ord(char) < 32 or ord(char) == 127 for char in filename)
        ):
            raise ServiceError(422, "A valid PADS Logic .c filename is required")
        source.seek(0, 2)
        size = source.tell()
        source.seek(0)
        if size == 0:
            raise ServiceError(422, "Symbol file is empty")
        if size > MAX_SYMBOL_BYTES:
            raise ServiceError(413, "Symbol file exceeds 2 MiB")
        try:
            source.read().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ServiceError(422, "Symbol file must be readable ASCII or UTF-8 text") from error
        source.seek(0)
        try:
            stored = self.storage.put(symbol["component_id"], symbol_id, source)
        except ValueError as error:
            raise ServiceError(413, str(error)) from error
        try:
            attached = self.repository.attach_file(
                symbol_id, filename, stored.key, stored.size, stored.sha256, utc_now()
            )
            if attached is None:
                raise ServiceError(409, "A source file is already attached to this symbol")
            return attached
        except BaseException:
            self.storage.delete(stored.key)
            raise

    def open_file(self, symbol_id: int) -> tuple[dict[str, Any], BinaryIO]:
        symbol = self.get(symbol_id)
        if symbol["storage_key"] is None:
            raise ServiceError(404, "Symbol source file is not attached")
        try:
            return symbol, self.storage.open(symbol["storage_key"])
        except FileNotFoundError as error:
            raise ServiceError(404, "Stored symbol source file is unavailable") from error

    def update_pin_validation(
        self, symbol_id: int, payload: PinValidationUpdate
    ) -> dict[str, Any]:
        self.get(symbol_id)
        updated = self.repository.set_pin_validation(symbol_id, payload.status, utc_now())
        if updated is None:
            raise ServiceError(404, "Schematic symbol not found")
        return updated

    def update_lifecycle(
        self, symbol_id: int, payload: SymbolLifecycleUpdate
    ) -> dict[str, Any]:
        symbol = self.get(symbol_id)
        current, target = symbol["lifecycle_status"], payload.status
        if target not in self.transitions[current]:
            raise ServiceError(409, f"Lifecycle transition from {current} to {target} is not allowed")
        if target == "RELEASED":
            missing = self.release_eligibility_errors(symbol)
            if missing:
                raise ServiceError(409, "Symbol release requires: " + ", ".join(missing))
        updated = self.repository.set_lifecycle(symbol_id, current, target, utc_now())
        if updated is None:
            raise ServiceError(409, "Symbol lifecycle changed; reload and try again")
        return updated

    def release_eligibility_errors(self, symbol: dict[str, Any]) -> list[str]:
        required = ("cad_tool", "cad_version", "symbol_name", "source_type", "revision")
        missing = [field for field in required if not symbol[field].strip()]
        if symbol["storage_key"] is None:
            missing.append("source file")
        if not self.hub.repository.pins(symbol["component_id"]):
            missing.append("canonical pins")
        if symbol["pin_validation_status"] != "ENGINEER_REVIEWED":
            missing.append("engineer pin review")
        return missing
