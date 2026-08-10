from __future__ import annotations

from pathlib import Path

import pytest

import ai_dev_tools.runners.bootstrap as boot
from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.runners.bootstrap import (
    BootstrapOptions,
    build_bootstrap_plan,
    run_bootstrap,
)
from ai_dev_tools.runners.bootstrap_models import BootstrapPlan, BootstrapStep
from ai_dev_tools.runners.environment_state import (
    capture_environment_state,
    inspect_environment_state,
    run_environment_explain,
)
from ai_dev_tools.utils.subprocess import CommandResult


def _plan(command: list[str]) -> BootstrapPlan:
    return BootstrapPlan(
        "python",
        "pip",
        [BootstrapStep("install", command, "test", "test")],
        [],
        [],
    )


def _doctor(root: Path) -> Report:
    report = Report(command="doctor", project_root=root)
    report.summary = {
        "tools": {
            "npm": {
                "status": "ok",
                "version": "10.0",
                "path": "npm",
            }
        }
    }
    return report.finish()


def test_environment_state_revalidates_inputs_plan_and_tools(tmp_path: Path) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text("[project]" + chr(10) + "name='demo'" + chr(10), encoding="utf-8")
    tool = tmp_path / "local-tool"
    tool.write_text("", encoding="utf-8")
    plan = _plan([str(tool)])

    path = capture_environment_state(tmp_path, plan, {"tools": {}})
    reusable = inspect_environment_state(tmp_path, plan)

    assert path.exists()
    assert reusable["reusable"] is True

    config.write_text("[project]" + chr(10) + "name='changed'" + chr(10), encoding="utf-8")
    changed = inspect_environment_state(tmp_path, plan)
    assert changed["reusable"] is False
    assert "INPUT_FINGERPRINT_CHANGED" in changed["reason_codes"]

    config.write_text("[project]" + chr(10) + "name='demo'" + chr(10), encoding="utf-8")
    tool.unlink()
    missing = inspect_environment_state(tmp_path, plan)
    assert any(str(code).startswith("TOOL_MISSING") for code in missing["reason_codes"])


def test_bootstrap_if_needed_reuses_successful_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(boot, "run_doctor", _doctor)
    monkeypatch.setattr(
        boot,
        "run_command",
        lambda command, cwd, timeout_seconds=300: CommandResult(
            command, 0, "ok", "", 0.01
        ),
    )

    first = run_bootstrap(tmp_path, BootstrapOptions())
    assert first.status == "success"
    assert first.summary["environment_state"]["captured"] is True

    monkeypatch.setattr(
        boot,
        "run_doctor",
        lambda root: (_ for _ in ()).throw(AssertionError("doctor should be skipped")),
    )
    monkeypatch.setattr(
        boot,
        "scan_project",
        lambda root: (_ for _ in ()).throw(AssertionError("scan should be skipped")),
    )
    second = run_bootstrap(tmp_path, BootstrapOptions(if_needed=True))

    assert second.status == "success"
    assert second.summary["skipped"] is True
    assert second.summary["reason_code"] == "WARM_ENVIRONMENT_REUSED"
    assert second.summary["executed_commands"] == 0


def test_environment_explain_reports_stale_and_reusable_state(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]" + chr(10) + "name='demo'" + chr(10),
        encoding="utf-8",
    )
    stale = run_environment_explain(tmp_path)
    assert stale.status == "partial"
    assert stale.summary["reusable"] is False

    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    capture_environment_state(tmp_path, plan, {"tools": {}})
    reusable = run_environment_explain(tmp_path)
    assert reusable.status == "success"
    assert reusable.summary["reusable"] is True