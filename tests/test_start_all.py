"""Exercise Windows launcher using mocked child launches; never start services or use real keys."""

import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell launcher")
ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "EKH_DATABASE_PATH",
    "EKH_STORAGE_ROOT",
    "EKH_MAX_UPLOAD_MB",
    "EKH_REVIEWER_FILE",
    "EKH_EXTERNAL_AI_ENABLED",
    "EKH_OPENAI_MODEL",
    "OPENAI_API_KEY",
    "EKH_AI_DENIED_REVISIONS",
)


def launch(tmp_path, content, *, inherited=None, expected=None, invalid=False):
    project = tmp_path / "workspace with spaces"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "start-all.ps1",
        "local-environment.ps1",
        "start-backend.ps1",
        "start-frontend.ps1",
        "start-worker.ps1",
    ):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    if content is not None:
        (project / ".env.local").write_text(content, encoding="utf-8-sig")
    env = dict(os.environ)
    for name in NAMES:
        env.pop(name, None)
    env.update(inherited or {})
    expected = expected or {}
    env.update(
        {
            "EKH_TEST_EXPECTED_KEY": expected.get("OPENAI_API_KEY", ""),
            "EKH_TEST_EXPECTED_MODEL": expected.get("EKH_OPENAI_MODEL", ""),
            "EKH_TEST_EXPECTED_ENABLED": expected.get("EKH_EXTERNAL_AI_ENABLED", ""),
            "EKH_TEST_INVALID": str(invalid),
            "EKH_TEST_PROJECT": str(project),
        }
    )
    harness = tmp_path / "exercise.ps1"
    harness.write_text(
        r"""$ErrorActionPreference = 'Stop'
$script:launchCount = 0
function Start-Process {
    param($FilePath, $WorkingDirectory, $WindowStyle, $ArgumentList)
    $script:launchCount++
    if ($env:EKH_TEST_INVALID -eq 'True') { throw 'Unexpected launch for invalid configuration' }
    if ($env:OPENAI_API_KEY -ne $env:EKH_TEST_EXPECTED_KEY -or
        $env:EKH_OPENAI_MODEL -ne $env:EKH_TEST_EXPECTED_MODEL -or
        $env:EKH_EXTERNAL_AI_ENABLED -ne $env:EKH_TEST_EXPECTED_ENABLED) {
        throw 'Child environment mismatch (values withheld)'
    }
    if ($WorkingDirectory -ne $env:EKH_TEST_PROJECT -or
        (Get-Location).Path -ne $env:EKH_TEST_PROJECT -or $WindowStyle -ne 'Normal') {
        throw 'Launch directory/window mismatch'
    }
    if ($ArgumentList.Count -ne 5 -or $ArgumentList[0] -ne '-NoProfile' -or
        $ArgumentList[1] -ne '-ExecutionPolicy' -or $ArgumentList[2] -ne 'Bypass' -or
        $ArgumentList[3] -ne '-File') { throw 'Unexpected launch arguments' }
    $names = @('start-backend.ps1', 'start-frontend.ps1', 'start-worker.ps1')
    $expectedPath = Join-Path (Join-Path $env:EKH_TEST_PROJECT 'scripts') $names[$script:launchCount - 1]
    if ($ArgumentList[4] -cne ('"' + $expectedPath + '"')) { throw 'Wrong child script path' }
    if (-not (Test-Path -LiteralPath $FilePath)) { throw 'Shell executable missing' }
}
try {
    . (Join-Path $env:EKH_TEST_PROJECT 'scripts/start-all.ps1')
    if ($env:EKH_TEST_INVALID -eq 'True') { throw 'Invalid configuration accepted' }
    if ($script:launchCount -ne 3) { throw 'Expected three launches' }
    Write-Output 'LAUNCH_TEST_PASSED'
} catch {
    if ($env:EKH_TEST_INVALID -eq 'True' -and $script:launchCount -eq 0 -and
        $_.Exception.Message -match '^(Invalid|Unsupported|Duplicate|Unclosed) .env.local') {
        if ($env:OPENAI_API_KEY -ne $env:EKH_TEST_EXPECTED_KEY) { throw 'Partial settings applied' }
        Write-Output $_.Exception.Message
        Write-Output 'INVALID_TEST_PASSED'
    } else { throw }
}
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert ("INVALID_TEST_PASSED" if invalid else "LAUNCH_TEST_PASSED") in result.stdout
    return result.stdout + result.stderr


def test_file_settings_override_inherited_and_are_literal_not_logged(tmp_path):
    # Random runtime-only marker, not an API credential or a committed secret fixture.
    marker = uuid4().hex + "=$env:PATH#literal"
    output = launch(
        tmp_path,
        "# Local settings\nEKH_EXTERNAL_AI_ENABLED=true\nEKH_OPENAI_MODEL=test-model\n"
        + 'OPENAI_API_KEY="'
        + marker
        + '"\n',
        inherited={"OPENAI_API_KEY": uuid4().hex},
        expected={
            "OPENAI_API_KEY": marker,
            "EKH_OPENAI_MODEL": "test-model",
            "EKH_EXTERNAL_AI_ENABLED": "true",
        },
    )
    assert marker not in output and "OPENAI_API_KEY" not in output and "test-model" not in output


def test_absent_file_runs_offline_without_prompting(tmp_path):
    output = launch(tmp_path, None)
    assert ".env.local is absent" in output and "For Real AI" in output


def test_absent_file_preserves_existing_shell_configuration(tmp_path):
    values = {
        "OPENAI_API_KEY": uuid4().hex,
        "EKH_OPENAI_MODEL": "test-model",
        "EKH_EXTERNAL_AI_ENABLED": "true",
    }
    output = launch(tmp_path, None, inherited=values, expected=values)
    assert values["OPENAI_API_KEY"] not in output


def test_empty_example_values_clear_inherited_key_and_model(tmp_path):
    launch(
        tmp_path,
        (ROOT / ".env.example").read_text(encoding="utf-8"),
        inherited={"OPENAI_API_KEY": uuid4().hex, "EKH_OPENAI_MODEL": "old-model"},
        expected={"EKH_EXTERNAL_AI_ENABLED": "false"},
    )


@pytest.mark.parametrize(
    "bad_line", ["invalid", "PATH=bad", "OPENAI_API_KEY=again", 'EKH_OPENAI_MODEL="unclosed']
)
def test_invalid_config_never_launches_or_leaks_or_partially_applies(tmp_path, bad_line):
    marker = uuid4().hex
    inherited = uuid4().hex
    output = launch(
        tmp_path,
        "OPENAI_API_KEY=" + marker + "\n" + bad_line + "\n",
        inherited={"OPENAI_API_KEY": inherited},
        expected={"OPENAI_API_KEY": inherited},
        invalid=True,
    )
    assert marker not in output and inherited not in output and bad_line not in output


def test_example_contains_no_key_or_enabled_external_default():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#")
    )
    assert values["OPENAI_API_KEY"] == "" and values["EKH_OPENAI_MODEL"] == ""
    assert values["EKH_EXTERNAL_AI_ENABLED"] == "false"
