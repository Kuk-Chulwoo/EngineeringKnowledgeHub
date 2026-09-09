$ErrorActionPreference = 'Stop'

function Get-EkhProcessSnapshot {
    param([Parameter(Mandatory = $true)][int]$Id)
    $item = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $Id) -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    [pscustomobject]@{ pid = [int]$item.ProcessId; parentPid = [int]$item.ParentProcessId; creationDate = ([string]$item.CreationDate); executablePath = ([string]$item.ExecutablePath); commandLine = ([string]$item.CommandLine) }
}

function Test-EkhRootIdentity {
    param($Expected, $Actual, [string]$HostScript)
    if ($null -eq $Actual) { return $false }
    return ($Actual.pid -eq [int]$Expected.pid -and $Actual.creationDate -ceq [string]$Expected.creationDate -and
        $Actual.executablePath -ieq [string]$Expected.executablePath -and $Actual.commandLine.Contains($HostScript) -and
        $Actual.commandLine.Contains([string]$Expected.launchId) -and $Actual.commandLine.Contains([string]$Expected.role))
}

function Get-EkhDescendants {
    param([Parameter(Mandatory = $true)][int]$RootId)
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $found = @(); $parents = @($RootId)
    while ($parents.Count -gt 0) {
        $next = @()
        foreach ($process in $all) {
            if ($parents -contains [int]$process.ParentProcessId) {
                $snapshot = [pscustomobject]@{ pid = [int]$process.ProcessId; parentPid = [int]$process.ParentProcessId; creationDate = ([string]$process.CreationDate); executablePath = ([string]$process.ExecutablePath) }
                $found += $snapshot; $next += $snapshot.pid
            }
        }
        $parents = $next
    }
    return @($found)
}

function Stop-EkhCapturedProcess {
    param($Captured)
    $current = Get-EkhProcessSnapshot -Id ([int]$Captured.pid)
    if ($null -eq $current) { return }
    if ($current.creationDate -cne [string]$Captured.creationDate -or $current.executablePath -ine [string]$Captured.executablePath) {
        throw 'A process identity changed during shutdown; no mismatched process was stopped.'
    }
    Stop-Process -Id ([int]$Captured.pid) -Force -ErrorAction Stop
}
