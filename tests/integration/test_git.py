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
    assert "DIVERGED" in _states(porcelain, "origin/main", False)
