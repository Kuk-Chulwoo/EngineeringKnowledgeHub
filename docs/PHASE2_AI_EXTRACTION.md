# Phase 2A: AI-assisted datasheet knowledge extraction

Status: APPROVED with engineering-data foundation refinements; external AI integration deferred.
Baseline: v0.1.0, approved commit 391db8dd874d3a6286e52228a17441a9a85d730d.
The annotated release tag was pushed before preparing this proposal.
This document records the approved architecture. The implemented synthetic foundation
and deferred provider-specific details are described in [the implementation guide](PHASE2A_FOUNDATION.md).

## Objective and boundary

Convert one existing immutable PDF revision into evidence-backed engineering candidates
for human review. Never change the uploaded PDF, document metadata or component catalog
automatically. Extracted identity can disagree with the catalog; show the discrepancy,
do not silently reconcile it. Existing v0.1 upload, view, search and download behavior
remains unchanged.

Initial scope:

- Component identity: manufacturer, part number, description.

- Package: family/type, pin count, body length/width/height, pitch and exposed-pad presence.

- Pins: number/designator, name, electrical type/function and optional functional group.

- Interfaces: SPI, UART, I2C, GPIO, RF, power, analog, clock/reset and other identified
  interfaces, including evidenced pin memberships and roles.

- Field-level evidence, confidence, extractor/model versions and review history.

Exclude AI/PADS library generation, footprint geometry, automatic catalog edits,
autonomous approval and detailed electrical/register/design-rule extraction.
Basic package body dimensions belong in 2A; detailed mechanical tolerances and land
patterns are later work. Package dimensions must never be treated as a PCB land pattern.

## Proposed flow

1. Engineer chooses an existing revision and, where known, target package/orderable variant.
2. Service resolves revision -> document -> component and captures the stored SHA-256.
   Verify original bytes against that hash before extraction; fail on missing/mismatched data.
3. Create a durable extraction run with exact revision, schema/pipeline/prompt versions,
   provider/model identification and extraction settings. A retry creates a new run.
4. Worker reads the PDF through the existing Storage interface. Parse text/tables with
   page coordinates; render/OCR only pages needing it, in bounded temporary storage.
5. Provider adapter receives the minimum relevant pages/regions for the requested fields.
   Produce only the constrained schema. Treat PDF text as untrusted input, never instructions
   authorizing tools, network access or changes to the application.
6. Deterministic validators check types, units, source pages, package scope, pin identities,
   references and evidence. Optional AI checking appends a separate check event.
7. Publish a complete candidate set atomically; terminal run output is immutable.
   A run may succeed with missing/ambiguous fields and explicit coverage diagnostics.
   Invalid provider output is not exposed as engineering knowledge.
8. Engineer reviews individual fields against original PDF pages, approves/rejects values,
   or creates a correction with its own evidence and provenance.
9. After field review, an engineer explicitly approves a bounded snapshot for a specific
   component, revision, package variant and intended use. No downstream consumer reads
   directly from raw candidates or from an implicit "latest" run.

Trace: immutable PDF revision -> extraction run -> entity -> field -> evidence ->
append-only review events -> explicit approved snapshot.

## Module boundaries (proposed, not created)

| Module | Responsibility |
|---|---|
| backend API routes | Start/status/read runs and submit reviews; transport validation only |
| extraction service | Ownership, revision/hash verification, run lifecycle, publication |
| ai PDF adapter | Text/table extraction and optional region/OCR coordinates |
| ai provider adapter | Model invocation and constrained candidate response |
| engineering validators | Typed field contract, evidence, scope, conflict/completeness checks |
| engineering repository | Proposed new tables, atomic writes, append-only records |
| review service | Authenticated reviewer actions, corrections and approval transitions |
| approved-data service | Explicit snapshot approval and fail-closed consumer boundary |
| React extraction/review panel | Progress, candidate fields, evidence viewer and review actions |

Storage remains responsible for original binaries; provider logic must not depend on
LocalStorage filesystem paths. New extraction/review endpoints are additive.
For a small local 2A implementation, use one separate worker process polling SQLite with
short claim transactions and a lease. Do not introduce Redis/Celery or distributed
infrastructure initially. Keep model calls outside database transactions.

Proposed run states: QUEUED -> RUNNING -> SUCCEEDED | FAILED | CANCELLED.
A worker atomically claims a queued run; only its live lease token may publish.
After worker loss/lease expiry, mark the abandoned run FAILED with a reason; an explicit
retry creates a new run linked by retry_of_run_id. Cancellation prevents late publication.
Partial work remains scratch output and cannot be reviewed or approved.
Status and error metadata persist across backend/worker restart.
Bound file/page count, render resolution, tokens, wall time and concurrent jobs.

## Evidence and review rules

The companion [engineering data model](ENGINEERING_DATA_MODEL.md) defines storage and
field shapes. Every candidate value resolves to exactly one immutable source revision
and the pipeline/model that produced it. Evidence uses one-based physical PDF page
numbers, optional printed page labels, short verbatim snippets and/or normalized regions.
Page coordinates refer to the displayed, rotation-corrected PDF CropBox, origin top-left.

Evidence is support, not decoration: a valid page number alone does not establish a claim.
Normalized or inferred values record the transformation and the actual supporting text.
Confidence is nullable and never a substitute for evidence or approval. Model confidence
is not a calibrated probability. Unknown values remain unknown; do not fabricate a pin,
dimension or interface to fill the schema.

Required statuses:

- AI_EXTRACTED: model-created candidate, not approved.

- AI_CHECKED: separately checked candidate, still not approved.

- ENGINEER_APPROVED: exact immutable field version accepted by a human.

- ENGINEER_REJECTED: exact candidate rejected by a human.

- ENGINEER_DRAFT: additional state for a human correction awaiting an explicit decision.

AI actors may never emit engineer review events. Human decisions record reviewer ID,
timestamp, reason, and the field hash/version reviewed. A deterministic validator pass
is recorded separately and does not by itself mean AI_CHECKED.
Approval and correction semantics are detailed in the model document.

Before implementing review, introduce a minimal trusted local reviewer identity:
a configured engineer account authenticates locally and receives a server-side session.
Actor identity comes from the session, never request JSON or model output. The worker
has no human session credentials; review mutations require session and CSRF protection.
No SSO/RBAC platform is proposed for 2A. Phase 1 endpoints retain their local-only behavior.

## Downstream approval boundary

Future PADS consumers must request an explicit ENGINEER_APPROVED snapshot through
approved-data service. Raw extraction tables and AI_CHECKED outputs are ineligible.
The gate verifies all selected fields are still engineer-approved, evidence/hash lineage,
package/variant coherence, resolved conflicts and a consumer-specific completeness profile.
Approval does not prove a dataset is complete enough for symbol or footprint generation.

A later PADS generator will have to supply a reviewed validation profile; without one,
PADS export remains disabled. Footprints additionally require approved land-pattern
geometry not provided by 2A. No generator, PADS output API or PADS file is built in 2A.
If a selected field is later rejected or superseded, invalidate affected snapshots
transactionally. Existing snapshots remain auditable but cannot authorize new generation.

## Storage, privacy and reproducibility

Keep small typed candidates, concise evidence, audit metadata and approved manifests in
SQLite, separate from original document metadata. Do not copy PDF bytes into extraction
records or save a full extracted text copy per run. Regenerate page views from the source.
Temporary OCR/render/model response files have a bounded lifetime and are deleted after
success/failure; cleanup also runs for abandoned jobs. An optional future bounded cache
is keyed by revision hash + parser version + page, never the canonical record.

Store exact provider/model identifier (including a returned immutable model version when
available), prompt template version/hash, extractor/checker versions, schema version,
settings and request/response hashes. Record when a provider alias is not reproducible.
Do not retain full raw responses by default or put secrets/full PDF text into logs.

Default to no external model transmission until a provider and document data policy are
configured and an engineer explicitly starts a run that identifies the external destination.
Provider selection is deferred to architecture review. Local providers use the same adapter.
Datasheet-derived data may also be confidential: exclude runtime extraction/cache files
from Git. Only intentionally reviewed, suitable small golden manifests/engineering exports
may enter Git. Never auto-commit model output or production PDFs.

## Proposed API and UI contract (not implemented)

| Method/path | Purpose |
|---|---|
| POST /api/v1/revisions/{id}/extraction-runs | Start explicit extraction; no request-supplied source path |
| GET /api/v1/revisions/{id}/extraction-runs | History of runs for this revision |
| GET /api/v1/extraction-runs/{id} | Status, settings, coverage, diagnostics and candidate entities |
| POST /api/v1/extraction-runs/{id}/cancel | Cancel unfinished work |
| POST /api/v1/engineering-fields/{id}/reviews | Append authorized review with expected review sequence |
| POST /api/v1/engineering-fields/{id}/corrections | Create new human draft; original remains unchanged |
| POST /api/v1/approved-snapshots | Approve an explicit field manifest after review/gate checks |
| GET /api/v1/approved-snapshots/{id} | Auditable manifest and present eligibility |

The component Documents panel offers extraction for an exact revision. A new review panel
shows run/version, package scope, coverage gaps and per-field statuses. Selecting evidence
opens the original PDF at its cited page, highlighting a region when available.
Confidence never uses green "approved" styling. Review actions remain human actions.
A failed extraction must not affect existing document viewing/downloading.

## CC1120 golden-reference plan

Use Texas Instruments CC1120 first. TI's product page currently links its Rev. H datasheet;
this is a discovery reference, not a pinned test input:
[TI CC1120 product and documentation](https://www.ti.com/product/CC1120).
Candidate PDF locator: https://www.ti.com/lit/ds/symlink/cc1120.pdf.
A mutable vendor URL is not an immutable source identifier.

After architecture approval:
1. Engineer obtains the chosen official PDF and uploads it using Phase 1.
2. Record source URL, retrieval date, document/revision label, file hash, page count and
   catalog/variant selection in a small golden manifest. Revision IDs are local database
   IDs; use SHA-256 to resolve the same fixture across test databases.
3. Manually establish expected identity, package, pins (including exposed-pad treatment)
   and interfaces with exact page evidence. Do not hard-code package/pin facts from
   memory or silently mix CC112x family documentation into the CC1120 datasheet.
4. Engineer approves the expected structured values; only this curated manifest is truth.
   Do not use one model's answer as the expected result for another model.
5. Verify vendor/source terms before Git-managing curated derived data. Keep original
   PDF outside Git. CI resolves an approved fixture from external test storage or runs
   synthetic tests; never downloads an unpinned "latest" PDF during a test.

Golden assertions: exact identity/variant, exact pin designators/names, no pin omissions
or duplicates, no invented interfaces, correct package units/tolerances, evidence for
every populated leaf and proper unknowns where the selected document is insufficient.
UART/I2C/etc. are schema options, not assumptions about CC1120 support.
If a required detail exists only in a user guide or package drawing, report it missing
for this run; later ingest that document as its own immutable revision. Cross-document
synthesis is explicitly deferred.

## Proposed acceptance and implementation sequence after review

1. Approve this architecture, field vocabulary, evidence convention, reviewer identity,
   provider policy and snapshot gate.
2. Implement and test an additive migration on copies of v1 databases; verify every old
   record/hash and all Phase 1 APIs, with backup/restore and schema-version handling.
3. Implement typed schema/validators and provider-independent synthetic fixtures first.
4. Add bounded extraction runner/provider adapter with error/cancellation/restart tests.
5. Add evidence/review workflow and server-enforced approval boundary.
6. Curate CC1120 golden data, then evaluate extraction against it.
7. Run Phase 1 regressions and adversarial provenance/approval tests before release review.

Release gates: no PDF/document metadata mutation; no unresolved source hash mismatch;
100% of populated fields carry valid revision/page evidence; all source references remain
valid after restart; human-approved outputs are never inferred from confidence.
Pin table and package values in the approved golden snapshot must exactly match the
engineer-curated expectations. Measure raw extraction coverage/error separately; missing
or incorrect candidates cannot pass simply because some fields are approved.

Required negative tests include evidence from another revision, page out of range,
wrong package variant, unsupported units, duplicate/missing pins, hallucinated interface
membership, model-written "ENGINEER_APPROVED", stale reviewer submission, expired worker
publication, cancellation, re-extraction overwriting review, and use of rejected/invalidated
snapshots. Fixture absence must be explicit, never a false golden-test pass.

Future scope: electrical characteristics, recommended operating conditions, absolute
maximum ratings, register maps, initialization sequences, hardware recommendations,
detailed mechanical dimensions and recommended PCB land patterns. Keep each concept
separate with units, conditions and source evidence; do not implement them in 2A now.


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
