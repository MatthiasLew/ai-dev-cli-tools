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
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
