# Engineering Knowledge Hub

Phase 1 / v0.1: component catalog and immutable datasheet revision management.
FastAPI + Python, SQLite, React + TypeScript. The Phase 1 release reserved AI analysis
and PADS generation for later phases. Phase 1 is approved and tagged v0.1.0.
Phase 2A architecture: [architecture](docs/PHASE2_AI_EXTRACTION.md) and
[data model](docs/ENGINEERING_DATA_MODEL.md). The synthetic engineering-data foundation
is approved. See [setup, APIs and validation](docs/PHASE2A_FOUNDATION.md).
Phase 2B adds opt-in real AI extraction and manually curated golden evaluation.
See [Phase 2B architecture and exact CC1120 manual steps](docs/PHASE2B_REAL_EXTRACTION.md).
External transmission is disabled by default. No real CC1120 accuracy result is claimed.
PADS and footprint generation remain unimplemented.

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

### Start all local services

One-time setup from the project root (do not overwrite an existing `.env.local`):

```powershell
copy .env.example .env.local
```

Edit `.env.local` in your editor. For Real AI, set `EKH_EXTERNAL_AI_ENABLED=true`,
your `EKH_OPENAI_MODEL`, and your actual `OPENAI_API_KEY`. The example has Real AI
disabled and empty model/key values. Never paste credentials into console commands,
logs or Git. `.env.local` is already excluded by `.gitignore`.

Daily startup:

```powershell
.\scripts\start-all.ps1
```

If execution policy blocks the script, use
`powershell -ExecutionPolicy Bypass -File scripts\start-all.ps1`.
The launcher moves to the project root, loads `.env.local` into its current process,
and opens separate Backend, Frontend and Worker PowerShell windows using the existing
individual start scripts. Settings reach child processes through environment inheritance,
never command-line arguments or console dumps. Only allowlisted settings in `.env.example`
are accepted. File values override inherited values; empty values clear an inherited setting.
Use literal `NAME=value` lines, optional matching single/double quotes and full-line `#`
comments. No variable expansion, command execution, multiline values or inline comments.
Malformed/unknown/duplicate settings stop startup before any child is launched; errors
show a line number without echoing the setting or value.

Without `.env.local`, startup uses existing shell settings and application defaults;
Backend/Frontend and offline synthetic extraction remain available. Real AI configuration
guidance is printed without requesting secrets. Existing shell variables remain effective.
Changing the file requires restarting the services. Starting a worker processes already
queued runs, including explicitly authorized real runs when external AI is enabled.

Stop with **Ctrl+C in each service window**, then close the windows. `stop-all.ps1` is
intentionally omitted: the existing scripts spawn descendant Python/npm/Node processes,
and process names, ports or saved PIDs cannot safely establish ownership across PID reuse
and restarts. The launcher does not terminate any process. Stop old instances before
running it again to avoid occupied ports or duplicate workers.

### Individual startup (unchanged)

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

See .env.example. `start-all.ps1` loads root `.env.local`; the application and individual
start scripts still read shell environment variables and do not load env files themselves:

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
Phase 2B real AI extraction is opt-in; PADS generation remains unavailable.

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
- backend/app/ai/: native PDF parsing, provider adapters, focused extraction and golden comparison.
- ai/, pads/: original top-level placeholders; PADS generation remains deferred.
- scripts/: Windows bootstrap, startup and verification.
- docs/: architecture, model, roadmap, Git workflow and API reference.

Technical references: [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/)
and [Vite guide](https://vite.dev/guide/).


## Phase 2A quick start

Configure a local reviewer with scripts/setup-reviewer.ps1, then run the backend,
frontend and scripts/start-worker.ps1 in separate terminals. Use the documented
PowerShell -ExecutionPolicy Bypass -File invocation from the startup examples above.
The new Engineering / AI Analysis tab provides a fabricated fixture PDF to download,
upload and select for synthetic extraction. No external AI provider is connected.

The first v2 startup creates an automatic SQLite v1 backup and applies an additive
migration. Stop the old backend before upgrading; v0.1 cannot open a v2 database.
Review [the complete foundation guide](docs/PHASE2A_FOUNDATION.md) before upgrading.
