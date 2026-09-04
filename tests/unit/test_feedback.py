from __future__ import annotations

from pathlib import Path

import pytest

from ai_dev_tools.models.report import Artifact, Report
from ai_dev_tools.runners import feedback
from ai_dev_tools.runners.check_models import CheckTask
from ai_dev_tools.runners.feedback import (
    FeedbackOptions,
    _changed_content_fingerprint,
    run_feedback,
    run_session_status,
)
from ai_dev_tools.runners.focused import focused_rerun


def test_focused_rerun_uses_parser_file_without_running_it() -> None:
    task = CheckTask("pytest", "unit_tests", ["pytest"], "medium", "detected")

    command = focused_rerun(
        task,
        {"parser": "pytest", "project_frames": [{"file": "tests/test_auth.py", "line": 4}]},
    )

    assert command is not None
    assert command[-1] == "tests/test_auth.py"


def test_feedback_combines_changes_validation_context_and_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git_report = Report(command="git inspect", project_root=tmp_path)
    git_report.summary = {"changed_files": ["src/app.py"], "states": ["DIRTY"]}

    check_report = Report(command="check", project_root=tmp_path)
    check_report.summary = {
        "checks_total": 1,
        "checks_failed": 0,
        "results": [
            {
                "name": "pytest",
                "exit_code": 0,
                "failure_signature": None,
                "reuse": "resumed",
            }
        ],
        "execution": {"resumed": 1},
        "changed_analysis": {"confidence": "high"},
    }
    check_report.artifacts.append(Artifact("check.json", "json", "check"))

    context_report = Report(command="context build", project_root=tmp_path)
    context_report.summary = {
        "selected_files": [{"path": "src/app.py"}],
        "incremental": {"selected": 1, "reused": 2},
        "budget": {"used_chars": 120},
    }
    context_report.artifacts.append(Artifact("context.json", "json", "context"))

    monkeypatch.setattr(feedback, "inspect_git", lambda root, detailed: git_report)
    monkeypatch.setattr(feedback, "run_check", lambda *args, **kwargs: check_report)
    monkeypatch.setattr(feedback, "build_context", lambda *args, **kwargs: context_report)

    report = run_feedback(tmp_path, FeedbackOptions(task="fix auth"))

    assert report.status == "success"
    assert report.summary["agent_protocol_version"] == "1"
    assert report.summary["changes"]["files"] == ["src/app.py"]
    assert report.summary["validation"]["execution"]["resumed"] == 1
    assert report.summary["context"]["incremental"]["reused"] == 2
    assert report.summary["performance"]["stages_seconds"]
    assert report.summary["observations"]["current_retained_reasons"] == ["final_verification"]
    assert any(artifact.kind == "session" for artifact in report.artifacts)
    assert any(artifact.kind == "observations" for artifact in report.artifacts)

    state = report.summary["delta"]["state_fingerprint"]
    repeated = run_feedback(
        tmp_path,
        FeedbackOptions(task="fix auth", acknowledged_state=str(state)),
    )
    assert repeated.summary["delta"]["reused"] is True
    assert repeated.summary["validation"]["unchanged"] is True
    assert repeated.summary["context"]["unchanged"] is True
    assert repeated.summary["delta"]["chars_avoided"] > 0

    unacknowledged = run_feedback(tmp_path, FeedbackOptions(task="fix auth"))
    assert unacknowledged.summary["delta"]["reused"] is False
    assert unacknowledged.summary["delta"]["reason_code"] == "ACKNOWLEDGEMENT_REQUIRED"

    session = run_session_status(tmp_path)
    assert session.status == "success"
    assert session.summary["task"] == "fix auth"
    assert session.summary["changed_files"] == ["src/app.py"]


def test_session_status_is_partial_before_feedback(tmp_path: Path) -> None:
    report = run_session_status(tmp_path)

    assert report.status == "partial"
    assert report.summary["reason_code"] == "SESSION_MISSING"


def test_changed_content_fingerprint_tracks_bytes_and_missing_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")

    first = _changed_content_fingerprint(tmp_path, ["src/app.py", "deleted.py"])
    source.write_text("VALUE = 2\n", encoding="utf-8")
    second = _changed_content_fingerprint(tmp_path, ["deleted.py", "src/app.py"])

    assert first != second


def test_focused_rerun_covers_supported_runner_families() -> None:
    cases: list[tuple[CheckTask, dict[str, object], list[str]]] = [
        (
            CheckTask("vitest", "unit_tests", ["npm", "test"], "medium", "detected"),
            {"parser": "vitest", "project_frames": ["src/app.test.ts:4"]},
            ["npm", "test", "--", "src/app.test.ts"],
        ),
        (
            CheckTask("phpunit", "unit_tests", ["phpunit"], "medium", "detected"),
            {"parser": "phpunit", "project_frames": [{"file": "tests/AuthTest.php"}]},
            ["vendor/bin/phpunit", "tests/AuthTest.php"],
        ),
        (
            CheckTask(
                "maven",
                "unit_tests",
                ["mvn", "test"],
                "slow",
                "detected",
                workspace="services/api",
            ),
            {"parser": "maven", "project_frames": [{"file": "pom.xml"}]},
            ["mvn", "-pl", "services/api", "test"],
        ),
        (
            CheckTask(
                "gradle",
                "unit_tests",
                ["gradle", "test"],
                "slow",
                "detected",
                workspace="services/api",
            ),
            {"parser": "gradle", "project_frames": [{"file": "build.gradle"}]},
            ["gradle", ":services:api:test"],
        ),
    ]
    for task, parsed, expected in cases:
        assert focused_rerun(task, parsed) == expected

    task = CheckTask("cargo", "unit_tests", ["cargo", "test"], "medium", "detected")
    assert focused_rerun(task, {"parser": "cargo", "project_frames": []}) is None
    assert focused_rerun(task, {"parser": "cargo", "project_frames": [42]}) is None


def test_focused_rerun_does_not_suggest_pytest_for_lint_or_typecheck() -> None:
    ruff_task = CheckTask(
        "ruff", "lint", ["python", "-m", "ruff", "check", "."], "fast", "detected"
    )
    parsed_ruff: dict[str, object] = {
        "tool": "ruff",
        "parser": "ruff",
        "project_frames": [{"file": "packages/ai_cost/estimator.py"}],
    }
    rerun_ruff = focused_rerun(ruff_task, parsed_ruff)
    assert rerun_ruff == ["python", "-m", "ruff", "check", "packages/ai_cost/estimator.py"]

    mypy_task = CheckTask(
        "mypy", "typecheck", ["python", "-m", "mypy", "src", "tests"], "medium", "detected"
    )
    parsed_mypy: dict[str, object] = {
        "tool": "mypy",
        "parser": "mypy",
        "project_frames": [{"file": "packages/intake/risk.py"}],
    }
    rerun_mypy = focused_rerun(mypy_task, parsed_mypy)
    assert rerun_mypy == ["python", "-m", "mypy", "packages/intake/risk.py"]

    eslint_task = CheckTask("npm lint", "lint", ["npm", "run", "lint"], "medium", "detected")
    parsed_eslint: dict[str, object] = {
        "tool": "eslint",
        "parser": "eslint",
        "project_frames": [{"file": "src/app.ts"}],
    }
    assert focused_rerun(eslint_task, parsed_eslint) is None



def test_session_status_rejects_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / ".ai" / "cache" / "session.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": "999"}', encoding="utf-8")

    report = run_session_status(tmp_path)

    assert report.status == "partial"
    assert report.summary["reason_code"] == "SESSION_SCHEMA_UNSUPPORTED"
