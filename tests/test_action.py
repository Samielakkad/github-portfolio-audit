import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _working_bash() -> str:
    candidates = []
    git = shutil.which("git")
    if git:
        candidates.append(str(Path(git).resolve().parents[1] / "bin" / "bash.exe"))
    bash = shutil.which("bash")
    if bash:
        candidates.append(bash)

    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and b"bash" in result.stdout.lower():
            return candidate
    pytest.skip("a working Bash executable is unavailable")


def _write_auditor_stub(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
output=""
while (($#)); do
  if [[ "$1" == "--output" ]]; then
    output="$2"
    shift 2
  else
    shift
  fi
done
if [[ "${STUB_WRITE_REPORT:-1}" == "1" ]]; then
  printf '# fresh report\\n' > "$output"
fi
exit "${STUB_STATUS:-0}"
""",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(0o755)


def _run_action(tmp_path: Path, *, write_report: bool) -> subprocess.CompletedProcess:
    bash = _working_bash()
    workspace = tmp_path / "workspace"
    runner_temp = workspace / "runner-temp"
    stub_dir = tmp_path / "bin"
    workspace.mkdir()
    runner_temp.mkdir()
    stub_dir.mkdir()
    (workspace / "portfolio-audit.md").write_text("stale caller content\n")
    _write_auditor_stub(stub_dir / "github-portfolio-audit")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{stub_dir}{os.pathsep}{env.get('PATH', '')}",
            "RUNNER_TEMP": "runner-temp",
            "GITHUB_STEP_SUMMARY": "summary.md",
            "GITHUB_REPOSITORY_OWNER": "example",
            "INPUT_OWNER": "",
            "INPUT_REPOSITORY": "",
            "INPUT_MIN_SCORE": "70",
            "STUB_STATUS": "1",
            "STUB_WRITE_REPORT": "1" if write_report else "0",
        }
    )
    result = subprocess.run(
        [bash, str(ROOT / "scripts" / "run-action.sh")],
        cwd=workspace,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    result.workspace = workspace
    result.runner_temp = runner_temp
    return result


def test_action_uses_private_temp_report_and_cleans_it(tmp_path):
    result = _run_action(tmp_path, write_report=True)

    assert result.returncode == 1, result.stderr
    assert (result.workspace / "summary.md").read_text() == "# fresh report\n"
    assert (
        result.workspace / "portfolio-audit.md"
    ).read_text() == "stale caller content\n"
    assert list(result.runner_temp.iterdir()) == []


def test_action_does_not_publish_stale_workspace_file_after_failure(tmp_path):
    result = _run_action(tmp_path, write_report=False)

    assert result.returncode == 1, result.stderr
    assert (result.workspace / "summary.md").read_text() == (
        "Portfolio audit failed before producing a report.\n"
    )
    assert "stale caller content" not in (result.workspace / "summary.md").read_text()
    assert list(result.runner_temp.iterdir()) == []
