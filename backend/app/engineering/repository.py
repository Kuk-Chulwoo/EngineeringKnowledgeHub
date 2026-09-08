"""Transactional persistence for engineering candidates and their review lineage."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ..database import Database
from ..services import ServiceError, utc_now
from .schema import CandidateSet, Claim, Entity, canonical, digest, validate_candidates


def validated(data: CandidateSet, revision_id: int, pages: int) -> list[str]:
    try:
        return validate_candidates(data, revision_id, pages)
    except ValueError as error:
        raise ServiceError(422, str(error)) from error


def require(condition: bool, detail: str, status: int = 409) -> None:
    if not condition:
        raise ServiceError(status, detail)


class EngineeringRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _run(c: sqlite3.Connection, run_id: int) -> dict[str, Any]:
        row = c.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
        require(row is not None, "Extraction run not found", 404)
        return dict(row)

    @staticmethod
    def _field(c: sqlite3.Connection, field_id: int) -> dict[str, Any]:
        row = c.execute("SELECT * FROM engineering_fields WHERE id=?", (field_id,)).fetchone()
        require(row is not None, "Engineering field not found", 404)
        return dict(row)

    @staticmethod
    def _latest(c: sqlite3.Connection, field_id: int) -> dict[str, Any]:
        row = c.execute(
            "SELECT * FROM engineering_review_events WHERE field_id=? ORDER BY sequence DESC LIMIT 1",
            (field_id,),
        ).fetchone()
        require(row is not None, "Field review history missing")
        return dict(row)

    @staticmethod
    def _evidence(c: sqlite3.Connection, field_id: int, revision_id: int) -> list[dict[str, Any]]:
        return [
            {
                "source_revision_id": revision_id,
                "page_number": row["page_number"],
                "printed_page_label": row["printed_page_label"],
                "source_text": row["source_text"],
                "region": json.loads(row["region_json"]) if row["region_json"] else None,
                "locator_method": row["locator_method"],
                "locator_version": row["locator_version"],
                "evidence_role": row["evidence_role"],
            }
            for row in c.execute(
                "SELECT * FROM engineering_field_evidence WHERE field_id=? ORDER BY ordinal",
                (field_id,),
            )
        ]

    def _claim(self, c: sqlite3.Connection, field: dict, run: dict) -> Claim:
        return Claim.model_validate(
            {
                **json.loads(field["payload_json"]),
                "evidence": self._evidence(c, field["id"], run["source_revision_id"]),
            }
        )

    def _put_field(
        self,
        c: sqlite3.Connection,
        entity: dict,
        run: dict,
        claim: Claim,
        origin: str,
        actor: str,
        supersedes: int | None = None,
    ) -> int:
        payload = claim.model_dump(exclude={"evidence"})
        field_hash = digest(
            {
                "run_id": run["id"],
                "source_revision_id": run["source_revision_id"],
                "source_sha256": run["source_sha256"],
                "entity": entity["local_key"],
                "kind": entity["kind"],
                "scope": entity["scope_key"],
                "claim": claim.model_dump(),
                "origin": origin,
                "supersedes": supersedes,
            }
        )
        field_id = c.execute(
            """INSERT INTO engineering_fields
            (entity_id,run_id,key,payload_json,origin,created_by,created_at,supersedes_field_id,content_sha256)
            VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
            (
                entity["id"],
                run["id"],
                claim.key,
                canonical(payload),
                origin,
                actor,
                utc_now(),
                supersedes,
                field_hash,
            ),
        ).fetchone()[0]
        for ordinal, evidence in enumerate(claim.evidence):
            e = evidence.model_dump()
            c.execute(
                """INSERT INTO engineering_field_evidence
                (field_id,ordinal,page_number,printed_page_label,source_text,region_json,
                 locator_method,locator_version,evidence_role,source_text_sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    field_id,
                    ordinal,
                    e["page_number"],
                    e["printed_page_label"],
                    e["source_text"],
                    canonical(e["region"]) if e["region"] else None,
                    e["locator_method"],
                    e["locator_version"],
                    e["evidence_role"],
                    hashlib.sha256(e["source_text"].encode()).hexdigest()
                    if e["source_text"]
                    else None,
                ),
            )
        self._event(
            c,
            field_id,
            1,
            "AI_EXTRACTED" if origin == "AI" else "ENGINEER_DRAFT",
            "AI" if origin == "AI" else "ENGINEER",
            actor,
            field_hash,
            "Initial candidate",
        )
        return field_id

    @staticmethod
    def _event(
        c: sqlite3.Connection,
        field_id: int,
        sequence: int,
        status: str,
        actor_kind: str,
        actor: str,
        field_hash: str,
        reason: str,
        checker: dict | None = None,
    ) -> int:
        return c.execute(
            """INSERT INTO engineering_review_events
            (field_id,sequence,status,actor_kind,actor_id,field_content_sha256,reason,created_at,checker_json)
            VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
            (
                field_id,
                sequence,
                status,
                actor_kind,
                actor,
                field_hash,
                reason,
                utc_now(),
                canonical(checker) if checker else None,
            ),
        ).fetchone()[0]

    @staticmethod
    def _invalidate(c: sqlite3.Connection, field_id: int, reason: str) -> None:
        c.execute(
            """UPDATE approved_snapshots SET eligibility='INVALIDATED',
            invalidated_at=?,invalidation_reason=?
            WHERE eligibility='ACTIVE' AND id IN
            (SELECT snapshot_id FROM approved_snapshot_fields WHERE field_id=?)""",
            (utc_now(), reason, field_id),
        )

    def create_run(
        self,
        revision_id: int,
        source_hash: str,
        page_count: int,
        provenance: dict,
        actor: str,
        retry_of: int | None = None,
    ) -> dict:
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if retry_of is not None:
                old = self._run(c, retry_of)
                require(old["source_revision_id"] == revision_id, "Retry revision mismatch")
                require(
                    old["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"),
                    "Retry requires terminal run",
                )
            run_id = c.execute(
                """INSERT INTO extraction_runs
                (source_revision_id,source_sha256,page_count,schema_version,provider,
                 provenance_json,status,requested_by,created_at,retry_of_run_id)
                VALUES (?,?,?,'engineering-extraction/0.1',?,?,'QUEUED',?,?,?) RETURNING id""",
                (
                    revision_id,
                    source_hash,
                    page_count,
                    provenance["provider"],
                    canonical(provenance),
                    actor,
                    utc_now(),
                    retry_of,
                ),
            ).fetchone()[0]
            return self._run(c, run_id)

    @staticmethod
    def _provenance(c, run):
        value = json.loads(run["provenance_json"])
        if run["provider"] != "synthetic":
            records = {
                r["pass_name"]: json.loads(r["provenance_json"])
                for r in c.execute("SELECT * FROM provider_passes WHERE run_id=?", (run["id"],))
            }
            value["passes"] = [
                records[p] for p in ("identity", "package", "pins", "interfaces") if p in records
            ]
        return value

    def record_pass(self, run_id, token, provenance):
        from .schema import PassProvenance

        provenance = PassProvenance.model_validate(provenance).model_dump()
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            run = self._run(c, run_id)
            require(
                run["status"] == "RUNNING"
                and run["lease_token"] == token
                and run["lease_expires_at"] > utc_now(),
                "Run cannot record pass",
            )
            c.execute(
                "INSERT INTO provider_passes VALUES (?,?,?)",
                (run_id, provenance["pass_name"], canonical(provenance)),
            )

    def list_runs(self, revision_id: int) -> list[dict]:
        with self.database.connect() as c:
            return [
                self._public_run(dict(r), self._provenance(c, dict(r)))
                for r in c.execute(
                    "SELECT * FROM extraction_runs WHERE source_revision_id=? ORDER BY id DESC LIMIT 100",
                    (revision_id,),
                )
            ]

    @staticmethod
    def _public_run(run: dict, provenance: dict | None = None) -> dict:
        return {
            key: value
            for key, value in run.items()
            if key not in ("lease_token", "lease_expires_at", "provenance_json")
        } | {
            "provenance": provenance or json.loads(run["provenance_json"]),
            "synthetic": run["provider"] == "synthetic",
            "pads_eligible": False,
        }

    def read_run(self, run_id: int) -> dict:
        with self.database.connect() as c:
            run = self._run(c, run_id)
            result = self._public_run(run, self._provenance(c, run))
            result["entities"] = []
            for row in c.execute(
                "SELECT * FROM engineering_entities WHERE run_id=? ORDER BY id", (run_id,)
            ):
                entity = dict(row)
                entity["fields"] = []
                for field_row in c.execute(
                    "SELECT * FROM engineering_fields WHERE entity_id=? ORDER BY id", (row["id"],)
                ):
                    field = dict(field_row)
                    history = [
                        dict(event)
                        for event in c.execute(
                            "SELECT * FROM engineering_review_events WHERE field_id=? ORDER BY sequence",
                            (field["id"],),
                        )
                    ]
                    entity["fields"].append(
                        {
                            **{k: v for k, v in field.items() if k != "payload_json"},
                            **self._claim(c, field, run).model_dump(),
                            "source_revision_id": run["source_revision_id"],
                            "review_status": history[-1]["status"],
                            "latest_review_sequence": history[-1]["sequence"],
                            "history": history,
                            "provenance": self._provenance(c, run),
                        }
                    )
                result["entities"].append(entity)
            return result

    def claim_next(self, lease_seconds: int = 60) -> dict | None:
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            now = utc_now()
            c.execute(
                """UPDATE extraction_runs SET status='FAILED',completed_at=?,
                error_code='LEASE_EXPIRED',error_summary='Worker lease expired'
                WHERE status='RUNNING' AND lease_expires_at<?""",
                (now, now),
            )
            row = c.execute(
                "SELECT id FROM extraction_runs WHERE status='QUEUED' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
            c.execute(
                """UPDATE extraction_runs SET status='RUNNING',started_at=?,lease_token=?,
                lease_expires_at=? WHERE id=?""",
                (now, uuid4().hex, expires, row["id"]),
            )
            return self._run(c, row["id"])

    def cancel(self, run_id: int) -> dict:
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            run = self._run(c, run_id)
            require(run["status"] in ("QUEUED", "RUNNING"), "Only unfinished runs can be cancelled")
            c.execute(
                "UPDATE extraction_runs SET status='CANCELLED',completed_at=? WHERE id=?",
                (utc_now(), run_id),
            )
        return self.read_run(run_id)

    def fail(self, run_id: int, token: str, code: str) -> None:
        with self.database.connect() as c:
            c.execute(
                """UPDATE extraction_runs SET status='FAILED',completed_at=?,
                error_code=?,error_summary='Extraction failed; original PDF is unchanged'
                WHERE id=? AND status='RUNNING' AND lease_token=?""",
                (utc_now(), code, run_id, token),
            )

    def publish(self, run_id: int, token: str, data: CandidateSet) -> None:
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            run = self._run(c, run_id)
            require(
                run["status"] == "RUNNING"
                and run["lease_token"] == token
                and run["lease_expires_at"] > utc_now(),
                "Run cannot publish",
            )
            require(
                data.provenance.model_dump() == self._provenance(c, run),
                "Provider provenance mismatch",
                422,
            )
            diagnostics = validated(data, run["source_revision_id"], run["page_count"])
            for entity in data.entities:
                entity_id = c.execute(
                    "INSERT INTO engineering_entities(run_id,local_key,kind,scope_key) VALUES (?,?,?,?) RETURNING id",
                    (run_id, entity.local_key, entity.kind, entity.scope_key),
                ).fetchone()[0]
                for claim in entity.fields:
                    self._put_field(
                        c,
                        {"id": entity_id, **entity.model_dump(exclude={"fields"})},
                        run,
                        claim,
                        "AI",
                        run["provider"] + "-worker",
                    )
            c.execute(
                """UPDATE extraction_runs SET status='SUCCEEDED',completed_at=?,
                candidate_set_sha256=?,diagnostics_json=? WHERE id=?""",
                (utc_now(), digest(data.model_dump()), canonical(diagnostics), run_id),
            )

    def _effective(
        self,
        c: sqlite3.Connection,
        run: dict,
        replacement: tuple[int, Claim] | None = None,
        selected: list[int] | None = None,
    ) -> CandidateSet:
        """Resolve accepted correction heads, preserving original raw candidate history."""
        entities = []
        for row in c.execute(
            "SELECT * FROM engineering_entities WHERE run_id=? ORDER BY id", (run["id"],)
        ):
            fields = [
                dict(f)
                for f in c.execute(
                    "SELECT * FROM engineering_fields WHERE entity_id=? ORDER BY id", (row["id"],)
                )
            ]
            grouped: dict[str, list[dict]] = {}
            for field in fields:
                grouped.setdefault(field["key"], []).append(field)
            claims = []
            for versions in grouped.values():
                original = next(f for f in versions if f["origin"] == "AI")
                approved = [
                    f for f in versions if self._latest(c, f["id"])["status"] == "ENGINEER_APPROVED"
                ]
                chosen = approved[0] if approved else original
                require(len(approved) <= 1, "Competing approved claims")
                if selected is not None:
                    matches = [f for f in versions if f["id"] in selected]
                    require(len(matches) == 1, "Snapshot must select one version of every field")
                    chosen = matches[0]
                claim = self._claim(c, chosen, run)
                if replacement and any(f["id"] == replacement[0] for f in versions):
                    claim = replacement[1]
                claims.append(claim)
            entities.append(
                Entity(
                    local_key=row["local_key"],
                    kind=row["kind"],
                    scope_key=row["scope_key"],
                    fields=claims,
                )
            )
        return CandidateSet(
            source_revision_id=run["source_revision_id"],
            provenance=self._provenance(c, run),
            entities=entities,
        )

    def review(
        self,
        field_id: int,
        expected: int,
        status: str,
        actor: str,
        reason: str,
        actor_kind: str = "ENGINEER",
    ) -> dict:
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            field = self._field(c, field_id)
            run = self._run(c, field["run_id"])
            latest = self._latest(c, field_id)
            require(latest["sequence"] == expected, "Stale review sequence")
            if actor_kind == "AI":
                require(
                    status == "AI_CHECKED" and latest["status"] in ("AI_EXTRACTED", "AI_CHECKED"),
                    "AI cannot make or override engineer decisions",
                    403,
                )
            else:
                require(
                    status in ("ENGINEER_APPROVED", "ENGINEER_REJECTED"),
                    "Unsupported human review status",
                    422,
                )
            if status == "ENGINEER_APPROVED":
                claim = self._claim(c, field, run)
                require(
                    claim.availability == "PRESENT", "Cannot approve unavailable engineering value"
                )
                effective = self._effective(c, run, replacement=(field_id, claim))
                validated(effective, run["source_revision_id"], run["page_count"])
                competing = [
                    dict(row)
                    for row in c.execute(
                        "SELECT * FROM engineering_fields WHERE entity_id=? AND key=? AND id<>?",
                        (field["entity_id"], field["key"], field_id),
                    )
                ]
                # Reject obsolete versions when accepting a correction; never inherit approval.
                for other in competing:
                    previous = self._latest(c, other["id"])
                    if previous["status"] == "ENGINEER_APPROVED":
                        require(
                            field["supersedes_field_id"] == other["id"],
                            "Correction no longer supersedes current approved version",
                        )
                        self._event(
                            c,
                            other["id"],
                            previous["sequence"] + 1,
                            "ENGINEER_REJECTED",
                            "ENGINEER",
                            actor,
                            other["content_sha256"],
                            "Replaced: " + reason,
                        )
                        self._invalidate(c, other["id"], "Selected field was replaced")
            if status == "ENGINEER_REJECTED":
                self._invalidate(c, field_id, reason)
            self._event(
                c,
                field_id,
                expected + 1,
                status,
                actor_kind,
                actor,
                field["content_sha256"],
                reason,
                {"checker": "synthetic-independent-check/1"} if actor_kind == "AI" else None,
            )
            return self._latest(c, field_id)

    def correct(self, field_id: int, expected: int, claim: Claim, actor: str) -> int:
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            field = self._field(c, field_id)
            require(self._latest(c, field_id)["sequence"] == expected, "Stale review sequence")
            require(claim.key == field["key"], "Correction cannot change field key", 422)
            run = self._run(c, field["run_id"])
            data = self._effective(c, run, replacement=(field_id, claim))
            validated(data, run["source_revision_id"], run["page_count"])
            entity = dict(
                c.execute(
                    "SELECT * FROM engineering_entities WHERE id=?", (field["entity_id"],)
                ).fetchone()
            )
            return self._put_field(c, entity, run, claim, "ENGINEER_CORRECTION", actor, field_id)

    def snapshot(self, run_id: int, package_id: int, field_ids: list[int], actor: str) -> dict:
        with self.database.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            run = self._run(c, run_id)
            require(run["status"] == "SUCCEEDED", "Snapshot requires succeeded run")
            require(
                len(field_ids) > 0 and len(field_ids) == len(set(field_ids)), "Invalid selection"
            )
            package = c.execute(
                "SELECT * FROM engineering_entities WHERE id=? AND run_id=? AND kind='PACKAGE'",
                (package_id, run_id),
            ).fetchone()
            require(package is not None, "Package does not belong to run", 422)
            # Initial conservative profile requires the complete single-package candidate set.
            require(
                c.execute(
                    "SELECT count(*) FROM engineering_entities WHERE run_id=? AND kind='PACKAGE'",
                    (run_id,),
                ).fetchone()[0]
                == 1,
                "Initial snapshot profile supports one package",
            )
            memberships = []
            for field_id in field_ids:
                field = self._field(c, field_id)
                event = self._latest(c, field_id)
                require(field["run_id"] == run_id, "Selected field belongs to another run")
                require(
                    event["status"] == "ENGINEER_APPROVED" and event["actor_kind"] == "ENGINEER",
                    "Every selected field must be engineer-approved",
                )
                require(
                    event["field_content_sha256"] == field["content_sha256"],
                    "Approval hash mismatch",
                )
                memberships.append((field_id, field["content_sha256"], event["id"]))
            effective = self._effective(c, run, selected=field_ids)
            require(
                sum(len(e.fields) for e in effective.entities) == len(field_ids),
                "Unexpected selected fields",
            )
            warnings = validated(effective, run["source_revision_id"], run["page_count"])
            require(not warnings, "Unresolved engineering coverage prevents snapshot")
            pkg_values = {
                f.key: f.value
                for e in effective.entities
                if e.local_key == package["local_key"]
                for f in e.fields
            }
            require(
                pkg_values.get("variant_selector") not in ("unspecified", "UNSPECIFIED", ""),
                "Package variant must be explicit",
            )
            component_id = c.execute(
                """SELECT d.component_id FROM revisions r
                JOIN documents d ON d.id=r.document_id WHERE r.id=?""",
                (run["source_revision_id"],),
            ).fetchone()[0]
            manifest = {
                "run_id": run_id,
                "revision_id": run["source_revision_id"],
                "package_id": package_id,
                "fields": sorted(memberships),
                "profile": "engineering-review/1",
                "synthetic": run["provider"] == "synthetic",
            }
            snapshot_id = c.execute(
                """INSERT INTO approved_snapshots
                (component_id,source_revision_id,run_id,selected_package_entity_id,purpose,
                 manifest_sha256,approved_by,approved_at,eligibility)
                VALUES (?,?,?,?,'engineering-review',?,?,?,'ACTIVE') RETURNING id""",
                (
                    component_id,
                    run["source_revision_id"],
                    run_id,
                    package_id,
                    digest(manifest),
                    actor,
                    utc_now(),
                ),
            ).fetchone()[0]
            for field_id, field_hash, event_id in memberships:
                c.execute(
                    "INSERT INTO approved_snapshot_fields VALUES (?,?,?,?)",
                    (snapshot_id, field_id, field_hash, event_id),
                )
            c.execute("UPDATE approved_snapshots SET sealed=1 WHERE id=?", (snapshot_id,))
        return self.read_snapshot(snapshot_id)

    def read_snapshot(self, snapshot_id: int) -> dict:
        with self.database.connect() as c:
            row = c.execute(
                "SELECT * FROM approved_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
            require(row is not None, "Snapshot not found", 404)
            result = dict(row)
            result["fields"] = [
                dict(row)
                for row in c.execute(
                    "SELECT * FROM approved_snapshot_fields WHERE snapshot_id=? ORDER BY field_id",
                    (snapshot_id,),
                )
            ]
            current = all(
                self._latest(c, f["field_id"])["status"] == "ENGINEER_APPROVED"
                and self._field(c, f["field_id"])["content_sha256"] == f["field_content_sha256"]
                for f in result["fields"]
            )
            result["eligible_for_engineering_review"] = (
                result["eligibility"] == "ACTIVE" and current
            )
            result["pads_eligible"] = False
            result["synthetic"] = self._run(c, result["run_id"])["provider"] == "synthetic"
            return result
