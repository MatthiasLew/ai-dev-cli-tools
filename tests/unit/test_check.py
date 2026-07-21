from pathlib import Path

from ai_dev_tools.runners import check
from ai_dev_tools.utils.subprocess import CommandResult


def test_check_uses_configured_commands(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[commands]\nlint='python --version'\ntest='python --version'\n", encoding="utf-8"
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], root: Path) -> CommandResult:
        calls.append(command)
        return CommandResult(command, 0, "ok", "", 0.01)

    monkeypatch.setattr(check, "run_command", fake_run)
    report = check.run_check(tmp_path, "full")
    assert report.status == "success"
    assert calls == [["python", "--version"], ["python", "--version"]]
    assert (tmp_path / ".ai" / "logs").exists()


def test_check_reports_failure(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".ai-dev-tools.toml").write_text("[commands]\ntest='pytest'\n", encoding="utf-8")
    monkeypatch.setattr(
        check,
        "run_command",
        lambda command, root: CommandResult(command, 1, "FAILED test_x\n", "", 0.01),
    )
    report = check.run_check(tmp_path, "fast")
    assert report.status == "failed"
    assert report.summary["results"][0]["first_failure_reason"] == "FAILED test_x"


def test_changed_mode_reports_broad_fallback(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".ai-dev-tools.toml").write_text("[commands]\ntest='pytest'\n", encoding="utf-8")

    def fake_run(command: list[str], root: Path, timeout_seconds: int = 300) -> CommandResult:
        if command[:2] == ["git", "status"]:
            return CommandResult(command, 0, " M src/app.py\n?? tests/test_app.py\n", "", 0.01)
        return CommandResult(command, 0, "2 passed, 1 skipped in 0.1s", "", 0.01)

    monkeypatch.setattr(check, "run_command", fake_run)
    report = check.run_check(tmp_path, "changed")
    changed = report.summary["changed_analysis"]
    assert changed["strategy"] == "broad_fallback"
    assert changed["changed_files"] == ["src/app.py", "tests/test_app.py"]
    result = report.summary["results"][0]
    assert result["passed"] == 2
    assert result["skipped"] == 1
    assert result["tests_total"] == 3
