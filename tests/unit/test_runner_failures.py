from pathlib import Path

import pytest

import ai_dev_tools.runners.check as check
from ai_dev_tools.utils.subprocess import CommandResult

RUNNER_COMMANDS = [
    "pytest",
    "npm test",
    "mvn test",
    "gradle test",
    "cargo test",
    "composer test",
]
OUTCOMES = {
    "failure": (1, "error: compilation failed", False),
    "timeout": (124, "partial output before timeout", True),
    "missing": (127, "executable not found", False),
    "malformed": (1, "<<<unstructured tool output>>>", False),
    "partial": (1, "FAILED", False),
}


@pytest.mark.parametrize("command_text", RUNNER_COMMANDS)
@pytest.mark.parametrize("outcome", list(OUTCOMES))
def test_runner_families_report_failure_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command_text: str,
    outcome: str,
) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        f"[commands]\ntest={command_text!r}\n", encoding="utf-8"
    )
    exit_code, output, timed_out = OUTCOMES[outcome]
    monkeypatch.setattr(
        check,
        "run_command",
        lambda command, cwd: CommandResult(
            command, exit_code, output, "", 0.01, timed_out=timed_out
        ),
    )

    report = check.run_check(tmp_path, mode="full", use_cache=False)

    result = report.summary["results"][0]
    assert report.status == "failed"
    assert result["exit_code"] == exit_code
    assert result["timed_out"] is timed_out
    assert result["failure_signature"].startswith("failure:")
    assert Path(result["full_log"]).exists()
