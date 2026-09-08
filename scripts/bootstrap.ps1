param([switch]$PortableNode)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (-not (Test-Path .venv\Scripts\python.exe)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
}
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
if ($PortableNode -and -not (Get-Command node -ErrorAction SilentlyContinue)) {
    $version = 'v22.23.2'
    New-Item -ItemType Directory -Force .tools | Out-Null
    $archive = "node-$version-win-x64.zip"
    Invoke-WebRequest "https://nodejs.org/dist/$version/$archive" -OutFile ".tools/$archive"
    Invoke-WebRequest "https://nodejs.org/dist/$version/SHASUMS256.txt" -OutFile .tools/SHASUMS256.txt
    $digest = (Get-FileHash ".tools/$archive" -Algorithm SHA256).Hash.ToLower()
    if (-not (Select-String -LiteralPath .tools/SHASUMS256.txt -SimpleMatch "$digest  $archive")) {
        throw 'Node archive checksum mismatch.'
    }
    Expand-Archive ".tools/$archive" -DestinationPath .tools -Force
}
. "$PSScriptRoot/node-path.ps1"
Push-Location frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally { Pop-Location }
