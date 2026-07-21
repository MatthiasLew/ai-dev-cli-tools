import shutil
from pathlib import Path

from ai_dev_tools.detectors import environment
from ai_dev_tools.utils.subprocess import CommandResult


def test_doctor_reports_missing_and_available(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shutil, "which", lambda exe: "C:/bin/tool" if exe == "git" else None)
    monkeypatch.setattr(
        environment,
        "run_command",
        lambda command, project_root, timeout_seconds=20: CommandResult(
            command, 0, "git version 2.0\n", "", 0.01
        ),
    )
    monkeypatch.setattr(
        environment,
        "TOOLS",
        (("git", "git", ["git", "--version"]), ("node", "node", ["node", "--version"])),
    )
    report = environment.run_doctor(tmp_path)
    assert report.summary["tools"]["git"]["status"] == "ok"
    assert report.summary["tools"]["node"]["status"] == "missing"
    assert (tmp_path / ".ai" / "reports" / "doctor.json").exists()


def test_doctor_marks_version_command_errors(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shutil, "which", lambda exe: "C:/bin/tool")
    monkeypatch.setattr(
        environment,
        "run_command",
        lambda command, project_root, timeout_seconds=20: CommandResult(
            command, 1, "", "tool exploded", 0.01
        ),
    )
    monkeypatch.setattr(environment, "TOOLS", (("tool", "tool", ["tool", "--version"]),))
    report = environment.run_doctor(tmp_path)
    assert report.status == "warning"
    assert report.summary["tools"]["tool"]["status"] == "error"
    assert report.summary["errors_optional"] == ["tool"]
