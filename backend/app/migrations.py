"""Explicit additive v1 -> v2 migration. Existing Phase 1 rows are never rewritten."""

import sqlite3

V2 = """
CREATE TABLE extraction_runs (
 id INTEGER PRIMARY KEY,
 source_revision_id INTEGER NOT NULL REFERENCES revisions(id),
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 page_count INTEGER NOT NULL CHECK(page_count>0),
 schema_version TEXT NOT NULL,
 provider TEXT NOT NULL CHECK(provider='synthetic'),
 provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
 status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 requested_by TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
 retry_of_run_id INTEGER REFERENCES extraction_runs(id),
 lease_token TEXT, lease_expires_at TEXT,
 error_code TEXT, error_summary TEXT, candidate_set_sha256 TEXT,
 diagnostics_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(diagnostics_json))
);
CREATE INDEX runs_revision ON extraction_runs(source_revision_id,id);
CREATE INDEX runs_status ON extraction_runs(status,id);
CREATE TABLE engineering_entities (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES extraction_runs(id),
 local_key TEXT NOT NULL, kind TEXT NOT NULL, scope_key TEXT NOT NULL,
 UNIQUE(run_id,local_key), UNIQUE(id,run_id)
);
CREATE TABLE engineering_fields (
 id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, run_id INTEGER NOT NULL,
 key TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 origin TEXT NOT NULL CHECK(origin IN ('AI','ENGINEER_CORRECTION')),
 created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 supersedes_field_id INTEGER REFERENCES engineering_fields(id),
 content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
 FOREIGN KEY(entity_id,run_id) REFERENCES engineering_entities(id,run_id)
);
CREATE UNIQUE INDEX original_claim ON engineering_fields(entity_id,key) WHERE origin='AI';
CREATE INDEX fields_run ON engineering_fields(run_id,id);
CREATE TABLE engineering_field_evidence (
 id INTEGER PRIMARY KEY, field_id INTEGER NOT NULL REFERENCES engineering_fields(id),
 ordinal INTEGER NOT NULL, page_number INTEGER NOT NULL CHECK(page_number>0),
 printed_page_label TEXT, source_text TEXT, region_json TEXT,
 locator_method TEXT NOT NULL, locator_version TEXT NOT NULL, evidence_role TEXT NOT NULL,
 source_text_sha256 TEXT,
 UNIQUE(field_id,ordinal),
 CHECK(source_text IS NOT NULL OR region_json IS NOT NULL),
 CHECK(region_json IS NULL OR json_valid(region_json))
);
CREATE TABLE engineering_review_events (
 id INTEGER PRIMARY KEY, field_id INTEGER NOT NULL REFERENCES engineering_fields(id),
 sequence INTEGER NOT NULL CHECK(sequence>0),
 status TEXT NOT NULL CHECK(status IN
 ('AI_EXTRACTED','AI_CHECKED','ENGINEER_DRAFT','ENGINEER_APPROVED','ENGINEER_REJECTED')),
 actor_kind TEXT NOT NULL CHECK(actor_kind IN ('AI','ENGINEER')),
 actor_id TEXT NOT NULL, field_content_sha256 TEXT NOT NULL,
 reason TEXT NOT NULL, created_at TEXT NOT NULL,
 checker_json TEXT CHECK(checker_json IS NULL OR json_valid(checker_json)),
 UNIQUE(field_id,sequence),
 CHECK(actor_kind='ENGINEER' OR status IN ('AI_EXTRACTED','AI_CHECKED'))
);
CREATE TABLE approved_snapshots (
 id INTEGER PRIMARY KEY, component_id INTEGER NOT NULL REFERENCES components(id),
 source_revision_id INTEGER NOT NULL REFERENCES revisions(id),
 run_id INTEGER NOT NULL REFERENCES extraction_runs(id),
 selected_package_entity_id INTEGER NOT NULL REFERENCES engineering_entities(id),
 purpose TEXT NOT NULL CHECK(purpose='engineering-review'),
 manifest_sha256 TEXT NOT NULL, approved_by TEXT NOT NULL, approved_at TEXT NOT NULL,
 eligibility TEXT NOT NULL CHECK(eligibility IN ('ACTIVE','INVALIDATED')),
 invalidated_at TEXT, invalidation_reason TEXT,
 sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0,1))
);
CREATE TABLE approved_snapshot_fields (
 snapshot_id INTEGER NOT NULL REFERENCES approved_snapshots(id),
 field_id INTEGER NOT NULL REFERENCES engineering_fields(id),
 field_content_sha256 TEXT NOT NULL,
 approval_event_id INTEGER NOT NULL REFERENCES engineering_review_events(id),
 PRIMARY KEY(snapshot_id,field_id)
);
CREATE TRIGGER frozen_run BEFORE UPDATE ON extraction_runs
WHEN OLD.status IN ('SUCCEEDED','FAILED','CANCELLED')
BEGIN SELECT RAISE(ABORT,'Terminal run is immutable'); END;
CREATE TRIGGER run_lineage BEFORE UPDATE ON extraction_runs
WHEN NEW.source_revision_id<>OLD.source_revision_id OR NEW.source_sha256<>OLD.source_sha256
 OR NEW.page_count<>OLD.page_count OR NEW.schema_version<>OLD.schema_version
 OR NEW.provider<>OLD.provider OR NEW.provenance_json<>OLD.provenance_json
 OR NEW.requested_by<>OLD.requested_by OR NEW.created_at<>OLD.created_at
 OR NEW.retry_of_run_id IS NOT OLD.retry_of_run_id
BEGIN SELECT RAISE(ABORT,'Run lineage is immutable'); END;
CREATE TRIGGER entity_insert BEFORE INSERT ON engineering_entities
WHEN (SELECT status FROM extraction_runs WHERE id=NEW.run_id)<>'RUNNING'
BEGIN SELECT RAISE(ABORT,'Entities require running run'); END;
CREATE TRIGGER field_insert BEFORE INSERT ON engineering_fields
WHEN (NEW.origin='AI' AND
 (SELECT status FROM extraction_runs WHERE id=NEW.run_id)<>'RUNNING')
 OR (NEW.origin='ENGINEER_CORRECTION' AND
 (SELECT status FROM extraction_runs WHERE id=NEW.run_id)<>'SUCCEEDED')
BEGIN SELECT RAISE(ABORT,'Invalid field publication state'); END;
CREATE TRIGGER frozen_evidence_insert BEFORE INSERT ON engineering_field_evidence
WHEN EXISTS(SELECT 1 FROM engineering_review_events WHERE field_id=NEW.field_id)
BEGIN SELECT RAISE(ABORT,'Published field evidence is immutable'); END;
CREATE TRIGGER sealed_membership BEFORE INSERT ON approved_snapshot_fields
WHEN (SELECT sealed FROM approved_snapshots WHERE id=NEW.snapshot_id)=1
BEGIN SELECT RAISE(ABORT,'Snapshot manifest is immutable'); END;
CREATE TRIGGER frozen_snapshot BEFORE UPDATE ON approved_snapshots
WHEN NOT (
 (OLD.sealed=0 AND NEW.sealed=1 AND NEW.eligibility=OLD.eligibility) OR
 (OLD.sealed=1 AND NEW.sealed=1 AND OLD.eligibility='ACTIVE'
 AND NEW.eligibility='INVALIDATED' AND NEW.invalidated_at IS NOT NULL
 AND NEW.invalidation_reason IS NOT NULL))
 OR NEW.component_id<>OLD.component_id OR NEW.source_revision_id<>OLD.source_revision_id
 OR NEW.run_id<>OLD.run_id OR NEW.selected_package_entity_id<>OLD.selected_package_entity_id
 OR NEW.purpose<>OLD.purpose OR NEW.manifest_sha256<>OLD.manifest_sha256
 OR NEW.approved_by<>OLD.approved_by OR NEW.approved_at<>OLD.approved_at
BEGIN SELECT RAISE(ABORT,'Snapshot manifest is immutable'); END;
PRAGMA user_version=2;
"""

APPEND_ONLY = (
    "extraction_runs",
    "engineering_entities",
    "engineering_fields",
    "engineering_field_evidence",
    "engineering_review_events",
    "approved_snapshots",
    "approved_snapshot_fields",
)


def execute_statements(connection: sqlite3.Connection, sql: str) -> None:
    """Avoid executescript's implicit COMMIT; DDL and version update stay atomic."""
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete migration statement")


def migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise RuntimeError("v2 migration requires schema version 1")
    execute_statements(connection, V2)
    for table in APPEND_ONLY:
        connection.execute(f"""CREATE TRIGGER no_delete_{table} BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT,'Audit records cannot be deleted'); END""")
        if table not in ("extraction_runs", "approved_snapshots"):
            connection.execute(f"""CREATE TRIGGER no_update_{table} BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT,'Audit records are immutable'); END""")
