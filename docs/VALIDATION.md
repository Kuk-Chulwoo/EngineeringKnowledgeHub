# Phase 1 engineering review

Validated on Windows, 2026-09-08, in C:\workspace\EngineeringKnowledgeHub.
Python 3.11.15, portable Node.js 22.23.2, npm 10.9.8.
Dependencies are captured in backend/requirements-lock.txt and frontend/package-lock.json.

## Automated results

Command: powershell -ExecutionPolicy Bypass -File scripts/test.ps1

- Backend: 16 passed.
- Ruff: all checks passed.
- Frontend Vitest/Testing Library: 4 passed.
- TypeScript type check and Vite production build: passed.
- npm installation audit: 0 vulnerabilities reported at installation time.

Backend coverage includes creation/search, validation, pagination, duplicate
components, multiple documents/revisions, exact PDF bytes, inline/download headers,
invalid PDFs/metadata, missing resources, upload size limits, failed transaction
cleanup, concurrent revision conflicts, path traversal rejection, unsupported
schema versions and persistence after restart.

The real-process test starts Uvicorn with temporary database/storage and an
OS-assigned loopback port, uploads two revisions over HTTP, stops the process,
restarts it and verifies searchable metadata plus original download bytes.
Only synthetic PDFs are used. No test catalog records were added to default storage.

Frontend tests cover registration/opening overview, upload handler and refreshed
revision history, view/download links, conflict messages and search requests.
jsdom does not connect the simulated FileList to native required-file validation;
the upload test submits the handler explicitly. Actual multipart/PDF transport is
covered by backend API and real-process tests.

## Running service checks

- Uvicorn started on http://127.0.0.1:8000.
- Vite started on http://127.0.0.1:5173.
- Frontend HTTP GET returned 200.
- /api/v1/health through the Vite proxy returned status ok, version 0.1.0.
- Requested local preview handoff to Codex; the UI tool returned queued.
- No manual browser visual/PDF-rendering review was performed.

## Repository checks

origin is https://github.com/Kuk-Chulwoo/EngineeringKnowledgeHub.git.
GitHub default branch is main. Initial architecture, backend and frontend milestones
were committed and pushed successfully. Final validation/documentation commit is
pushed separately; exact final SHA and synchronization result are in the handoff.
git diff --check passed. Tracked inventory contains no uploaded PDFs, runtime
databases, .env, credentials or dependency/runtime folders. Ignore rules were checked
against representative PDF/database/.env/node_modules/.tools paths.

## Remaining engineering review

- Manually exercise the interface with representative vendor datasheets, including
  the Windows browser's embedded PDF viewer; download/new-tab fallback is provided.
- Strict PDF structural validation can reject malformed but browser-readable files.
- Two upstream test dependency deprecation warnings remain (Starlette/httpx and
  AnyIO BlockingPortal); they do not fail tests.
- Local single-user scope: authentication/network deployment is not implemented.
- SQLite case folding is ASCII; non-ASCII text remains searchable literally.
- Back up database and PDFs together with writes stopped. A hard crash between file
  write and metadata commit may leave an orphan file; do not auto-delete without review.
- No AI analysis, engineering extraction or PADS library generation is implemented.
- Approve Phase 1 before creating v0.1.0 tag or authorizing Phase 2.
