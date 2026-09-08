"""Manually curated golden references and read-only comparisons of ORIGINAL AI fields."""

import json
from decimal import Decimal
from typing import Literal

from pydantic import Field

from ..engineering.repository import require, validated
from ..engineering.schema import (
    REFS,
    CandidateSet,
    Claim,
    Entity,
    Evidence,
    Kind,
    Quantity,
    StrictModel,
    canonical,
    digest,
)
from ..engineering.synthetic import PROVENANCE
from ..services import utc_now
from .config import ExtractionSettings
from .parsing import analyze, normalized


class ExpectedField(StrictModel):
    key: str = Field(min_length=1, max_length=100)
    value: str | int | bool | Quantity
    evidence: list[Evidence] = Field(min_length=1, max_length=16)


class ExpectedEntity(StrictModel):
    local_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    kind: Kind
    scope_key: str = Field(min_length=1, max_length=100)
    fields: list[ExpectedField] = Field(min_length=1, max_length=100)


class GoldenManifest(StrictModel):
    schema_version: Literal["engineering-golden/0.1"]
    manufacturer: str = Field(min_length=1, max_length=200)
    part_number: str = Field(min_length=1, max_length=200)
    source_revision_id: int = Field(gt=0)
    document_revision: str = Field(min_length=1, max_length=200)
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(gt=0, le=300)
    source_url: str | None = Field(default=None, max_length=2000)
    retrieved_at: str | None = Field(default=None, max_length=100)
    curation_notes: str = Field(min_length=1, max_length=4000)
    package_scope: str = Field(min_length=1, max_length=100)
    entities: list[ExpectedEntity] = Field(min_length=1, max_length=2000)

    def candidates_for_validation(self):
        # Internal reuse of deterministic engineering rules only, never a persisted AI run.
        return CandidateSet(
            source_revision_id=self.source_revision_id,
            provenance=PROVENANCE,
            entities=[
                Entity(
                    local_key=e.local_key,
                    kind=e.kind,
                    scope_key=e.scope_key,
                    fields=[Claim.model_validate(f.model_dump()) for f in e.fields],
                )
                for e in self.entities
            ],
        )


CATEGORIES = {
    "COMPONENT_IDENTITY": "Identity",
    "PACKAGE": "Package",
    "PIN": "Pins",
    "INTERFACE": "Interfaces",
    "INTERFACE_PIN": "Interfaces",
}


def flatten(entities):
    """Semantic entity addresses decouple comparison from model-generated local keys."""
    by_key = {e.local_key: e for e in entities}

    def values(e):
        return {f.key: f.value for f in e.fields if f.availability == "PRESENT"}

    def address(e):
        v = values(e)
        if e.kind == "COMPONENT_IDENTITY":
            return [e.kind]
        if e.kind == "PACKAGE":
            return [e.kind, e.scope_key]
        if e.kind == "PIN":
            return [e.kind, e.scope_key, v.get("number", "?" + e.local_key)]
        if e.kind == "INTERFACE":
            return [e.kind, e.scope_key, v.get("kind", "?"), v.get("name", "?" + e.local_key)]

        def ref(key):
            return (
                address(by_key[v[key]])
                if v.get(key) in by_key
                else ["unresolved", e.local_key, key]
            )

        return [
            e.kind,
            e.scope_key,
            ref("interface_ref"),
            ref("pin_ref"),
            v.get("role", "?"),
            v.get("mode"),
        ]

    result = {}
    for e in entities:
        a = address(e)
        for f in e.fields:
            key = canonical([a, f.key])
            require(key not in result, "Ambiguous semantic entity address; comparison refused", 422)
            value = f.value
            if f.key in REFS and value in by_key:
                value = address(by_key[value])
            if isinstance(value, dict) and set(value) == {"decimal", "unit"}:
                value = {
                    "decimal": format(Decimal(value["decimal"]).normalize(), "f"),
                    "unit": value["unit"],
                }
            result[key] = {
                "category": CATEGORIES[e.kind],
                "entity": a,
                "field": f.key,
                "value": value,
                "availability": f.availability,
                "evidence": [ev.model_dump() for ev in f.evidence],
            }
    return result


def compare(expected, actual):
    golden, candidates = flatten(expected), flatten(actual)
    rows, evidence_rows = [], []
    for key in sorted(golden.keys() | candidates.keys()):
        g, a = golden.get(key), candidates.get(key)
        present = a is not None and a["availability"] == "PRESENT"
        # Unavailable extra slots are not invented engineering values.
        if g is None and not present:
            continue
        status = (
            "EXTRA"
            if g is None
            else "MISSING"
            if not present
            else "MATCH"
            if canonical(g["value"]) == canonical(a["value"])
            else "MISMATCH"
        )
        row = {
            **{k: (g or a)[k] for k in ("category", "entity", "field")},
            "status": status,
            "golden": g["value"] if g else None,
            "candidate": a["value"] if present else None,
        }
        rows.append(row)
        if g is None:
            evidence_status = "EXTRA"
        elif not present or not a["evidence"]:
            evidence_status = "MISSING"
        else:
            evidence_status = (
                "MATCH"
                if all(
                    any(
                        ge["page_number"] == ae["page_number"]
                        and ge["source_revision_id"] == ae["source_revision_id"]
                        and ge["source_text"]
                        and ae["source_text"]
                        and normalized(ge["source_text"]) in normalized(ae["source_text"])
                        for ae in a["evidence"]
                    )
                    for ge in g["evidence"]
                )
                else "MISMATCH"
            )
        evidence_rows.append(
            {
                **row,
                "category": "Evidence",
                "status": evidence_status,
                "golden": g["evidence"] if g else None,
                "candidate": a["evidence"] if a else None,
            }
        )
    metrics = {}
    for category in ("Identity", "Package", "Pins", "Interfaces", "Evidence"):
        subset = [r for r in rows + evidence_rows if r["category"] == category]
        counts = {
            s.lower(): sum(r["status"] == s for r in subset)
            for s in ("MATCH", "MISMATCH", "MISSING", "EXTRA")
        }
        expected_count = counts["match"] + counts["mismatch"] + counts["missing"]
        metrics[category] = {
            **counts,
            "expected": expected_count,
            "covered": counts["match"] + counts["mismatch"],
            "coverage": ((counts["match"] + counts["mismatch"]) / expected_count)
            if expected_count
            else None,
        }
    return {
        "comparison_version": "semantic-fields/1",
        "unit": "field claims (not pin rows)",
        "metrics": metrics,
        "rows": rows + evidence_rows,
        "wrong_value_count": sum(r["status"] == "MISMATCH" for r in rows),
        "missing_value_count": sum(r["status"] == "MISSING" for r in rows),
        "invented_value_count": sum(r["status"] == "EXTRA" for r in rows),
        "measurement_only": True,
    }


class GoldenService:
    def __init__(self, engineering):
        self.engineering = engineering
        self.database = engineering.repository.database

    def validate_source(self, manifest):
        revision = self.engineering.hub.repository.revision(manifest.source_revision_id)
        require(revision is not None, "Revision not found", 404)
        require(
            revision["revision"] == manifest.document_revision
            and revision["sha256"] == manifest.pdf_sha256,
            "Golden revision/hash mismatch",
            422,
        )
        document = analyze(
            self.engineering.hub,
            manifest.source_revision_id,
            ExtractionSettings(
                package_scope=manifest.package_scope, max_document_pages=300, chars_per_page=20000
            ),
        )
        require(document.page_count == manifest.page_count, "Golden page count mismatch", 422)
        data = manifest.candidates_for_validation()
        validated(data, manifest.source_revision_id, manifest.page_count)
        packages = [e for e in data.entities if e.kind == "PACKAGE"]
        require(
            len(packages) == 1
            and all(e.scope_key == manifest.package_scope for e in data.entities),
            "Golden must describe one explicit package scope",
            422,
        )
        identity = next(e for e in data.entities if e.kind == "COMPONENT_IDENTITY")
        identity_values = {f.key: f.value for f in identity.fields}
        require(
            identity_values["manufacturer"] == manifest.manufacturer
            and identity_values["part_number"] == manifest.part_number,
            "Golden identity metadata mismatch",
            422,
        )
        for e in data.entities:
            for f in e.fields:
                for ev in f.evidence:
                    require(
                        ev.locator_method in ("TEXT", "TABLE")
                        and ev.region is None
                        and bool(ev.source_text)
                        and normalized(ev.source_text)
                        in normalized(document.pages[ev.page_number]),
                        "Golden evidence is not supported by native source text",
                        422,
                    )
        flatten(data.entities)

    def create(self, manifest, actor):
        self.validate_source(manifest)
        value = manifest.model_dump()
        with self.database.connect() as c:
            identity = c.execute(
                "INSERT INTO golden_manifests(source_revision_id,manifest_json,manifest_sha256,curated_by,created_at) VALUES (?,?,?,?,?) RETURNING id",
                (manifest.source_revision_id, canonical(value), digest(value), actor, utc_now()),
            ).fetchone()[0]
        return self.read(identity)

    def read(self, identity):
        with self.database.connect() as c:
            row = c.execute("SELECT * FROM golden_manifests WHERE id=?", (identity,)).fetchone()
            require(row is not None, "Golden reference not found", 404)
            value = dict(row)
            value["manifest"] = json.loads(value.pop("manifest_json"))
            value["status"] = "ENGINEER_APPROVED" if value["approved_by"] else "ENGINEER_DRAFT"
            return value

    def list(self, revision_id):
        with self.database.connect() as c:
            return [
                self.read(r[0])
                for r in c.execute(
                    "SELECT id FROM golden_manifests WHERE source_revision_id=? ORDER BY id DESC LIMIT 100",
                    (revision_id,),
                )
            ]

    def approve(self, identity, expected_hash, actor):
        value = self.read(identity)
        require(value["manifest_sha256"] == expected_hash, "Golden approval hash mismatch")
        self.validate_source(GoldenManifest.model_validate(value["manifest"]))
        with self.database.connect() as c:
            changed = c.execute(
                "UPDATE golden_manifests SET approved_by=?,approved_at=? WHERE id=? AND approved_by IS NULL",
                (actor, utc_now(), identity),
            ).rowcount
            require(changed == 1, "Golden already approved")
        return self.read(identity)

    def evaluate(self, identity, run_id):
        reference = self.read(identity)
        require(
            reference["status"] == "ENGINEER_APPROVED",
            "Golden reference requires engineer approval",
        )
        manifest = GoldenManifest.model_validate(reference["manifest"])
        self.validate_source(manifest)
        run = self.engineering.repository.read_run(run_id)
        require(run["status"] == "SUCCEEDED", "Evaluation requires succeeded run")
        require(
            run["source_revision_id"] == manifest.source_revision_id
            and run["source_sha256"] == manifest.pdf_sha256
            and run["page_count"] == manifest.page_count,
            "Golden/run revision, hash or page count mismatch",
            422,
        )
        originals = [
            Entity(
                local_key=e["local_key"],
                kind=e["kind"],
                scope_key=e["scope_key"],
                fields=[
                    Claim.model_validate(
                        {k: f[k] for k in Claim.model_fields if k in f}
                        | {"review_status": "AI_EXTRACTED"}
                    )
                    for f in e["fields"]
                    if f["origin"] == "AI"
                ],
            )
            for e in run["entities"]
        ]
        require(
            all(e.scope_key == manifest.package_scope for e in originals),
            "Golden/run package scope mismatch",
            422,
        )
        return {
            **compare(manifest.candidates_for_validation().entities, originals),
            "golden_id": identity,
            "golden_sha256": reference["manifest_sha256"],
            "run_id": run_id,
            "candidate_set_sha256": run["candidate_set_sha256"],
            "source_revision_id": manifest.source_revision_id,
        }
