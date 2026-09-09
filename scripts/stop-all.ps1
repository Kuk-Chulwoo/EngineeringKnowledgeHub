$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
. (Join-Path $PSScriptRoot 'process-ownership.ps1')
$runDirectory = Join-Path $projectRoot '.run'; $manifestPath = Join-Path $runDirectory 'services.json'; $lockPath = Join-Path $runDirectory 'launcher.lock'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { Write-Host 'No owned EngineeringKnowledgeHub service set is recorded.'; return }
$lock = $null
try {
    try { $lock = [IO.File]::Open($lockPath, 'CreateNew', 'Write', 'None') } catch { throw 'Another EngineeringKnowledgeHub launcher operation is active.' }
    try { $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } catch { throw 'The launcher manifest is unreadable; no process was stopped.' }
    $hostScript = Join-Path $PSScriptRoot 'service-host.ps1'; $verified = @()
    foreach ($service in @($manifest.services)) {
        $actual = Get-EkhProcessSnapshot -Id ([int]$service.pid)
        if ($null -eq $actual) { continue }
        if (-not (Test-EkhRootIdentity -Expected $service -Actual $actual -HostScript $hostScript)) { throw 'A recorded PID has a different process identity; no process was stopped.' }
        $verified += [pscustomobject]@{ expected = $service; actual = $actual }
    }
    foreach ($item in $verified) {
        $descendants = @(Get-EkhDescendants -RootId $item.actual.pid); [array]::Reverse($descendants)
        foreach ($child in $descendants) { Stop-EkhCapturedProcess -Captured $child }
        Stop-EkhCapturedProcess -Captured $item.actual
    }
    Remove-Item -LiteralPath $manifestPath -Force
    Write-Host 'Stopped the owned EngineeringKnowledgeHub service set and removed launcher state.'
} finally {
    if ($null -ne $lock) { $lock.Dispose(); Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue }
}
