param(
    [Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend', 'worker')][string]$Role,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f-]{36}$')][string]$LaunchId
)
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot ("start-{0}.ps1" -f $Role)
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) { throw 'Required service script is missing.' }
& $scriptPath
