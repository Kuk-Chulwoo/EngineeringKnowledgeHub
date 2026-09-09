"""Additive v4 -> v5 schematic symbol artifact migration."""

import sqlite3


def migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != 4:
        raise RuntimeError("v5 migration requires v4")
    connection.execute(
        """CREATE TABLE schematic_symbols (
         id INTEGER PRIMARY KEY,
         component_id INTEGER NOT NULL REFERENCES components(id),
         cad_tool TEXT NOT NULL CHECK(cad_tool IN ('PADS_LOGIC')),
         cad_version TEXT NOT NULL CHECK(length(trim(cad_version))>0),
         symbol_name TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(symbol_name))>0),
         source_type TEXT NOT NULL CHECK(source_type IN (
          'EXISTING_COMPANY_LIBRARY','MANUFACTURER_LIBRARY','ENGINEER_CREATED',
          'IMPORTED_VENDOR_LIBRARY')),
         source_filename TEXT,
         revision TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(revision))>0),
         lifecycle_status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(lifecycle_status IN (
          'DRAFT','VALIDATED','ENGINEER_APPROVED','RELEASED')),
         pin_validation_status TEXT NOT NULL DEFAULT 'NOT_CHECKED' CHECK(
          pin_validation_status IN ('NOT_CHECKED','ENGINEER_REVIEWED')),
         notes TEXT NOT NULL DEFAULT '',
         storage_key TEXT UNIQUE,
         size_bytes INTEGER CHECK(size_bytes IS NULL OR size_bytes>0),
         sha256 TEXT,
         created_at TEXT NOT NULL,
         updated_at TEXT NOT NULL,
         UNIQUE(component_id,cad_tool,symbol_name,revision)
        )"""
    )
    connection.execute(
        "CREATE INDEX schematic_symbols_component ON schematic_symbols(component_id,id)"
    )
    connection.execute("PRAGMA user_version=5")
