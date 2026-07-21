from pathlib import Path

from ai_dev_tools.cli import main


def test_cli_scan_json_with_path_containing_space(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "project with space"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='space-demo'\n", encoding="utf-8")
    exit_code = main(["--project", str(project), "--json", "scan"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"command": "scan"' in captured.out
    assert (project / ".ai" / "reports" / "project-scan.md").exists()


def test_cli_reserved_command_warns(tmp_path: Path) -> None:
    assert main(["--project", str(tmp_path), "context", "build"]) == 0
