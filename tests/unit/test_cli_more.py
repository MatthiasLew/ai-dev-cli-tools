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


def test_placeholder_returns_not_implemented(tmp_path: Path) -> None:
    assert main(["--project", str(tmp_path), "--json", "run"]) == 1


def test_map_accepts_limits(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    assert main(["--project", str(tmp_path), "map", "--max-files", "1", "--max-depth", "2"]) == 0


def test_cli_capabilities_json(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--project", str(tmp_path), "--json", "capabilities"]) == 0
    output = capsys.readouterr().out
    assert "implemented" in output
    assert "context build" in output


def test_cli_check_explain_does_not_run(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[commands]\ntest='missing-command'\n", encoding="utf-8"
    )
    assert main(["--project", str(tmp_path), "--json", "check", "--mode", "full", "--explain"]) == 0
    output = capsys.readouterr().out
    assert "explain_only" in output
    assert "missing-command" in output


def test_cli_logs_summarize_file_with_tool(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    log = tmp_path / "pytest.log"
    log.write_text("FAILED tests/test_x.py::test_x - boom\n1 failed\n", encoding="utf-8")
    assert (
        main(
            [
                "--project",
                str(tmp_path),
                "--json",
                "logs",
                "summarize",
                str(log),
                "--tool",
                "pytest",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "pytest" in output
    assert "detected_tool" in output


def test_cli_context_build_json(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    assert (
        main(
            [
                "--project",
                str(tmp_path),
                "--json",
                "context",
                "build",
                "--no-git",
                "--include",
                "README.md",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"command": "context build"' in output
    assert (tmp_path / ".ai" / "context" / "context-latest.json").exists()
