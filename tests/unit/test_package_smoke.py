from __future__ import annotations

import json
import os
from pathlib import Path

from ai_dev_tools.cli import main
from scripts.test_installed_package import entrypoint_path


def test_cli_accepts_json_after_subcommand(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["capabilities", "--json", "--project", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert '"command": "capabilities"' in output


def test_cli_accepts_project_after_subcommand_global_flag(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    assert main(["scan", "--json", "--project", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["project_root"] == str(tmp_path.resolve())


def test_installed_package_entrypoint_path_windows(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(os, "name", "nt")
    assert entrypoint_path(tmp_path) == tmp_path / "Scripts" / "ai-dev.exe"


def test_installed_package_entrypoint_path_posix(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(os, "name", "posix")
    assert entrypoint_path(tmp_path) == tmp_path / "bin" / "ai-dev"
