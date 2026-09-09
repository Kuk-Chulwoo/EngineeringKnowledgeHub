# Literal, allowlisted settings only. Never execute .env.local as PowerShell code.
function Import-EkhLocalEnvironment {
    param([Parameter(Mandatory = $true)][string]$Path)
    $allowedNames = @(
        'EKH_DATABASE_PATH', 'EKH_STORAGE_ROOT', 'EKH_MAX_UPLOAD_MB',
        'EKH_REVIEWER_FILE', 'EKH_EXTERNAL_AI_ENABLED', 'EKH_OPENAI_MODEL',
        'OPENAI_API_KEY', 'EKH_AI_DENIED_REVISIONS'
    )
    $settings = @{}
    $lineNumber = 0
    try { $lines = Get-Content -LiteralPath $Path -Encoding UTF8 -ErrorAction Stop }
    catch { throw 'Unable to read .env.local. Check local file permissions.' }
    foreach ($line in $lines) {
        $lineNumber++
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        if ($trimmed -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            throw "Invalid .env.local format at line $lineNumber. Expected NAME=value."
        }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if ($allowedNames -cnotcontains $name) {
            throw "Unsupported .env.local setting at line $lineNumber. See .env.example."
        }
        if ($settings.ContainsKey($name)) {
            throw "Duplicate .env.local setting at line $lineNumber."
        }
        if ($value.StartsWith('"') -or $value.StartsWith("'")) {
            if ($value.Length -lt 2 -or $value[$value.Length - 1] -ne $value[0]) {
                throw "Unclosed .env.local quote at line $lineNumber."
            }
            $value = $value.Substring(1, $value.Length - 2)
        }
        $settings[$name] = $value
    }
    # Validate the whole file before modifying the current process environment.
    foreach ($name in $settings.Keys) {
        [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
    }
}
