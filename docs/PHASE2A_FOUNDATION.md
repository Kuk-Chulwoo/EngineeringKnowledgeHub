# Phase 2A engineering-data foundation

Status: implementation complete for engineering review. No external AI provider,
CC1120 golden extraction, land-pattern geometry or PADS generation is included.
Approved starting baseline: 29d12dbaa1d959aa92c9f9ecfefbf661385c1fec.
Phase 1 release remains v0.1.0 at 391db8dd874d3a6286e52228a17441a9a85d730d.

## Run locally

From C:\workspace\EngineeringKnowledgeHub, use the existing bootstrap instructions.
No new Python or Node packages were required.

Before upgrading a running v1 installation, stop its backend. Keep a backup of its
database and PDF directory together; do not run old v0.1 code against a v2 database.

Configure a trusted local reviewer once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-reviewer.ps1
```

This prompts for an engineer name and a password of at least 12 characters, storing
only a random salt and scrypt password hash in ignored data/reviewer.json.
No default/shared production password is created. Set EKH_REVIEWER_FILE to another
private location if desired. Restart backend after replacing credentials to invalidate
existing sessions.

Run these in three separate terminals:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1
powershell -ExecutionPolicy Bypass -File scripts\start-worker.ps1
```

The three lines above represent separate long-running processes. Open
http://127.0.0.1:5173. The worker polls once per second and makes no network/model calls.
For one queued job only: .venv\Scripts\python.exe -m backend.app.engineering.worker --once.

## Synthetic walkthrough

1. Register a clearly fabricated demo component, such as SYNTH-DEMO-4.
2. Open Engineering / AI Analysis and download the fabricated fixture PDF.
3. Upload that file through the existing Documents panel with a test revision label.
4. Return to Engineering / AI Analysis, sign in as the configured engineer, and select
   the uploaded revision. Start synthetic extraction.
5. Observe QUEUED/RUNNING/SUCCEEDED. Without the worker, the run remains queued and
   can be cancelled. A completed/failed/cancelled run can be retried as a new run.
6. Expand entities to see field values, independent confidence and review status,
   source page/snippet links and append-only review history.
7. Enter a reason and approve/reject individual fields. A stale submission fails rather
   than silently overwriting another decision.
8. After approving one version of every field, create the single-package review snapshot.
   Rejection or accepted correction of a selected field invalidates that snapshot.

The provider accepts ONLY the exact generated fixture PDF hash. It does not interpret
arbitrary uploaded datasheets. A fabricated result is never represented as CC1120 or as
knowledge extracted from a production PDF. Every run/snapshot is marked synthetic;
pads_eligible is always false.

The fixture is generated from Git-managed Python source and contains matching evidence
text on its PDF pages. Generated PDFs remain outside Git. It contains a fabricated package
code, four fabricated leads plus an exposed pad, a multiplexed pin, several interface
entities and individual interface-pin membership claims. Its dimensions and names are
invented examples, not vendor facts.

## Migration design

backend/app/migrations.py contains explicit v1 -> v2 DDL. Database.initialize:
- Accepts versions 0, 1 and 2, rejecting unknown versions.
- Creates the existing v1 schema for a new database, then applies v2.
- For a populated v1 database, first uses SQLite's backup API to make a uniquely named
  coherent .v1-backup-<timestamp> backup alongside the database.
- Acquires BEGIN IMMEDIATE, rechecks the version, applies additive DDL and sets
  PRAGMA user_version=2 in the same transaction.
- Never rewrites components, documents or revisions, and never touches original PDFs.
- Rolls back the new tables/version if migration fails; reopening v2 is idempotent.

Do not downgrade the version pragma. To roll back, restore the matched v1 database
backup plus the v0.1.0 code while services are stopped. Original PDFs must remain
available at their matching storage root.

## Implemented tables

| Table | Purpose |
|---|---|
| extraction_runs | Exact source revision/hash/page count, frozen provider provenance, run states, retries, leases, output hash and diagnostics |
| engineering_entities | Run-local identity/package/pin/interface/membership entities and scope |
| engineering_fields | Typed claim payload, origin, immutable content hash and correction predecessor |
| engineering_field_evidence | Physical PDF page, label, snippet/region, locator version/role, source-text hash |
| engineering_review_events | Append-only sequence, actor, state, reason, exact field hash and optional check metadata |
| approved_snapshots | Explicit run/revision/component/package selection, immutable manifest, reviewer and invalidation metadata |
| approved_snapshot_fields | Exact selected field/hash and human approval-event membership |

All seven have delete guards. Entities, fields, evidence, review events and membership
rows also have update guards. Evidence cannot be appended once a field's initial event
exists. Terminal runs cannot be republished/updated. Snapshot manifests are sealed in
the creation transaction; only ACTIVE -> INVALIDATED eligibility updates are permitted.

The full proposal includes future optional metadata; this foundation uses bounded
provenance_json, payload_json and diagnostics_json for the supported subset. It does not
add speculative provider/OCR settings, full-response storage or extra tables.
The Python schema is engineering-extraction/0.1; the application API remains /api/v1.
Application release display remains v0.1 pending a subsequent reviewed release.

## Schema and deterministic validation

- Allowed entity kinds and per-kind field keys; extra input properties are rejected.
- Package family/type and manufacturer_package_code are separate. lead_count requires
  an integer and explicit LEADS_ONLY / INCLUDING_EXPOSED_PAD / UNSPECIFIED basis.
- Vendor source_name remains distinct from normalized_name, primary_function,
  alternate_function.<key>, electrical_type and functional_group.
- Interface kinds include SPI, UART, I2C, GPIO, RF, POWER, ANALOG, CLOCK_RESET, OTHER.
- Reference target kind, ownership/package scope and interface/pin package consistency.
- Duplicate entity keys, duplicate claims, duplicate pin designators and memberships.
- Pin count agreement, missing/extra pins and exposed-pad consistency; do not invent a
  numeric designator for a vendor exposed pad.
- Positive bounded decimal strings and canonical mm units for package dimensions;
  minimum <= nominal <= maximum, grouped by quantity field prefix.
- PRESENT requires a non-null value and evidence. Unknown/ambiguous claims retain null.
- Confidence 0..1 or null with an explicit basis; confidence never grants approval.
- Matching source revision, physical page bounds, finite normalized region coordinates
  and nonzero region area; a snippet or region is required.
- Source-text hashes are computed/checked. They establish snippet integrity, not semantic
  truth. This deterministic layer does not claim to prove arbitrary model interpretations.
- Provider output can only start AI_EXTRACTED; ENGINEER_APPROVED output is rejected.

Package/orderable -> package mechanical drawing -> recommended land pattern -> PADS
PCB decal remains future lineage. A package entity or body size alone is not a footprint.

## Lifecycle, review and snapshots

One separate worker atomically claims a durable queued job with a 60-second lease.
It verifies original bytes/hash, validates the provider-independent candidate set, and
publishes entities/fields/evidence/initial events plus terminal status in one transaction.
Cancellation, wrong lease, expiry and any terminal state reject publication. A worker
failure yields FAILED with a redacted code; partial output is rolled back.
Expired jobs become FAILED when a worker next polls. There is no autonomous retry;
retry creates a new run and never inherits review status.

AI_CHECKED is supported by internal review infrastructure with checker provenance.
No external AI checker is connected or invoked. It cannot override a human decision.
Human correction requests append immutable fields starting ENGINEER_DRAFT; they preserve
original value/evidence/hash and freeze their own evidence. Accepting a replacement
rejects the previously approved predecessor and invalidates dependent snapshots.
Entity additions or structural corrections require a new extraction run in this scope.

The initial snapshot profile is deliberately conservative: one explicit package and
exactly one approved version of EVERY claim, with no unresolved coverage. Multi-package
snapshots and partial/consumer-specific approval profiles are deferred.
A snapshot records exact field hashes and approval events. Invalidated snapshots remain
auditable and never reactivate; reapproval requires creating a new snapshot.
All snapshots remain synthetic and PADS-ineligible.

## Reviewer trust boundary

The API reads actor identity from a server-side session, never provider/request actor IDs.
Login uses a salted scrypt hash and constant-time comparison. Cookies are HttpOnly and
SameSite=Strict, scoped to /api/v1, with an eight-hour session limit. Mutations require
an allowed loopback Origin and matching CSRF header. Failed logins are rate limited.
Credentials are not sent to the worker and are not committed.

Sessions are in memory: backend restart signs reviewers out. This is one trusted local
account, not production authentication/RBAC. Cookies are not Secure because the local
development URLs use HTTP. Existing Phase 1 endpoints retain their original local-only
access model. Do not expose this application directly to a network.

## APIs

All paths are under /api/v1. New mutation routes require reviewer cookie, trusted Origin
and X-CSRF-Token, except login which establishes the session.

| Method | Path | Purpose |
|---|---|---|
| POST/GET/DELETE | /reviewer/session | Sign in, read current session/CSRF, sign out |
| GET | /engineering/synthetic-fixture/file | Generate/download fabricated fixture PDF |
| POST | /revisions/{id}/extraction-runs | Queue synthetic run; optional retry_of_run_id |
| GET | /revisions/{id}/extraction-runs | Latest 100 runs for a revision |
| GET | /extraction-runs/{id} | Status, provenance, entities/field versions, evidence and history |
| POST | /extraction-runs/{id}/cancel | Cancel queued/running run |
| POST | /engineering-fields/{id}/reviews | Human approve/reject, expected_sequence and reason |
| POST | /engineering-fields/{id}/corrections | New claim and expected_sequence; returns new draft field ID |
| POST | /approved-snapshots | run_id, selected_package_entity_id, exact field_ids |
| GET | /approved-snapshots/{id} | Immutable manifest membership and current eligibility |

Errors: 401 missing/expired session, 403 origin/CSRF/actor violation, 404 missing record,
409 stale state/conflict/ineligible snapshot, 422 invalid candidate/input, 429 rate limit,
503 reviewer not configured. No worker publication endpoint is exposed over HTTP.
Internal storage paths and worker lease tokens are excluded from API responses.

## Validation results

Final automated suite:
- 63 backend tests, including all 16 Phase 1 tests.
- 7 frontend tests, including all 4 Phase 1 interface tests.
- Ruff, TypeScript and Vite production build.

Tests cover populated-v1 preservation/rollback/idempotence, every required invalid-data
category, deterministic fabricated PDF evidence, provider failure atomicity, run restart,
real worker subprocess publication, stale review, AI approval spoofing, correction history,
snapshot approval/invalidation, incomplete selections, forbidden PADS profile, retry,
cancellation, expired leases, terminal publication, immutable audit records, source hash
tampering, local sessions/CSRF/rate limit/expiry and UI review requests.

No live external AI calls, CC1120 extraction or production PDF uploads were performed.
Frontend interaction tests use jsdom and mocked HTTP; backend tests separately exercise
real persistence and the worker process. No manual browser visual/PDF rendering audit
was performed in this phase.

## Known limitations and review

- Synthetic fixture only; external provider integration requires a new authorization.
- No CC1120 golden values; its later fixture must be engineer-curated from a pinned PDF.
- Corrections are exposed via REST; the minimal UI handles review/history and snapshots,
  not a general engineering-data editor.
- No bulk approval, multi-user RBAC, multi-package snapshots, generation profiles,
  OCR engine, semantic evidence checking or large intermediate storage.
- Worker lease is fixed for this fast fixture; a future long-running provider needs
  reviewed timeout/heartbeat policy before integration.
- Latest-100 run listing is bounded; pagination can be added when needed.
- Two existing upstream Starlette/httpx and AnyIO deprecation warnings remain.
- Release v0.1.0 remains untouched. Stop here for engineering review; do not start
  external AI, CC1120 golden extraction or PADS work automatically.
