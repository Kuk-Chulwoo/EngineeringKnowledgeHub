"""Exercise launcher ownership with mocked processes; never starts services or uses real keys."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell launcher")
ROOT = Path(__file__).resolve().parents[1]
SCRIPT_NAMES = ("start-all.ps1", "stop-all.ps1", "service-host.ps1", "process-ownership.ps1", "local-environment.ps1", "start-backend.ps1", "start-frontend.ps1", "start-worker.ps1")


def exercise(tmp_path, *, mode="normal", env_text=None):
    project = tmp_path / "workspace with spaces"; scripts = project / "scripts"; scripts.mkdir(parents=True)
    for name in SCRIPT_NAMES:
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    if env_text is not None:
        (project / ".env.local").write_text(env_text, encoding="utf-8")
    run = project / ".run"; run.mkdir(); launch_id = "11111111-1111-1111-1111-111111111111"
    if mode in {"stale", "mismatch"}:
        manifest = {"schemaVersion": 1, "launchId": launch_id, "services": [{"role": "backend", "pid": 777, "creationDate": "old", "executablePath": "fake-powershell.exe", "launchId": launch_id}]}
        (run / "services.json").write_text(json.dumps(manifest), encoding="utf-8")
    harness = tmp_path / "harness.ps1"
    harness.write_text(r'''$ErrorActionPreference = 'Stop'
$script:processes = @{}; $script:stopped = @(); $script:nextPid = 1000
$hostPath = Join-Path (Join-Path $env:EKH_TEST_PROJECT 'scripts') 'service-host.ps1'
$script:processes[900] = [pscustomobject]@{ ProcessId=900; ParentProcessId=1; CreationDate='unrelated-time'; ExecutablePath='unrelated.exe'; CommandLine='unrelated' }
if ($env:EKH_TEST_MODE -eq 'mismatch') { $script:processes[777] = [pscustomobject]@{ ProcessId=777; ParentProcessId=1; CreationDate='different'; ExecutablePath='unrelated.exe'; CommandLine='unrelated' } }
function Start-Process {
  param($FilePath,$WorkingDirectory,$WindowStyle,$ArgumentList,[switch]$PassThru)
  $script:nextPid++; $id=$script:nextPid; $role=$ArgumentList[6]; $launch=$ArgumentList[8]
  $script:processes[$id] = [pscustomobject]@{ ProcessId=$id; ParentProcessId=1; CreationDate=('time-'+$id); ExecutablePath=$FilePath; CommandLine=($hostPath+' -Role '+$role+' -LaunchId '+$launch) }
  $childId = $id + 100; $script:processes[$childId] = [pscustomobject]@{ ProcessId=$childId; ParentProcessId=$id; CreationDate=('child-time-'+$id); ExecutablePath='owned-child.exe'; CommandLine='owned-child' }
  [pscustomobject]@{ Id=$id }
}
function Get-CimInstance { param($ClassName,$Filter,$ErrorAction); if ($Filter -match '(\d+)$') { return $script:processes[[int]$Matches[1]] }; return @($script:processes.Values) }
function Stop-Process { param($Id,[switch]$Force,$ErrorAction); $script:stopped += [int]$Id; $script:processes.Remove([int]$Id) }
try {
  . (Join-Path $env:EKH_TEST_PROJECT 'scripts/start-all.ps1')
  if ($env:EKH_TEST_MODE -eq 'mismatch') { throw 'Mismatch state was accepted' }
  $manifest = Get-Content (Join-Path $env:EKH_TEST_PROJECT '.run/services.json') -Raw | ConvertFrom-Json
  if (@($manifest.services).Count -ne 3) { throw 'Manifest missing services' }
  if (($manifest | ConvertTo-Json -Depth 5) -match 'OPENAI|API_KEY|secret-marker') { throw 'Secret-like data reached manifest' }
  if ($env:EKH_TEST_MODE -eq 'duplicate') { try { . (Join-Path $env:EKH_TEST_PROJECT 'scripts/start-all.ps1'); throw 'Duplicate accepted' } catch { if ($_.Exception.Message -notmatch 'already running') { throw } } }
  if ($env:EKH_TEST_MODE -eq 'stop_mismatch') { $script:processes[[int]$manifest.services[0].pid].CreationDate = 'reused-pid-time' }
  . (Join-Path $env:EKH_TEST_PROJECT 'scripts/stop-all.ps1')
  if (Test-Path (Join-Path $env:EKH_TEST_PROJECT '.run/services.json')) { throw 'Manifest retained after stop' }
  if ($script:stopped.Count -ne 6 -or -not $script:processes.ContainsKey(900)) { throw 'Owned process tree isolation failed' }
  Write-Output 'PASSED'
} catch {
  if ($env:EKH_TEST_MODE -eq 'mismatch' -and $_.Exception.Message -match 'does not match current process identity') { if ($script:stopped.Count -ne 0) { throw 'Unrelated process stopped' }; Write-Output 'PASSED' }
  elseif ($env:EKH_TEST_MODE -eq 'stop_mismatch' -and $_.Exception.Message -match 'different process identity') { if ($script:stopped.Count -ne 0) { throw 'Shutdown was not atomic' }; Write-Output 'PASSED' }
  else { throw }
}
''', encoding="utf-8")
    env = dict(os.environ); env.update({"EKH_TEST_PROJECT": str(project), "EKH_TEST_MODE": mode})
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    assert result.returncode == 0, result.stderr
    assert "PASSED" in result.stdout
    return result.stdout + result.stderr, project


@pytest.mark.parametrize("mode", ["normal", "duplicate", "stale", "mismatch", "stop_mismatch"])
def test_launcher_ownership_scenarios(tmp_path, mode):
    output, _ = exercise(tmp_path, mode=mode)
    assert "secret-marker" not in output


def test_local_settings_are_never_persisted_or_logged(tmp_path):
    marker = "secret-marker-" + uuid4().hex
    output, project = exercise(tmp_path, env_text=f"EKH_EXTERNAL_AI_ENABLED=true\nEKH_OPENAI_MODEL=test-model\nOPENAI_API_KEY={marker}\n")
    assert marker not in output
    assert not (project / ".run" / "services.json").exists()


def test_run_state_is_gitignored():
    assert ".run/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
