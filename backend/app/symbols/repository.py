from typing import Any

from ..database import Database


class SymbolRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(self, component_id: int, values: dict[str, Any]) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                """INSERT INTO schematic_symbols
                (component_id,cad_tool,cad_version,symbol_name,source_type,revision,notes,
                 lifecycle_status,pin_validation_status,created_at,updated_at)
                VALUES (:component_id,:cad_tool,:cad_version,:symbol_name,:source_type,:revision,
                 :notes,'DRAFT','NOT_CHECKED',:created_at,:updated_at) RETURNING *""",
                {**values, "component_id": component_id},
            ).fetchone()
            return dict(row)

    def list_for_component(self, component_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """SELECT * FROM schematic_symbols WHERE component_id=?
                    ORDER BY symbol_name COLLATE NOCASE, revision COLLATE NOCASE, id""",
                    (component_id,),
                )
            ]

    def get(self, symbol_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM schematic_symbols WHERE id=?", (symbol_id,)
            ).fetchone()
            return dict(row) if row else None

    def update(self, symbol_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "cad_tool", "cad_version", "symbol_name", "source_type", "revision", "notes",
            "updated_at",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid symbol update")
        assignments = ", ".join(f"{name}=:{name}" for name in values)
        with self.database.connect() as connection:
            row = connection.execute(
                f"UPDATE schematic_symbols SET {assignments} WHERE id=:id RETURNING *",
                {**values, "id": symbol_id},
            ).fetchone()
            return dict(row) if row else None

    def attach_file(
        self, symbol_id: int, filename: str, key: str, size: int, sha256: str, updated_at: str
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """UPDATE schematic_symbols SET source_filename=?,storage_key=?,size_bytes=?,
                sha256=?,updated_at=? WHERE id=? AND storage_key IS NULL RETURNING *""",
                (filename, key, size, sha256, updated_at, symbol_id),
            ).fetchone()
            return dict(row) if row else None

    def set_lifecycle(
        self, symbol_id: int, current: str, target: str, updated_at: str
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """UPDATE schematic_symbols SET lifecycle_status=?,updated_at=?
                WHERE id=? AND lifecycle_status=? RETURNING *""",
                (target, updated_at, symbol_id, current),
            ).fetchone()
            return dict(row) if row else None

    def set_pin_validation(
        self, symbol_id: int, status: str, updated_at: str
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """UPDATE schematic_symbols SET pin_validation_status=?,updated_at=?
                WHERE id=? RETURNING *""",
                (status, updated_at, symbol_id),
            ).fetchone()
            return dict(row) if row else None
