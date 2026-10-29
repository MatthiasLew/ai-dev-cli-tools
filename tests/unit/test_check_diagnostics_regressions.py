import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from threading import Event

import pytest

from ai_dev_tools.parsers.logs import parse_tool_output
from ai_dev_tools.runners.check import run_check
from ai_dev_tools.utils.subprocess import _resolve_executable, run_command


@pytest.mark.parametrize(
    "output",
    [
        "Errors: 0",
        "Documentation errors: 0. External URLs and heading anchors not checked.",
        "ERRORS: 0\nEverything checked",
    ],
)
def test_zero_error_summary_has_no_failure(output: str) -> None:
    result = parse_tool_output("python check.py", output)
    assert result["status"] == "success"
    assert result["first_failure"] is None
    assert result["first_failure_reason"] is None


@pytest.mark.parametrize(
    "output",
    [
        "Errors: 1",
        "Errors: 01",
        "Errors: 0.5",
        "Errors: 0; validation failed",
        "Errors: 0\nException: broken",
        "Errors: 0x10",
        "Errors: 0unknown",
    ],
)
@pytest.mark.parametrize("exit_code", [0, 1])
def test_real_diagnostics_are_retained(output: str, exit_code: int) -> None:
    result = parse_tool_output("python check.py", output, exit_code)
    assert result["first_failure"] is not None
    assert result["first_failure_reason"] is not None


def test_configured_check_zero_errors(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[commands]\nlint = 'python check.py'\n", encoding="utf-8"
    )
    (tmp_path / "check.py").write_text("print('Errors: 0')\n", encoding="utf-8")
    report = run_check(tmp_path, "full", use_cache=False)
    assert report.status == "success"
    result = report.summary["results"][0]
    assert result["exit_code"] == 0
    assert result["first_failure"] is None
    assert result["first_failure_reason"] is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows executable search order")
@pytest.mark.parametrize("cancellable", [False, True])
def test_windows_executes_path_selected_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancellable: bool
) -> None:
    environment = tmp_path / "selected environment"
    venv.EnvBuilder(with_pip=False).create(environment)
    monkeypatch.setenv("PATH", str(environment / "Scripts") + os.pathsep + os.environ["PATH"])
    resolved = shutil.which("python")
    assert resolved is not None
    probe = ["-c", "import sys; print(sys.executable)"]
    expected = subprocess.check_output([resolved, *probe], text=True).strip()
    _resolve_executable.cache_clear()
    try:
        result = run_command(
            ["python", *probe], tmp_path, cancel_event=Event() if cancellable else None
        )
        assert result.exit_code == 0
        assert result.stdout.strip() == expected
        assert result.command == ["python", *probe]
    finally:
        _resolve_executable.cache_clear()
