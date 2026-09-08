$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
.\.venv\Scripts\python.exe -m backend.app.engineering.setup_reviewer
exit $LASTEXITCODE
