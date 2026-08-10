from __future__ import annotations

from pathlib import Path

from ai_dev_tools.runners import check
from ai_dev_tools.runners.check_models import CheckTask
from ai_dev_tools.runners.check_scheduler import schedule_checks, schedule_graph
from ai_dev_tools.utils.subprocess import CommandResult


def _result(task: CheckTask, exit_code: int = 0) -> CommandResult:
    return CommandResult(task.command, exit_code, "", "failed" if exit_code else "", 0.1)


def test_feedback_first_cancels_expensive_wave_after_required_failure() -> None:
    fast = CheckTask("lint", "lint", ["lint"], "fast", "configured")
    slow = CheckTask("integration", "integration_tests", ["test"], "slow", "configured")
    calls: list[str] = []

    def execute(task: CheckTask) -> CommandResult:
        calls.append(task.name)
        return _result(task, 1)

    result = schedule_checks(
        [fast, slow],
        jobs=4,
        policy="feedback-first",
        execute=execute,
    )

    assert calls == ["lint"]
    assert result.tasks == [fast]
    assert result.cancelled == [slow]
    assert result.time_to_first_failure_seconds is not None
    assert schedule_graph([fast, slow], "feedback-first")["fail_fast"] is True


def test_complete_policy_preserves_deterministic_result_order() -> None:
    first = CheckTask("first", "lint", ["one"], "fast", "configured")
    second = CheckTask("second", "unit_tests", ["two"], "medium", "configured")

    result = schedule_checks(
        [first, second],
        jobs=2,
        policy="complete",
        execute=lambda task: _result(task),
    )

    assert [task.name for task in result.tasks] == ["first", "second"]
    assert [item.command for item in result.results] == [["one"], ["two"]]
    assert result.cancelled == []


def test_resume_reuses_only_exact_cached_checkpoints(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[commands]\nlint='python --version'\ntest='python --version'\n",
        encoding="utf-8",
    )

    first = check.run_check(tmp_path, "full")
    resumed = check.run_check(tmp_path, "full", resume=True)

    assert first.status == "success"
    assert resumed.status == "success"
    assert resumed.summary["execution"]["resumed"] == 2
    assert {item["reuse"] for item in resumed.summary["results"]} == {"resumed"}
    assert any(artifact.kind == "checkpoint" for artifact in resumed.artifacts)


def test_feedback_first_report_lists_cancelled_checks(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    tasks = [
        CheckTask("lint", "lint", ["lint"], "fast", "configured"),
        CheckTask("integration", "integration_tests", ["integration"], "slow", "configured"),
    ]
    monkeypatch.setattr(check, "build_validation_plan", lambda settings: tasks)
    monkeypatch.setattr(
        check,
        "_run_logged",
        lambda task, root, logs, entries, cache: _result(task, 1 if task.name == "lint" else 0),
    )

    report = check.run_check(tmp_path, "full", policy="feedback-first")

    assert report.status == "failed"
    assert [item["name"] for item in report.summary["execution"]["cancelled"]] == ["integration"]
    assert report.summary["checks_total"] == 1


def test_checkpoint_rejects_invalid_and_stale_entries(tmp_path: Path) -> None:
    from ai_dev_tools.runners.check_checkpoint import load_resume_keys

    path = tmp_path / ".ai" / "cache" / "check-checkpoint.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")
    assert load_resume_keys(tmp_path, {"current"}) == set()

    path.write_text('{"schema_version":"999","completed_keys":["current"]}', encoding="utf-8")
    assert load_resume_keys(tmp_path, {"current"}) == set()

    path.write_text('{"schema_version":"1","completed_keys":"invalid"}', encoding="utf-8")
    assert load_resume_keys(tmp_path, {"current"}) == set()

    path.write_text(
        '{"schema_version":"1","completed_keys":["current","stale",42]}',
        encoding="utf-8",
    )
    assert load_resume_keys(tmp_path, {"current"}) == {"current"}
