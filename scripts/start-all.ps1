$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
. (Join-Path $PSScriptRoot 'local-environment.ps1')

$localSettingsPath = Join-Path $projectRoot '.env.local'
if (Test-Path -LiteralPath $localSettingsPath -PathType Leaf) {
    Import-EkhLocalEnvironment -Path $localSettingsPath
    Write-Host 'Loaded local development settings. Values are not displayed.'
} else {
    Write-Host '.env.local is absent. Continuing with existing process settings and local defaults.'
    Write-Host 'For Real AI, copy .env.example to .env.local and configure it locally, then restart all services.'
}
if ($env:EKH_EXTERNAL_AI_ENABLED -ne 'true' -or
    [string]::IsNullOrWhiteSpace($env:EKH_OPENAI_MODEL) -or
    [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    Write-Host 'Real AI is disabled or not fully configured. Backend, Frontend and synthetic extraction remain available.'
}

$shellPath = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $shellPath -PathType Leaf)) {
    $shellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
}
$scripts = @('start-backend.ps1', 'start-frontend.ps1', 'start-worker.ps1')
foreach ($script in $scripts) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $script) -PathType Leaf)) {
        throw 'A required startup script is missing. Restore the project scripts first.'
    }
}
foreach ($script in $scripts) {
    $scriptPath = Join-Path $PSScriptRoot $script
    # Explicitly requested visible windows; settings are inherited, never command-line arguments.
    Start-Process -FilePath $shellPath -WorkingDirectory $projectRoot -WindowStyle Normal -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $scriptPath + '"')
    ) | Out-Null
}
Write-Host 'Started Backend, Frontend and Worker in separate PowerShell windows.'
Write-Host 'Open http://127.0.0.1:5173. Stop each service with Ctrl+C in its own window.'
