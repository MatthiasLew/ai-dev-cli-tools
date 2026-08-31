from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.cli import main


def test_integrations_and_dashboard_status_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(
        ["--project", str(tmp_path), "--json", "integrations", "install", "generic"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["clients"] == ["generic"]

    code = main(["--project", str(tmp_path), "--json", "dashboard", "status"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["project_root"] == str(tmp_path.resolve())


def test_daemon_and_benchmark_gate_cli_paths(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["--project", str(tmp_path), "--json", "index", "daemon", "status"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "partial"

    missing = tmp_path / "missing.json"
    code = main(
        [
            "--project",
            str(tmp_path),
            "--json",
            "benchmark",
            "gate",
            str(missing),
            str(missing),
            "--min-token-reduction",
            "15",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_adaptive_context_cli_reports_resolved_budget(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")

    code = main(
        [
            "--project",
            str(tmp_path),
            "--json",
            "context",
            "build",
            "--task",
            "document API",
            "--include",
            "README.md",
            "--no-git",
            "--adaptive",
            "--explain",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["adaptive_context"]["enabled"] is True
    assert payload["summary"]["adaptive_context"]["intent"] == "docs"
