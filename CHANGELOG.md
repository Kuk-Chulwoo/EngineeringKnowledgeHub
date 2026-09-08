# Changelog

## Unreleased

- Implement Phase 2A engineering-data foundation with no external AI provider.
- Add additive SQLite v1-to-v2 migration and seven audit/engineering tables.
- Add typed schema, deterministic validators and fabricated synthetic fixture.
- Add durable runs, immutable evidence, local reviewer sessions, correction history
  and exact-field approved snapshots with invalidation.
- Add minimal Engineering / AI Analysis review UI and worker/reviewer startup scripts.
- Validate with 63 backend tests, 7 frontend tests, lint and frontend build.
- Foundation implementation awaits engineering review; no new release tag.

## 0.1.0 — 2026-09-08

- Establish the requested local workspace and GitHub main branch.
- Document architecture, data model, roadmap and Git workflow before implementation.
- Add typed FastAPI REST endpoints and persistent SQLite metadata.
- Model components, logical documents and immutable document revisions.
- Preserve original PDFs with opaque keys, SHA-256, upload dates and vendor metadata.
- Validate PDFs, enforce upload limits, reject duplicate revisions and clean failed writes.
- Add component search and pagination.
- Add React registration, component catalog, overview, revision history, PDF viewer
  and original downloads; reserve future engineering tabs.
- Add Windows bootstrap/start/test scripts and locked dependencies.
- Add 16 backend tests (including real-process restart) and 4 interface tests.
- Keep production datasheets, runtime databases and secrets out of Git.

Phase 1 approved. Annotated v0.1.0 tag points to 391db8dd874d3a6286e52228a17441a9a85d730d.
Phase 2A foundation is implemented in Unreleased; external AI and PADS remain deferred.
