$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
.\.venv\Scripts\python.exe -m ruff check backend tests
if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
. "$PSScriptRoot/node-path.ps1"
Push-Location frontend
try {
    npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
