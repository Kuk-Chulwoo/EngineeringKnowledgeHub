# Use an installed Node.js, or the optional ignored portable runtime.
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    $runtime = Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot '..\.tools') -Directory -Filter 'node-*-win-x64' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $runtime) { throw 'Install Node.js 22.12+ or run scripts/bootstrap.ps1 -PortableNode.' }
    $env:PATH = $runtime.FullName + ';' + $env:PATH
}
