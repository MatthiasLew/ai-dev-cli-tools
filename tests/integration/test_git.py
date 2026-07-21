from pathlib import Path

from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.utils.subprocess import run_command


def test_git_inspect_dirty_repo(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    report = inspect_git(tmp_path, detailed=True)
    assert "DIRTY" in report.summary["states"]
    assert "file.txt" in report.summary["changed_files"]
