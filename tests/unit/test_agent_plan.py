from pathlib import Path

from ai_dev_tools.cli import main
from ai_dev_tools.models.report import Report
from ai_dev_tools.runners.plan import run_agent_plan


def test_agent_plan_is_preview_only_and_actionable(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import plan

    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        plan,
        "inspect_git",
        lambda *args, **kwargs: _report(
            tmp_path,
            {
                "changed_files": ["src/service.py"],
                "changed_symbols": [
                    {"path": "src/service.py", "name": "run", "risk": "medium"}
                ],
            },
        ),
    )
    monkeypatch.setattr(
        plan,
        "run_check",
        lambda *args, **kwargs: _report(
            tmp_path,
            {
                "selected_checks": [
                    {"name": "pytest", "command": ["python", "-m", "pytest"]}
                ],
                "changed_analysis": {"confidence": "high", "reason_paths": []},
                "schedule": {"groups": []},
            },
        ),
    )

    report = run_agent_plan(tmp_path, "change service behavior")

    assert report.status == "success"
    assert report.summary["constraints"]["commands_executed"] is False
    assert report.summary["decision"]["confidence"] == "high"
    assert report.summary["next_actions"][-1]["kind"] == "validate"
    assert report.summary["evidence"][1]["symbol"] == "run"
    assert (tmp_path / ".ai" / "reports" / "agent-plan.json").exists()


def test_agent_plan_cli_requires_no_execution(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--project", str(tmp_path), "--json", "plan", "--task", "inspect repo"]) == 0
    assert '"agent_plan_version": "1"' in capsys.readouterr().out


def _report(root: Path, summary: dict[str, object]) -> Report:
    report = Report(command="fixture", project_root=root)
    report.summary = summary
    return report
