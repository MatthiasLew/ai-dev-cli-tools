from __future__ import annotations

import shutil
import sys
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.detectors.workspaces import detect_workspaces, owning_workspace
from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.runners.check import build_validation_plan, collect_changed_files
from ai_dev_tools.utils.subprocess import run_command

FIXTURE = Path("tests/fixtures/monorepo-mixed")


def test_mixed_monorepo_fixture_routes_workspaces_in_unicode_spaced_path(tmp_path: Path) -> None:
    project = tmp_path / "mixed project \u017c\u00f3\u0142\u0107"
    shutil.copytree(FIXTURE, project)

    workspaces = detect_workspaces(project)
    roots = {workspace.root for workspace in workspaces}
    assert {"", "packages/api", "packages/web", "services/worker"} <= roots
    api_owner = owning_workspace(workspaces, "packages/api/src/service.py")
    web_owner = owning_workspace(workspaces, "packages\\web\\test.js")
    assert api_owner is not None and api_owner.root == "packages/api"
    assert web_owner is not None and web_owner.root == "packages/web"

    plan = build_validation_plan(load_settings(project))
    routed = {(task.workspace, task.name) for task in plan}
    assert ("packages/api", "pytest") in routed
    assert ("packages/web", "npm test") in routed
    assert ("services/worker", "cargo test") in routed


def test_git_handles_spaces_unicode_rename_and_delete(tmp_path: Path) -> None:
    assert run_command(["git", "init", "-b", "main"], tmp_path, 30).exit_code == 0
    run_command(["git", "config", "user.email", "tests@example.invalid"], tmp_path, 30)
    run_command(["git", "config", "user.name", "Test Runner"], tmp_path, 30)
    old = tmp_path / "old name \u017c\u00f3\u0142\u0107.txt"
    deleted = tmp_path / "delete me.txt"
    old.write_text("old", encoding="utf-8")
    deleted.write_text("delete", encoding="utf-8")
    run_command(["git", "add", "--", old.name, deleted.name], tmp_path, 30)
    assert run_command(["git", "commit", "-m", "base"], tmp_path, 30).exit_code == 0

    new = tmp_path / "new name \u65e5\u672c.txt"
    old.rename(new)
    deleted.unlink()
    untracked = tmp_path / "untracked space \u0142.txt"
    untracked.write_text("new", encoding="utf-8")

    report = inspect_git(tmp_path, detailed=True)
    changed = set(report.summary["changed_files"])
    assert {old.name, new.name, deleted.name, untracked.name} <= changed
    collected = set(collect_changed_files(tmp_path))
    assert {old.name, new.name, deleted.name, untracked.name} <= collected


def test_subprocess_replaces_non_utf8_output(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'prefix\\xffsuffix')"],
        tmp_path,
        30,
    )
    assert result.exit_code == 0
    assert result.stdout.startswith("prefix")
    assert "suffix" in result.stdout
    assert "\ufffd" in result.stdout
