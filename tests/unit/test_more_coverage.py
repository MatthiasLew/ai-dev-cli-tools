from pathlib import Path

from ai_dev_tools.parsers.logs import summarize_latest_log
from ai_dev_tools.runners.check import run_check
from ai_dev_tools.utils.subprocess import run_command, split_command


def test_summarize_latest_log_no_logs_and_with_log(tmp_path: Path) -> None:
    report = summarize_latest_log(tmp_path)
    assert report.status == "warning"
    assert (tmp_path / ".ai" / "reports" / "logs-summary-latest.json").exists()
    logs = tmp_path / ".ai" / "logs"
    logs.mkdir(parents=True)
    (logs / "x.log").write_text("Error once\n", encoding="utf-8")
    report = summarize_latest_log(tmp_path)
    assert report.summary["first_failure_reason"] == "Error once"
    assert (tmp_path / ".ai" / "reports" / "logs-summary-latest.md").exists()


def test_check_without_detected_commands(tmp_path: Path) -> None:
    report = run_check(tmp_path)
    assert report.status == "warning"
    assert "No configured checks" in str(report.summary["message"])


def test_subprocess_helpers(tmp_path: Path) -> None:
    assert split_command("python -m pytest") == ["python", "-m", "pytest"]
    result = run_command(["definitely-not-a-real-ai-dev-command"], tmp_path, 1)
    assert result.exit_code == 127
    assert result.combined_output


def test_windows_batch_command_wrapper() -> None:
    from ai_dev_tools.utils.subprocess import _windows_batch_command

    wrapped = _windows_batch_command(["npm.CMD", "--version"])
    if wrapped[0].lower().endswith("cmd.exe"):
        assert wrapped[1:3] == ["/d", "/c"]
    else:
        assert wrapped == ["npm.CMD", "--version"]
