from pathlib import Path

from ai_dev_tools.cli import main


def test_cli_doctor_json(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.detectors import environment

    monkeypatch.setattr(environment, "TOOLS", tuple())
    assert main(["--project", str(tmp_path), "--json", "doctor"]) == 0
    assert '"command": "doctor"' in capsys.readouterr().out


def test_cli_git_non_repo(tmp_path: Path) -> None:
    assert main(["--project", str(tmp_path), "git", "status"]) == 0


def test_cli_quiet_scan(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    assert main(["--project", str(tmp_path), "--quiet", "scan"]) == 0
    assert "project-scan" in capsys.readouterr().out
