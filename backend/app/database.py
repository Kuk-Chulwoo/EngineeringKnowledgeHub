import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .migration_v3 import migrate_v2_to_v3
from .migrations import execute_statements, migrate_v1_to_v2

SCHEMA = """
CREATE TABLE IF NOT EXISTS components (
    id INTEGER PRIMARY KEY,
    manufacturer TEXT NOT NULL COLLATE NOCASE,
    part_number TEXT NOT NULL COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    package TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(manufacturer, part_number)
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES components(id),
    title TEXT NOT NULL COLLATE NOCASE,
    UNIQUE(component_id, title)
);
CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    revision TEXT NOT NULL COLLATE NOCASE,
    datasheet_date TEXT,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
    sha256 TEXT NOT NULL,
    UNIQUE(document_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_revisions_document ON revisions(document_id);
PRAGMA user_version = 1;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise RuntimeError(f"Unsupported database schema version: {version}")
            if version in (1, 2):
                # SQLite backup includes a coherent snapshot; never overwrite an earlier backup.
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                backup_path = self.path.with_name(self.path.name + f".v{version}-backup-" + stamp)
                with sqlite3.connect(backup_path) as backup:
                    connection.backup(backup)
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                execute_statements(connection, SCHEMA)
                version = 1
            if version == 1:
                migrate_v1_to_v2(connection)
                version = 2
            if version == 2:
                migrate_v2_to_v3(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign key check failed")
