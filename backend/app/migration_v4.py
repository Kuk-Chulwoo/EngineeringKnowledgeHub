"""Additive v3 -> v4 Company Part Master and canonical pin table migration."""

import sqlite3


def migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != 3:
        raise RuntimeError("v4 migration requires v3")
    connection.execute("ALTER TABLE components ADD COLUMN internal_part_number TEXT COLLATE NOCASE")
    connection.execute(
        """ALTER TABLE components ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK(lifecycle_status IN ('DRAFT','VALIDATED','ENGINEER_APPROVED','RELEASED'))"""
    )
    connection.execute("ALTER TABLE components ADD COLUMN updated_at TEXT")
    connection.execute("UPDATE components SET updated_at=created_at")
    connection.execute(
        """CREATE UNIQUE INDEX components_internal_part_number
        ON components(internal_part_number COLLATE NOCASE)
        WHERE internal_part_number IS NOT NULL"""
    )
    connection.execute(
        """CREATE TABLE component_pins (
         id INTEGER PRIMARY KEY,
         component_id INTEGER NOT NULL REFERENCES components(id),
         pin_number TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(pin_number))>0),
         pin_name TEXT NOT NULL CHECK(length(trim(pin_name))>0),
         source_type TEXT NOT NULL CHECK(source_type IN ('AI_EXTRACTED','USER_IMPORT','MANUAL')),
         source_run_id INTEGER REFERENCES extraction_runs(id),
         source_revision_id INTEGER REFERENCES revisions(id),
         created_at TEXT NOT NULL,
         updated_at TEXT NOT NULL,
         UNIQUE(component_id,pin_number)
        )
        """
    )
    connection.execute("CREATE INDEX component_pins_component ON component_pins(component_id,id)")
    connection.execute("PRAGMA user_version=4")
