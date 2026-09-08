# Engineering Knowledge Hub

Phase 1 / v0.1: component catalog and immutable datasheet revision management.
FastAPI + Python, SQLite, React + TypeScript. AI analysis and PADS generation are
reserved for later phases. Phase 1 is approved and tagged v0.1.0.
Phase 2A proposals: [architecture](docs/PHASE2_AI_EXTRACTION.md) and
[data model](docs/ENGINEERING_DATA_MODEL.md). Implementation awaits architecture review.

## Windows quick start

Workspace: `C:\workspace\EngineeringKnowledgeHub`
Remote: https://github.com/Kuk-Chulwoo/EngineeringKnowledgeHub.git

Prerequisites: Git, Python 3.11+, Node.js 22.12+ (or the portable option below).
From PowerShell:

```powershell
cd C:\workspace\EngineeringKnowledgeHub
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -PortableNode
```

The portable option downloads a pinned official Node runtime into ignored .tools/
and checks its SHA-256 against the official manifest. Omit -PortableNode if Node
is installed. Python dependencies and Node dependencies are locked.

Start these in two PowerShell terminals:

```powershell
cd C:\workspace\EngineeringKnowledgeHub
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
```

```powershell
cd C:\workspace\EngineeringKnowledgeHub
powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1
```

Open http://127.0.0.1:5173. API documentation: http://127.0.0.1:8000/docs.
Stop each service with Ctrl+C. The scripts run from any current directory.
If ports 8000/5173 are occupied, stop the existing Hub instance before restarting.

## Use

1. Register a manufacturer/part number and optional description/category/package.
2. Select the component and open Documents.
3. Enter document title, revision, optional vendor date, and choose a PDF.
4. Upload. A title groups revisions; use a new title for another document.
5. View in the embedded browser viewer or a new tab; download original bytes.
6. Search by manufacturer, part number, description or category.
7. Restart services: records and original PDFs remain on disk.

Duplicate manufacturer/part pairs and duplicate document revision labels return
a conflict. No previous revision is overwritten. Damaged, empty, encrypted and
oversized PDFs are rejected. Default maximum file size is 50 MiB.
Dates are optional. Upload timestamps are stored in UTC and displayed locally.

## Configuration and storage

See .env.example. The application reads shell environment variables, not .env files:

```powershell
$env:EKH_DATABASE_PATH = 'data/hub.sqlite3'
$env:EKH_STORAGE_ROOT = 'data/datasheets'
$env:EKH_MAX_UPLOAD_MB = '50'
```

Relative paths resolve against the project root. Set variables in the backend
terminal before startup. SQLite metadata and PDFs must be backed up together with
writes stopped. Storage filenames are opaque UUIDs; original filenames are metadata.
Runtime PDFs, databases, .env, logs, virtual environments and dependencies are ignored.
Never commit production datasheets, credentials or access tokens.

v0.1 is for local single-user use and binds to loopback. Network deployment,
authentication, advanced PDF sanitization and production operations are future work.
There is no AI or PADS generation in this version.

## Verification

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

Backend tests create synthetic PDFs in temporary directories; no vendor files are
required. Frontend tests verify forms, search, errors and revision viewing.
See docs/VALIDATION.md for acceptance results and remaining review items.

## Repository map

- backend/app/: REST routes, typed schemas, service, repository, SQLite and storage.
- frontend/src/: component browser, overview/documents panels and future tab registry.
- tests/: backend API, persistence, conflict and failure-path tests.
- data/datasheets/: ignored original PDFs; data/components/: future reviewed exports.
- ai/, pads/: placeholders only.
- scripts/: Windows bootstrap, startup and verification.
- docs/: architecture, model, roadmap, Git workflow and API reference.

Technical references: [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/)
and [Vite guide](https://vite.dev/guide/).
