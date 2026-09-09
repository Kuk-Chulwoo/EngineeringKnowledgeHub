from typing import Any

from .database import Database


class Repository:
    def __init__(self, database: Database):
        self.database = database

    def create_component(self, values: dict[str, Any]) -> dict[str, Any]:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO components
                (manufacturer, part_number, description, category, package, internal_part_number,
                 lifecycle_status, created_at, updated_at)
                VALUES (:manufacturer, :part_number, :description, :category, :package,
                 :internal_part_number, 'DRAFT', :created_at, :updated_at)
                RETURNING *""",
                values,
            )
            return dict(cursor.fetchone())

    def search(self, query: str, limit: int, offset: int) -> dict[str, Any]:
        # instr treats % and _ literally; SQL values are always bound parameters.
        predicate = """instr(lower(manufacturer), lower(?)) > 0
            OR instr(lower(part_number), lower(?)) > 0
            OR instr(lower(description), lower(?)) > 0
            OR instr(lower(category), lower(?)) > 0
            OR instr(lower(coalesce(internal_part_number,'')), lower(?)) > 0
            OR instr(lower(package), lower(?)) > 0"""
        values = [query] * 6
        with self.database.connect() as connection:
            total = connection.execute(
                f"SELECT count(*) FROM components WHERE {predicate}",
                values,
            ).fetchone()[0]
            rows = connection.execute(
                f"""SELECT * FROM components WHERE {predicate}
                ORDER BY manufacturer, part_number, id LIMIT ? OFFSET ?""",
                [*values, limit, offset],
            )
            return {
                "items": [dict(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def component(self, component_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM components WHERE id = ?",
                (component_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            documents = connection.execute(
                "SELECT * FROM documents WHERE component_id = ? ORDER BY id",
                (component_id,),
            ).fetchall()
            result["documents"] = []
            for document in documents:
                item = dict(document)
                item["revisions"] = [
                    dict(revision)
                    for revision in connection.execute(
                        "SELECT * FROM revisions WHERE document_id = ? ORDER BY id DESC",
                        (item["id"],),
                    )
                ]
                result["documents"].append(item)
            summary = connection.execute(
                """SELECT count(*) AS count,
                CASE WHEN count(DISTINCT source_type)=1 THEN min(source_type) ELSE NULL END source_type
                FROM component_pins WHERE component_id=?""",
                (component_id,),
            ).fetchone()
            result["pin_summary"] = dict(summary)
            return result

    def update_component(self, component_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "internal_part_number",
            "manufacturer",
            "part_number",
            "description",
            "category",
            "package",
            "updated_at",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid component update")
        assignments = ", ".join(f"{name}=:{name}" for name in values)
        with self.database.connect() as connection:
            row = connection.execute(
                f"UPDATE components SET {assignments} WHERE id=:id RETURNING *",
                {**values, "id": component_id},
            ).fetchone()
            return dict(row) if row else None

    def transition_lifecycle(
        self, component_id: int, current: str, target: str, updated_at: str
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """UPDATE components SET lifecycle_status=?, updated_at=?
                WHERE id=? AND lifecycle_status=? RETURNING *""",
                (target, updated_at, component_id, current),
            ).fetchone()
            return dict(row) if row else None

    def pins(self, component_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """SELECT * FROM component_pins WHERE component_id=?
                    ORDER BY pin_number COLLATE NOCASE, pin_number, id""",
                    (component_id,),
                )
            ]

    def replace_pins(
        self,
        component_id: int,
        source_type: str,
        pins: list[dict[str, str]],
        timestamp: str,
    ) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM component_pins WHERE component_id=?", (component_id,))
            connection.executemany(
                """INSERT INTO component_pins
                (component_id,pin_number,pin_name,source_type,source_run_id,source_revision_id,
                 created_at,updated_at) VALUES (?,?,?,?,NULL,NULL,?,?)""",
                [
                    (component_id, pin["pin_number"], pin["pin_name"], source_type, timestamp, timestamp)
                    for pin in pins
                ],
            )
            return [
                dict(row)
                for row in connection.execute(
                    """SELECT * FROM component_pins WHERE component_id=?
                    ORDER BY pin_number COLLATE NOCASE, pin_number, id""",
                    (component_id,),
                )
            ]

    def add_revision(self, component_id: int, title: str, values: dict[str, Any]) -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO documents(component_id, title) VALUES (?, ?)",
                (component_id, title),
            )
            document_id = connection.execute(
                "SELECT id FROM documents WHERE component_id = ? AND title = ?",
                (component_id, title),
            ).fetchone()[0]
            cursor = connection.execute(
                """INSERT INTO revisions (document_id, revision, datasheet_date, filename,
                uploaded_at, storage_key, size_bytes, sha256)
                VALUES (:document_id, :revision, :datasheet_date, :filename,
                :uploaded_at, :storage_key, :size_bytes, :sha256) RETURNING *""",
                {**values, "document_id": document_id},
            )
            return dict(cursor.fetchone())

    def revision(self, revision_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
            return dict(row) if row else None
