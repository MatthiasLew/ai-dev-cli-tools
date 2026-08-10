import sys
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.runtime import runner
from ai_dev_tools.runtime.runner import (
    RunOptions,
    RunPlan,
    resolve_run_plan,
    run_application,
    stop_application,
)


def test_resolve_configured_run_plan(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        '[commands]\nrun = "python -m demo"\n', encoding="utf-8"
    )

    plan = resolve_run_plan(load_settings(tmp_path))

    assert plan is not None
    assert plan.command[:2] == ["python", "-m"]
    assert plan.source == "configured"


def test_resolve_node_run_plan_prefers_dev(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"start": "node server.js", "dev": "vite"}}',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")

    plan = resolve_run_plan(load_settings(tmp_path))

    assert plan is not None
    assert plan.command == ["pnpm", "run", "dev"]


def test_run_explain_never_starts_process(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        '[commands]\nrun = "python -m demo"\n', encoding="utf-8"
    )

    report = run_application(tmp_path, RunOptions(explain=True))

    assert report.status == "success"
    assert report.summary["modifications"] == "NONE"
    assert not (tmp_path / ".ai" / "runtime" / "process.json").exists()


def test_managed_process_stop(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    plan = RunPlan(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        "test",
    )
    monkeypatch.setattr(runner, "resolve_run_plan", lambda settings: plan)

    started = run_application(tmp_path, RunOptions())
    stopped = stop_application(tmp_path, timeout_seconds=10)

    assert started.status == "success"
    assert started.summary["status"] == "running"
    assert stopped.status == "success"
    assert stopped.summary["status"] in {"stopped", "exited"}
    assert "token" not in stopped.summary["state"]


def test_run_blocks_when_managed_process_is_fresh(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    runtime = tmp_path / ".ai" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "process.json").write_text(
        '{"status": "running", "heartbeat_at": "' + datetime.now(UTC).isoformat() + '"}',
        encoding="utf-8",
    )
    report = run_application(tmp_path, RunOptions())

    assert report.status == "blocked"
    assert report.issues[0].code == "ALREADY_RUNNING"


def test_run_blocks_without_detected_command(tmp_path: Path) -> None:
    report = run_application(tmp_path, RunOptions())

    assert report.status == "blocked"
    assert report.issues[0].code == "NO_RUN_COMMAND"


def test_foreground_run_records_failure(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.utils.subprocess import CommandResult

    monkeypatch.setattr(
        runner,
        "resolve_run_plan",
        lambda settings: RunPlan(["demo"], "test"),
    )
    monkeypatch.setattr(
        runner,
        "run_command",
        lambda command, cwd, timeout_seconds: CommandResult(command, 124, "", "timeout", 1.0, True),
    )

    report = run_application(
        tmp_path,
        RunOptions(foreground=True, timeout_seconds=1),
    )

    assert report.status == "failed"
    assert report.summary["timed_out"] is True
    assert report.summary["exit_code"] == 124


def test_background_start_failure_is_reported(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        runner,
        "resolve_run_plan",
        lambda settings: RunPlan(["demo"], "test"),
    )
    monkeypatch.setattr(runner, "_spawn_supervisor", lambda command, cwd: None)
    monkeypatch.setattr(
        runner,
        "_wait_for_state",
        lambda path, statuses, timeout: {"status": "exited", "exit_code": 1},
    )

    report = run_application(tmp_path, RunOptions())

    assert report.status == "failed"
    assert report.issues[0].code == "START_FAILED"


def test_stop_handles_absent_exited_and_invalid_state(tmp_path: Path) -> None:
    absent = stop_application(tmp_path)
    assert absent.status == "partial"

    runtime = tmp_path / ".ai" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    metadata = runtime / "process.json"
    metadata.write_text('{"status": "exited", "token": "hidden"}', encoding="utf-8")
    exited = stop_application(tmp_path)
    assert exited.status == "partial"
    assert "token" not in exited.summary["state"]

    metadata.write_text('{"status": "running"}', encoding="utf-8")
    invalid = stop_application(tmp_path)
    assert invalid.status == "blocked"
    assert invalid.issues[0].code == "INVALID_RUNTIME_STATE"


def test_stop_explain_and_timeout(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    runtime = tmp_path / ".ai" / "runtime"
    runtime.mkdir(parents=True)
    metadata = runtime / "process.json"
    metadata.write_text(
        '{"status": "running", "token": "secret", "child_pid": 10}',
        encoding="utf-8",
    )

    explained = stop_application(tmp_path, explain=True)
    assert explained.status == "success"
    assert explained.summary["status"] == "would_request_stop"
    assert "token" not in explained.summary["state"]

    monkeypatch.setattr(
        runner,
        "_wait_for_state",
        lambda path, statuses, timeout: {"status": "running", "token": "secret"},
    )
    timed_out = stop_application(tmp_path, timeout_seconds=0)
    assert timed_out.status == "failed"
    assert timed_out.issues[0].code == "STOP_TIMEOUT"


def test_resolve_run_plan_handles_invalid_and_yarn_packages(tmp_path: Path) -> None:
    package = tmp_path / "package.json"
    package.write_text("{", encoding="utf-8")
    assert resolve_run_plan(load_settings(tmp_path)) is None

    package.write_text('{"scripts": {"start": "node server.js"}}', encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    plan = resolve_run_plan(load_settings(tmp_path))
    assert plan is not None
    assert plan.command == ["yarn", "run", "start"]


def test_wait_for_state_accepts_complete_atomic_pending_state(tmp_path: Path) -> None:
    metadata = tmp_path / "process.json"
    metadata.write_text('{"status": "stopping"}', encoding="utf-8")
    metadata.with_suffix(".json.tmp").write_text(
        '{"status": "stopped", "exit_code": 0}', encoding="utf-8"
    )

    state = runner._wait_for_state(metadata, {"stopped"}, 0.1)

    assert state["status"] == "stopped"
