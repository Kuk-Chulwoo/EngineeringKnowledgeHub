# v0.1 REST API

Base path: /api/v1. OpenAPI JSON: /openapi.json. Interactive docs: /docs.

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Application version/status |
| POST | /components | Register component (JSON) |
| GET | /components?q=&limit=50&offset=0 | Search with total count and pagination |
| GET | /components/{id} | Component, documents and revisions |
| POST | /components/{id}/revisions | Upload PDF with multipart metadata |
| GET | /revisions/{id}/file | Inline original PDF |
| GET | /revisions/{id}/file?download=true | Download original PDF |

Component input: manufacturer and part_number (required, 1–200 trimmed chars),
description (0–4000), category and package (0–200).
Multipart fields: file; revision (required); document_title (default Datasheet);
datasheet_date (optional ISO YYYY-MM-DD; omit if unknown).
Response revision: id, document_id, revision, datasheet_date, filename,
uploaded_at, size_bytes and sha256. Internal storage keys are excluded.

Search matches any substring in manufacturer, part number, description or category.
SQLite lower()/NOCASE provide ASCII case folding; non-ASCII text can be stored and
searched literally. Future full-text/Unicode search can replace repository search.

201 created; 404 missing component/revision/file; 409 duplicate identity/revision;
413 size limit; 422 invalid metadata/PDF. JSON errors use detail.
Complete request bodies are capped at file limit + 1 MiB multipart overhead.
No modification/deletion endpoints exist for historical revisions.


## Phase 2A additions

See [Phase 2A foundation API table](PHASE2A_FOUNDATION.md#apis) for extraction,
local reviewer/session, correction and snapshot endpoints. Phase 1 routes above retain
their existing contract.
