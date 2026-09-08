$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/node-path.ps1"
Set-Location (Join-Path $PSScriptRoot '..\frontend')
npm.cmd run dev
exit $LASTEXITCODE
