import io
import json
import sys
from pathlib import Path

from ai_dev_tools.cli import _print_text, main
from ai_dev_tools.models.report import Issue, Report


def test_cli_doctor_json(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.detectors import environment

    monkeypatch.setattr(environment, "TOOLS", tuple())
    assert main(["--project", str(tmp_path), "--json", "doctor"]) == 0
    assert '"command": "doctor"' in capsys.readouterr().out


def test_text_report_replaces_characters_unsupported_by_console_encoding(tmp_path: Path) -> None:
    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1250", errors="strict")
    original = sys.stdout
    report = Report(command="check", project_root=tmp_path)
    report.issues.append(Issue(severity="error", message="invalid: \ufffd"))
    try:
        sys.stdout = console
        _print_text(report)
        console.flush()
    finally:
        sys.stdout = original

    rendered = output.getvalue().decode("cp1250")
    assert "invalid: ?" in rendered


def test_cli_git_non_repo(tmp_path: Path) -> None:
    assert main(["--project", str(tmp_path), "git", "status"]) == 0


def test_cli_quiet_scan(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    assert main(["--project", str(tmp_path), "--quiet", "scan"]) == 0
    assert "project-scan" in capsys.readouterr().out


def test_run_blocks_without_safe_command(tmp_path: Path) -> None:
    assert main(["--project", str(tmp_path), "--json", "run"]) == 1


def test_map_accepts_limits(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    assert main(["--project", str(tmp_path), "map", "--max-files", "1", "--max-depth", "2"]) == 0


def test_cli_capabilities_json(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--project", str(tmp_path), "--json", "capabilities"]) == 0
    output = capsys.readouterr().out
    assert "implemented" in output
    assert "context build" in output
    assert "test flaky" in output
    assert "mcp serve" in output
    assert '"ci_status": "VERIFIED"' in output


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


def test_cli_mcp_serve_uses_stdio_without_extra_output(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request) + "\n"))

    assert main(["--project", str(tmp_path), "mcp", "serve"]) == 0

    output = capsys.readouterr().out
    response = json.loads(output)
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "ai-dev-cli-tools"
