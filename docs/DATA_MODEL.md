# Data model

- components: integer id; manufacturer; part_number; description; category; package;
  created_at UTC. Manufacturer + part_number are unique (SQLite NOCASE).
- documents: integer id; component_id foreign key; title. Unique title per component.
  A logical document may be a datasheet, errata or application note.
- revisions: integer id; document_id foreign key; revision label; optional
  datasheet_date ISO date; original filename; uploaded_at UTC; opaque storage_key;
  size_bytes; SHA-256. Revision label is unique within a document.
- schema version: SQLite user_version, initially 1. Later releases require explicit
  migration scripts, preserving existing data; unsupported versions fail startup.

Revision metadata lives on revisions, not components. A component detail response
nests documents and their revisions. No update/delete revision API exists in v0.1.
Missing dates are null, never invented. Revision ordering is upload/id order rather
than lexical ordering of vendor labels.

Future normalized engineering data must reference immutable revision IDs and source
pages. Reviewed JSON and PADS source artifacts may be Git-managed; runtime metadata
and uploaded binaries remain outside Git.
