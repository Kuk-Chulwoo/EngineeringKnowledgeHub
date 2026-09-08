# Proposed engineering data model — Phase 2A

> Phase 2B implementation update: [real extraction, v3 additions and golden comparison](PHASE2B_REAL_EXTRACTION.md).
> The Phase 2A design below remains the trust-model baseline. External transmission is now opt-in; PADS remains deferred.

Status: APPROVED for engineering-data foundation implementation. External AI, CC1120
golden extraction and PADS generation remain outside this phase. Companion: [Phase 2A architecture](PHASE2_AI_EXTRACTION.md).

## Design invariants

1. Existing components/documents/revisions remain unchanged. An extraction run belongs
   to one revision; component ownership is derived through the existing document FK.
2. Run output is an immutable candidate set, separate from catalog metadata. Re-extraction
   creates a new run and never carries forward approval automatically.
3. Every populated field is a typed, versioned claim with source revision, evidence,
   confidence, extraction provenance and review state. Relationships are claims too.
4. Review is append-only. Corrections create new claims; never edit an approved value.
5. Approved snapshots select exact claim versions for a stated purpose and package scope.
   They are not "latest extraction" pointers or an unrestricted approval of an entire run.

## Representation

Use a small relational envelope plus schema-validated JSON field values.
This avoids adding a table for every future engineering domain while preserving relational
keys for lineage, evidence and review. Do not accept arbitrary unvalidated EAV fields:
a versioned discriminated schema defines allowed entity kinds, field keys, types, enums,
units, reference targets, requiredness and cardinalities. Unknown output keys are rejected.
The initial schema identifier is engineering-extraction/0.1; it is distinct from the
application release version and SQLite PRAGMA user_version.

Arrays are not approved as opaque JSON blobs. Each pin/interface is an entity and each
populated leaf is a field. Interface membership has its own entity/field evidence.
Computed display strings, IDs and review totals are system metadata, not extracted claims.

Proposed serialized field envelope:

- field_id, entity_id, key, value and value_type;

- availability: PRESENT | NOT_FOUND | AMBIGUOUS | NOT_APPLICABLE;

- source_revision_id, resolved from the run and included in API/export envelopes;

- evidence[]: physical page plus source snippet and/or region;

- confidence: number 0..1 or null, with confidence_basis;

- extraction: run_id, schema/pipeline/parser/provider/model/prompt versions;

- origin: AI | ENGINEER_CORRECTION;

- review_status and latest_review_sequence;

- supersedes_field_id, if this is a correction; content_sha256.

No evidence-backed value: value=null and availability NOT_FOUND/AMBIGUOUS as appropriate.
These records report coverage, not engineering facts. NOT_FOUND carries searched page
ranges in diagnostics, not fabricated evidence. Null is never zero or false.
NOT_APPLICABLE itself needs evidence or an explicit human rationale and cannot fill a
required downstream numeric/pin field. Only PRESENT claims with supporting evidence can
enter a generation-oriented approved snapshot.

Confidence may be null when the provider cannot estimate it. Record basis as MODEL_SELF_REPORT,
CHECKER_ESTIMATE or NOT_PROVIDED; never present a model score as calibrated accuracy.
An AI check result and its version belong in the review event, not an overwritten
extraction confidence. Human approval is a separate decision, never confidence=1.

## Initial entity/field vocabulary

| Entity | Field keys and value rules |
|---|---|
| component_identity | manufacturer, part_number, description: strings; preserve source identity, do not overwrite catalog |
| package | family, type, manufacturer_package_code: strings; lead_count: positive integer; pin_count_basis: LEADS_ONLY/INCLUDING_EXPOSED_PAD/UNSPECIFIED; body_length/body_width/body_height/pitch bounds: dimensional fields; exposed_pad_present: boolean |
| pin | number: string (supports numeric pins, alphanumeric pads and vendor EP designators); source_name: verbatim string; normalized_name: optional string; electrical_type: enum; primary_function: string; alternate_function.<key>: optional string; functional_group: optional string; package_ref: local package entity reference |
| interface | kind: enum; name: source/normalized label; function: optional description; package_ref: package reference where relevant |
| interface_pin | interface_ref, pin_ref: local entity references; role: string such as clock/data/chip-select/supply; each evidenced |

Interface kind enum: SPI, UART, I2C, GPIO, RF, POWER, ANALOG, CLOCK_RESET, OTHER.
OTHER requires a specific name/function. This enum does not assert that every component
has every interface. "Not found" is not an assertion that an interface does not exist.
Interface presence needs evidence of its function; naming conventions alone are insufficient.

Pin electrical_type enum: INPUT, OUTPUT, BIDIRECTIONAL, POWER_IN, POWER_OUT, GROUND,
PASSIVE, OPEN_DRAIN, NO_CONNECT, OTHER, UNKNOWN. Preserve the verbatim function even when
a normalized type is assigned. Record inference method and supporting evidence.
No current enum is a PADS electrical-type mapping. Multiplexed pins can belong to several
interface_pin entities with distinct roles/mode qualifiers; do not force one interface.
Unstated optional groups are omitted, not invented.

Each dimension bound is a separate claim, e.g. body_width.minimum,
body_width.nominal, body_width.maximum, pitch.nominal. A quantity value contains a
decimal string and canonical unit (mm for package dimensions), plus optional source-unit
and conversion metadata. Decimal strings avoid binary-float drift. A min/max/nominal trio
shares a quantity_group identifier for validation, not blanket approval.
Validate minimum <= nominal <= maximum where available. Do not manufacture nominal as
the average of bounds. Record source symbols and measurement basis so overall lead span
is not confused with body width, and lead pitch is not confused with pad spacing.

Part numbers/package alternatives need explicit scope. Each entity has a scope key and
optional variant selector tied to the source. Runs can identify multiple packages, but
pins/memberships must reference the correct package within that run. "Unspecified"
scope blocks package-dependent approval until resolved. Do not merge separate packages
or orderable suffixes because their pin counts happen to match. A human scope correction
uses the same evidence/review mechanism as other engineering claims.

Exposed pads retain the vendor's exact designator; do not invent pin 33 for a 32-lead part.
Package pin-count basis states whether the exposed pad is included. Validate the pin table
against that explicit basis, counting designators individually and keeping grouped source
text as evidence. A table entry such as a pin range must not silently collapse multiple pins.

## Proposed tables

The following is a schema proposal, not executable DDL. IDs are local integer primary keys
unless noted. Foreign keys use RESTRICT to retain audit lineage. Times are UTC ISO strings.
Field/reference ownership rules are enforced transactionally by services and, where
expressible relationally, composite foreign keys and unique constraints.

### 1. extraction_runs

- id; source_revision_id FK -> revisions.id; source_sha256 (64 hex chars).

- schema_version; pipeline_version; parser_version; provider; model_identifier;
  model_version (nullable if unavailable); prompt_version; prompt_sha256.

- settings_json (validated, bounded, no secrets); requested_scope_json.

- status: QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED.

- created_at, started_at, completed_at; requested_by trusted actor ID.

- retry_of_run_id FK self, nullable; idempotency_key, nullable, unique when supplied.

- lease_token, lease_expires_at (nullable transient worker-ownership metadata).

- coverage_json and diagnostics_json (bounded); error_code and redacted error_summary.

- request_sha256/response_sha256 (nullable), candidate_set_sha256.

Indexes: (source_revision_id, created_at), (status, created_at).
Same revision may have multiple runs. Capture SHA-256 from original revision and verify
bytes, rather than trusting a request-supplied hash. Settings/lineage freeze on creation;
terminal status/output freeze on completion. Only the owning live lease may publish.

### 2. engineering_entities

- id; run_id FK -> extraction_runs.id; local_key unique within run.

- kind: COMPONENT_IDENTITY/PACKAGE/PIN/INTERFACE/INTERFACE_PIN.

- scope_key (system grouping key, not an unreviewed engineering fact); display_order.

- parent_entity_id optional, constrained to same run; created_at.

UNIQUE(id, run_id) supports composite child ownership FKs.
Source-derived variant meaning belongs in a reviewed field, not solely in scope_key.
System grouping or missing-entity repairs require a new extraction run in initial 2A;
do not add entities to the frozen AI output. Human corrections cover fields on existing
entities, including a NOT_FOUND placeholder. Broader manual entity authoring is deferred.

### 3. engineering_fields

- id; entity_id; run_id; key from versioned vocabulary.

- value_type; value_json (small scalar/quantity/reference object, valid JSON).

- availability; confidence nullable CHECK 0 <= confidence <= 1; confidence_basis.

- origin: AI/ENGINEER_CORRECTION; created_by trusted actor ID for correction.

- transformation_json (bounded: normalization/unit conversion/inference method).

- supersedes_field_id optional FK -> engineering_fields.id; created_at; content_sha256.

Composite FK (entity_id, run_id) -> engineering_entities(id, run_id).
Allow multiple immutable versions of the same entity/key, linked by supersedes_field_id;
for initial AI publication there is one claim per (entity_id, key). Service validation
rejects duplicates. Corrections must have the same entity/key/run lineage, be acyclic,
and identify the exact prior claim. Branching competing corrections remain conflicts
until explicitly resolved by an engineer; no last-write-wins selection.
Human corrections form an append-only overlay on the frozen AI candidate set; they do not
change candidate_set_sha256. Each correction freezes value/evidence together at creation.
Its source lineage still points to the original revision/run, but its producer is the
engineer, not the original model. API responses distinguish inherited extraction lineage
from correction actor/time; never attribute human-entered values to an AI model.

Reference-valued claims must resolve to compatible entity kinds in the same run and
package scope. JSON references cannot be protected by ordinary SQLite foreign keys;
validate them at publication and again at snapshot creation. A future normalized
reference table is optional only if query/constraint needs justify it.

content_sha256 covers canonical value, entity/key, scope, source lineage, transformation
and evidence manifest. Reviews and confidence check events do not mutate that hash.
Use a specified deterministic JSON encoding (UTF-8, sorted keys, normalized decimal
strings, no NaN/Infinity) in the eventual implementation.

### 4. engineering_field_evidence

- id; field_id FK -> engineering_fields.id; ordinal unique within field.

- page_number positive integer (1-based physical PDF page).

- printed_page_label optional.

- source_text optional short verbatim snippet.

- region_json optional normalized rectangle: x0,y0,x1,y1 in [0,1],
  top-left origin on the rotation-corrected CropBox, with x0 < x1 and y0 < y1.

- locator_method: TEXT/TABLE/OCR/VISION; locator_version.

- evidence_role: DIRECT/CONTEXT; source_text_sha256 optional for snippet verification.

At least one of nonempty source_text or region_json is required for an evidence row.
Validate page <= actual page count and coordinates against the canonical page transform.
OCR text is explicitly labeled and its region retained; it is not asserted to be exact
native PDF text. Allow multiple evidence rows for a field spanning pages/table headers.
Evidence inherits revision from field -> run; do not accept a competing revision ID.
API/export envelopes include resolved source_revision_id in each field/evidence object.
If an import supplies IDs, reject any mismatch with the run. Cross-document synthesis
requires a future explicit model, not arbitrary foreign-revision evidence here.

Evidence is finalized with AI candidate publication or human correction creation and is immutable. Changing evidence
creates a replacement claim and invalidates approval just like changing its value.

### 5. engineering_review_events

- id; field_id FK; sequence integer; expected prior sequence enforced on append.

- status: AI_EXTRACTED/AI_CHECKED/ENGINEER_DRAFT/ENGINEER_APPROVED/ENGINEER_REJECTED.

- actor_kind: AI/ENGINEER; actor_id from worker identity or authenticated session.

- field_content_sha256; reason; created_at.

- checker_provider/model/version and check_method optional for AI_CHECKED.

- validation_report_json optional bounded deterministic-check findings.

UNIQUE(field_id, sequence). The latest event determines effective review status;
clients cannot directly update a review_status column.
Initial AI publication appends AI_EXTRACTED atomically with fields/evidence. A human
correction starts ENGINEER_DRAFT. AI can append AI_CHECKED only before a human decision.
It cannot erase a rejection or approval. Human approval/rejection may follow either AI
state or ENGINEER_DRAFT, and changing a previous human decision requires a reason.
Approval requires PRESENT, valid evidence, successful hard validation and a matching hash.
Rejected claims remain visible. Re-approval never revives an invalidated snapshot.

Review append checks expected sequence to reject stale/concurrent submissions with 409.
A value/evidence correction never inherits the predecessor's approval. Merely proposing
a correction does not silently revoke the current value; accepting that correction
transactionally rejects/supersedes the predecessor and invalidates dependent snapshots.

### 6. approved_snapshots

- id; component_id FK; source_revision_id FK; run_id FK.

- selected_package_entity_id nullable only for package-independent purpose.

- purpose/profile_version (explicit validated profile, initially engineering-review).

- manifest_sha256; approved_by trusted engineer ID; approved_at.

- eligibility: ACTIVE/INVALIDATED; invalidated_at; invalidation_reason.

A snapshot is an explicit engineer action after individual field review. Manifest
content is immutable; eligibility may only move ACTIVE -> INVALIDATED, with reason.
Service checks component/revision/run/package ownership, field statuses and scope in
one transaction. In 2A no PADS profile exists; therefore no snapshot is PADS-eligible.
For future output, consumers must revalidate current eligibility, every field and a
supported completeness profile, even if the manifest was once approved.

### 7. approved_snapshot_fields

- snapshot_id FK; field_id FK; field_content_sha256; approval_event_id FK.

- PRIMARY KEY(snapshot_id, field_id).

References exact human approval event and claim hash. Enforce approval_event.field_id
matches field_id and the event is ENGINEER_APPROVED; all fields belong to snapshot run.
Approval of a container is never enough: quantities, package references, pin numbers,
names, functions and interface memberships selected for consumption need their own
approved claims. Include relationship/scope closure, not just visible values.

A field's later rejection/accepted replacement invalidates snapshots referencing it in
the same transaction. Consumer gate also checks current status/hash as defense against
stale eligibility. No automatic transfer to a new run, new revision or corrected value.
Cross-run/multi-document snapshot assembly is outside the initial proposal.

## Illustrative envelope

Shape only: IDs, values and page references below are fabricated to explain structure,
not CC1120 data, a fixture, or approved engineering knowledge.

```json
{
  "field_id": 501,
  "entity_id": 20,
  "key": "pitch.nominal",
  "value_type": "quantity",
  "value": {"decimal": "0.50", "unit": "mm"},
  "availability": "PRESENT",
  "source_revision_id": 7,
  "evidence": [{
    "source_revision_id": 7,
    "page_number": 12,
    "source_text": "e 0.50 BSC",
    "region": {"x0": 0.12, "y0": 0.35, "x1": 0.45, "y1": 0.42},
    "locator_method": "TABLE",
    "evidence_role": "DIRECT"
  }],
  "confidence": 0.86,
  "confidence_basis": "MODEL_SELF_REPORT",
  "extraction": {
    "run_id": 4,
    "schema_version": "engineering-extraction/0.1",
    "pipeline_version": "example-only",
    "model_identifier": "provider/model-to-be-selected",
    "prompt_version": "example-only"
  },
  "origin": "AI",
  "review_status": "AI_EXTRACTED",
  "latest_review_sequence": 1
}
```

This candidate is forbidden for downstream PADS generation regardless of confidence.
Content hashes and complete provenance would be present in a real persisted response.

## Proposed migration and retention

After architecture approval, add seven tables without changing existing document rows.
Bump SQLite schema version 1 -> 2 through an explicit versioned migration; do not edit
the current CREATE IF NOT EXISTS block to silently imply migration support.
Test on a backed-up copy, check foreign keys, old row counts and PDF hashes, and run
the full Phase 1 suite. v0.1 rejects schema version 2, so rollback restores the matched
v1 database backup and v0.1.0 code; do not claim an in-place downgrade.

Run metadata, published claims/evidence and review events are retained for audit.
Keep raw model responses, page images, OCR intermediates and full extracted text out of
these tables; short snippets/regions and hashes suffice for traceability. Failed job
scratch data is cleaned, while failure diagnostics remain. No auto-deletion of approved
lineage. Optional compact export manifests are generated on explicit request, not
duplicated after every run. Treat all derived runtime engineering data as potentially
confidential; Git export is a deliberate reviewed operation.

## Future extension points, not current entities

- Electrical characteristics: quantity, condition, test basis and min/typ/max separately.

- Recommended operating conditions and absolute maximum ratings: distinct categories,
  never interchangeable design limits.

- Register maps: address, field bits, access/reset value, mode and revision context.

- Initialization sequences: ordered actions with conditions/delays and evidence.

- Hardware recommendations: circuit context, constraint, rationale and applicability.

- Detailed mechanics and PCB land patterns: tolerances, coordinate frame, units,
  drawing revision, pad geometry and evidence; never infer land patterns from body size.

Add a reviewed schema version and validators when each domain is authorized. Existing
field envelopes, evidence and approval lineage can be reused. No speculative values,
register tables, geometry or PADS data are created by this proposal.


## Approved foundation refinements

- Package identity includes manufacturer_package_code separately from family/type,
  lead_count and pin_count_basis. Family plus count is never a unique package identity.
  All dimensions, pitch and exposed-pad presence retain independent evidence.
- Pin fields are source_name (verbatim), normalized_name, primary_function,
  alternate_functions, electrical_type and functional_group. Normalization does not
  overwrite source_name. Each alternate function is represented as a separate claim
  (alternate_function.<stable-key>) so its evidence/review is independent.
  Multiplexed pins can have multiple interface-pin membership entities.
- Future lineage: component/orderable variant -> package -> mechanical drawing ->
  manufacturer-recommended land pattern -> PADS PCB decal. Mechanical dimensions and
  land-pattern geometry are separate concepts. A package alone cannot justify a footprint.
  No drawing/land-pattern geometry or PADS generation is implemented in this foundation.
- This implementation uses only a provider-independent fabricated fixture. Synthetic
  results are explicitly marked and accepted only for the matching fixture PDF hash;
  arbitrary production PDFs must not be assigned fabricated engineering values.
- Minimal reviewer setup uses a locally configured account with a salted password hash,
  in-memory expiring sessions, HttpOnly SameSite cookies and CSRF tokens. No RBAC/SSO.
- One explicit worker command processes durable queued runs. The UI can start runs;
  worker failure/expired leases result in FAILED and retry creates a new run. No external
  provider, model download, OCR integration or CC1120 fixture is included.


## Foundation implementation record

The approved synthetic engineering-data subset is now implemented. See
[PHASE2A_FOUNDATION.md](PHASE2A_FOUNDATION.md) for actual table/field mappings, APIs,
reviewer setup, migration/rollback, snapshot limits and validation results. Sections
above describing external providers, OCR or broader profiles remain future architecture.
