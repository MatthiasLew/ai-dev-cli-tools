from pathlib import Path

from ai_dev_tools.models.report import Artifact, Report
from ai_dev_tools.runners import finish


def test_finish_ready(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    git_report = Report(command="git inspect", project_root=tmp_path).finish()
    git_report.summary = {
        "changed_files": ["src/app.py", "tests/test_app.py", "README.md"],
        "states": ["DIRTY"],
        "conflicted_files": [],
    }
    git_report.artifacts.append(Artifact("git.json", "json", "git"))
    check_report = Report(command="check", project_root=tmp_path).finish()
    check_report.artifacts.append(Artifact("check.json", "json", "check"))
    monkeypatch.setattr(finish, "inspect_git", lambda root, detailed: git_report)
    monkeypatch.setattr(finish, "run_check", lambda root, mode: check_report)
    monkeypatch.setattr(finish, "scan_paths_for_secrets", lambda root, paths: [])
    report = finish.run_finish(tmp_path)
    assert report.summary["ready_to_commit"] is True
    assert report.summary["changed"]["production_files"] == 1


def test_finish_blocks_no_changes(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    git_report = Report(command="git inspect", project_root=tmp_path).finish()
    git_report.summary = {"changed_files": [], "states": ["UP_TO_DATE"], "conflicted_files": []}
    check_report = Report(command="check", project_root=tmp_path).finish()
    monkeypatch.setattr(finish, "inspect_git", lambda root, detailed: git_report)
    monkeypatch.setattr(finish, "run_check", lambda root, mode: check_report)
    monkeypatch.setattr(finish, "scan_paths_for_secrets", lambda root, paths: [])
    report = finish.run_finish(tmp_path)
    assert report.status == "failed"
    assert report.summary["blocking_reasons"] == ["no_changes"]
    assert report.summary["blocking_reason_codes"] == ["NO_CHANGES"]


def test_finish_blocks_conflicts_and_failed_checks(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    git_report = Report(command="git inspect", project_root=tmp_path).finish()
    git_report.summary = {
        "changed_files": ["src/app.py"],
        "states": ["CONFLICT", "DIRTY"],
        "conflicted_files": ["src/app.py"],
    }
    check_report = Report(command="check", project_root=tmp_path, status="failed").finish()
    check_report.summary = {"checks_failed": 2}
    monkeypatch.setattr(finish, "inspect_git", lambda root, detailed: git_report)
    monkeypatch.setattr(finish, "run_check", lambda root, mode: check_report)
    monkeypatch.setattr(finish, "scan_paths_for_secrets", lambda root, paths: [])
    report = finish.run_finish(tmp_path)
    assert "repository has merge conflicts" in report.summary["blocking_reasons"]
    assert "2 check(s) failed" in report.summary["blocking_reasons"]
