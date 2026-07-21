from pathlib import Path

from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.utils.subprocess import run_command


def test_git_inspect_dirty_repo(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    report = inspect_git(tmp_path, detailed=True)
    assert "DIRTY" in report.summary["states"]
    assert "file.txt" in report.summary["changed_files"]


def test_git_state_parses_ahead_behind_counts() -> None:
    from ai_dev_tools.git.inspect import _ahead_behind_counts, _states

    porcelain = "## main...origin/main [ahead 2, behind 1]\n M file.txt"
    assert _ahead_behind_counts(porcelain) == (2, 1)
    assert "DIVERGED" in _states(porcelain, "origin/main", False, True, False)


def test_git_inspect_staged_untracked_secret_and_path_with_space(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    spaced = tmp_path / "file with space.txt"
    spaced.write_text("hello", encoding="utf-8")
    run_command(["git", "add", "file with space.txt"], tmp_path, 30)
    secret = tmp_path / "secret.txt"
    fake_key = "sk-" + "1234567890abcdef1234567890"
    secret.write_text("OPENAI_API_KEY=" + fake_key, encoding="utf-8")
    report = inspect_git(tmp_path, detailed=True)
    assert "file with space.txt" in report.summary["staged_files"]
    assert "secret.txt" in report.summary["untracked_files"]
    assert report.summary["secret_findings"]


def test_name_status_parses_rename(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.git import inspect as git_inspect
    from ai_dev_tools.git.inspect import _entry_paths, _name_status
    from ai_dev_tools.utils.subprocess import CommandResult

    def fake_run(command: list[str], root: Path, timeout_seconds: int = 300) -> CommandResult:
        return CommandResult(command, 0, "R100\0old name.py\0new name.py\0", "", 0.01)

    monkeypatch.setattr(git_inspect, "run_command", fake_run)
    entries = _name_status(["git", "diff", "--name-status", "-z"], Path.cwd())
    assert entries == [{"status": "R100", "path": "new name.py", "old_path": "old name.py"}]
    assert _entry_paths(entries) == ["new name.py"]
