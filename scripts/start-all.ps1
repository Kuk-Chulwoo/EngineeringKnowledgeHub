$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
. (Join-Path $PSScriptRoot 'local-environment.ps1')
. (Join-Path $PSScriptRoot 'process-ownership.ps1')
$runDirectory = Join-Path $projectRoot '.run'; $manifestPath = Join-Path $runDirectory 'services.json'; $lockPath = Join-Path $runDirectory 'launcher.lock'
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$lock = $null
try {
    try { $lock = [IO.File]::Open($lockPath, 'CreateNew', 'Write', 'None') } catch { throw 'Another EngineeringKnowledgeHub launcher operation is active.' }
    $hostScript = Join-Path $PSScriptRoot 'service-host.ps1'
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        try { $existing = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } catch { throw 'The launcher manifest is unreadable; no process was started or stopped.' }
        $live = 0; $mismatch = 0
        foreach ($service in @($existing.services)) {
            $actual = Get-EkhProcessSnapshot -Id ([int]$service.pid)
            if ($null -ne $actual) {
                if (Test-EkhRootIdentity -Expected $service -Actual $actual -HostScript $hostScript) { $live++ } else { $mismatch++ }
            }
        }
        if ($live -gt 0) { throw 'An owned EngineeringKnowledgeHub service set is already running.' }
        if ($mismatch -gt 0) { throw 'The launcher manifest does not match current process identity; inspect .run before retrying.' }
        Remove-Item -LiteralPath $manifestPath -Force
        Write-Host 'Removed stale launcher state; no stale PID was stopped.'
    }
    $localSettingsPath = Join-Path $projectRoot '.env.local'
    if (Test-Path -LiteralPath $localSettingsPath -PathType Leaf) {
        Import-EkhLocalEnvironment -Path $localSettingsPath
        Write-Host 'Loaded local development settings. Values are not displayed.'
    } else {
        Write-Host '.env.local is absent. Continuing with existing process settings and local defaults.'
        Write-Host 'For Real AI, copy .env.example to .env.local and configure it locally, then restart all services.'
    }
    if ($env:EKH_EXTERNAL_AI_ENABLED -ne 'true' -or [string]::IsNullOrWhiteSpace($env:EKH_OPENAI_MODEL) -or [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
        Write-Host 'Real AI is disabled or not fully configured. Backend, Frontend and synthetic extraction remain available.'
    }
    $shellPath = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path -LiteralPath $shellPath -PathType Leaf)) { $shellPath = (Get-Command powershell.exe -ErrorAction Stop).Source }
    $launchId = [guid]::NewGuid().ToString(); $services = @()
    foreach ($role in @('backend', 'frontend', 'worker')) {
        $process = Start-Process -FilePath $shellPath -WorkingDirectory $projectRoot -WindowStyle Normal -PassThru -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $hostScript + '"'), '-Role', $role, '-LaunchId', $launchId
        )
        $actual = Get-EkhProcessSnapshot -Id $process.Id
        if ($null -eq $actual) { throw 'A launched service process could not be identified.' }
        $services += [ordered]@{ role = $role; pid = $actual.pid; creationDate = $actual.creationDate; executablePath = $actual.executablePath; launchId = $launchId }
        [ordered]@{ schemaVersion = 1; projectRoot = $projectRoot; launchId = $launchId; services = $services } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    }
    Write-Host 'Started Backend, Frontend and Worker in separate PowerShell windows.'
    Write-Host 'Open http://127.0.0.1:5173. Run .\scripts\stop-all.ps1 for an ownership-checked shutdown.'
} finally {
    if ($null -ne $lock) { $lock.Dispose(); Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue }
}
