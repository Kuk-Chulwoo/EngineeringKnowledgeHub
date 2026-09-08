# Git workflow

Workspace: C:\workspace\EngineeringKnowledgeHub
Repository: https://github.com/Kuk-Chulwoo/EngineeringKnowledgeHub
origin: https://github.com/Kuk-Chulwoo/EngineeringKnowledgeHub.git
Stable/default branch: main.

Verify git status, git remote -v and git branch before modifications. Initial v0.1
uses small meaningful commits on main. Larger future work uses feature branches
and reviewed pull requests. Do not commit broken code to main.

Before each stable milestone commit/push: run relevant tests, review git diff and
staged diff, inspect git status, verify no credentials, environment files, runtime
SQLite databases or uploaded PDFs are staged. Push to origin/main and verify HEAD
matches origin/main and git ls-remote origin refs/heads/main.

Code, schemas, templates, tests, docs and reviewed engineering/PADS source belong in
Git. Production datasheets and large files belong in server storage, metadata in the
database. .env.example contains placeholders only. Never commit .env or secrets.
Tags use v0.1.0 etc.; do not create a release tag until engineering review passes.
