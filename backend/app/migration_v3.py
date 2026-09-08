"""Atomic v2 -> v3. Copy run rows verbatim, restore all existing audit guards."""

import sqlite3

from .migrations import execute_statements


def migrate_v2_to_v3(c: sqlite3.Connection):
    if c.execute("PRAGMA user_version").fetchone()[0] != 2:
        raise RuntimeError("v3 migration requires v2")
    # FK enforcement must be disabled before BEGIN, then checked before commit.
    if c.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise RuntimeError("Migration requires foreign_keys OFF outside transaction")
    triggers = c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
    indexes = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='extraction_runs' AND sql IS NOT NULL"
    ).fetchall()
    ddl = c.execute("SELECT sql FROM sqlite_master WHERE name='extraction_runs'").fetchone()[0]
    for name, _ in triggers:
        c.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
    ddl = ddl.replace("CREATE TABLE extraction_runs", "CREATE TABLE extraction_runs_new", 1)
    ddl = ddl.replace("CHECK(provider='synthetic')", "CHECK(provider IN ('synthetic','openai'))")
    c.execute(ddl)
    c.execute("INSERT INTO extraction_runs_new SELECT * FROM extraction_runs")
    c.execute("DROP TABLE extraction_runs")
    c.execute("ALTER TABLE extraction_runs_new RENAME TO extraction_runs")
    for (sql,) in indexes:
        c.execute(sql)
    for _, sql in triggers:
        c.execute(sql)
    execute_statements(c, V3)
    if c.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Foreign key check failed; migration rolled back")


V3 = """
CREATE TABLE provider_passes (
 run_id INTEGER NOT NULL REFERENCES extraction_runs(id),
 pass_name TEXT NOT NULL CHECK(pass_name IN ('identity','package','pins','interfaces')),
 provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
 PRIMARY KEY(run_id,pass_name)
);
CREATE TRIGGER provider_pass_running BEFORE INSERT ON provider_passes
WHEN (SELECT status FROM extraction_runs WHERE id=NEW.run_id)<>'RUNNING'
BEGIN SELECT RAISE(ABORT,'Pass requires running run'); END;
CREATE TRIGGER provider_pass_frozen BEFORE UPDATE ON provider_passes
BEGIN SELECT RAISE(ABORT,'Pass provenance immutable'); END;
CREATE TRIGGER provider_pass_keep BEFORE DELETE ON provider_passes
BEGIN SELECT RAISE(ABORT,'Pass provenance immutable'); END;
CREATE TABLE golden_manifests (
 id INTEGER PRIMARY KEY,
 source_revision_id INTEGER NOT NULL REFERENCES revisions(id),
 manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
 manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
 curated_by TEXT NOT NULL, created_at TEXT NOT NULL,
 approved_by TEXT, approved_at TEXT,
 CHECK((approved_by IS NULL)=(approved_at IS NULL))
);
CREATE TRIGGER golden_frozen BEFORE UPDATE ON golden_manifests
WHEN OLD.approved_by IS NOT NULL OR NEW.approved_by IS NULL OR NEW.approved_at IS NULL
 OR NEW.id<>OLD.id OR NEW.source_revision_id<>OLD.source_revision_id
 OR NEW.manifest_json<>OLD.manifest_json OR NEW.manifest_sha256<>OLD.manifest_sha256
 OR NEW.curated_by<>OLD.curated_by OR NEW.created_at<>OLD.created_at
BEGIN SELECT RAISE(ABORT,'Golden manifest immutable; only one approval allowed'); END;
CREATE TRIGGER golden_keep BEFORE DELETE ON golden_manifests
BEGIN SELECT RAISE(ABORT,'Golden audit records immutable'); END;
PRAGMA user_version=3;
"""
