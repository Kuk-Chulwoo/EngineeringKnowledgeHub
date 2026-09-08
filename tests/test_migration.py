import sqlite3

import pytest

from backend.app.database import SCHEMA, Database
from backend.app.migrations import migrate_v1_to_v2


def populated_v1(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO components VALUES (1,'Vendor','PART','desc','cat','pkg','now')"
        )
        connection.execute("INSERT INTO documents VALUES (1,1,'Datasheet')")
        connection.execute(
            "INSERT INTO revisions VALUES (1,1,'A',NULL,'original.pdf','now',?,100,?)",
            ("a" * 32 + ".pdf", "b" * 64),
        )
    return rows(path)


def rows(path):
    with sqlite3.connect(path) as connection:
        return {
            t: connection.execute(f"SELECT * FROM {t}").fetchall()
            for t in ("components", "documents", "revisions")
        }


def test_populated_v1_migration_preserves_every_original_column(tmp_path):
    path = tmp_path / "hub.sqlite3"
    before = populated_v1(path)
    Database(path).initialize()
    assert rows(path) == before
    Database(path).initialize()
    assert rows(path) == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[
                0
            ]
            == 10
        )
    backups = list(tmp_path.glob("*.v1-backup-*"))
    assert len(backups) == 1
    assert rows(backups[0]) == before


def test_migration_rollback_on_failure(tmp_path):
    path = tmp_path / "hub.sqlite3"
    before = populated_v1(path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE engineering_fields (conflict TEXT)")
    with pytest.raises(sqlite3.OperationalError):
        Database(path).initialize()
    assert rows(path) == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='extraction_runs'"
        ).fetchall()


def test_migration_requires_v1(tmp_path):
    with sqlite3.connect(tmp_path / "empty") as connection, pytest.raises(RuntimeError):
        migrate_v1_to_v2(connection)
