# Architecture

## v0.1
React + TypeScript + Vite provides a component browser, registration form,
overview and documents panels. A module registry reserves future engineering tabs.
The UI calls a versioned REST API through Vite's /api proxy.

FastAPI routes validate transport input; services own component/document workflows;
a repository owns SQL and transactions; a storage protocol owns binary operations.
SQLite persists metadata, with foreign keys and schema versioning. Use one local
backend process initially. Configuration selects database and storage paths.

A component has multiple logical documents; each document has immutable revisions.
Uploads use opaque UUID storage keys, retain original bytes, record size/hash and
UTC upload time, reject invalid PDFs and never overwrite existing files.
A failed database transaction removes the just-written file. A process crash between
file write and database commit may leave an orphan; backup/reconciliation is an
operational responsibility, not automatic deletion.

## Storage migration
Local storage implements put/open/delete using relative opaque keys. A future NAS
can use another configured root; object storage can implement the same protocol.
Database metadata stores keys, never absolute server paths. Back up database and
files together while writes are stopped. Never store uploaded PDFs in Git.

## Future modules (not implemented)
ai/ will hold extraction and analysis jobs, revision comparison, interfaces, design
rules and firmware assistance. Store output with revision ID, source page/bounding
box, tool/model version, confidence and review status. A future search provider can
index extracted text without changing component search clients.
pads/ will consume reviewed engineering data to generate PADS Logic VX2.11 CAE
decals, Layout VX2.11 PCB decals and Part Types, with explicit validation.
No AI/PADS engines, queues or speculative engineering tables are implemented.

## Trust boundary
v0.1 is a local single-user development application, bound to loopback, without
authentication. Before network deployment add authentication/authorization, TLS,
request limits at the proxy, malware scanning and operational backups. PDF validation
checks structure, not safety of active PDF content. Browser PDF support varies;
download remains available.
