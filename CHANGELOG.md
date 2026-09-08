# Changelog

## 0.1.0 — unreleased, engineering review pending

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

No release tag: engineering review is required first. Phase 2 has not started.
