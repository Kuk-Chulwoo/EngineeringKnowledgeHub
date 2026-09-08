from typing import Any

from .database import Database


class Repository:
    def __init__(self, database: Database):
        self.database = database

    def create_component(self, values: dict[str, Any]) -> dict[str, Any]:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO components
                (manufacturer, part_number, description, category, package, created_at)
                VALUES (:manufacturer, :part_number, :description, :category, :package, :created_at)
                RETURNING *""",
                values,
            )
            return dict(cursor.fetchone())

    def search(self, query: str, limit: int, offset: int) -> dict[str, Any]:
        # instr treats % and _ literally; SQL values are always bound parameters.
        predicate = """instr(lower(manufacturer), lower(?)) > 0
            OR instr(lower(part_number), lower(?)) > 0
            OR instr(lower(description), lower(?)) > 0
            OR instr(lower(category), lower(?)) > 0"""
        values = [query] * 4
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
            return result

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
