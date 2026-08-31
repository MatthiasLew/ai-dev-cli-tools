import socket
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from urllib import request as urllib_request

import pytest

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
    class LiveSupervisor:
        def poll(self) -> None:
            return None

    monkeypatch.setattr(runner, "_spawn_supervisor", lambda command, cwd: LiveSupervisor())
    monkeypatch.setattr(
        runner,
        "_wait_for_state",
        lambda path, statuses, timeout: {"status": "exited", "exit_code": 1},
    )

    report = run_application(tmp_path, RunOptions())

    assert report.status == "failed"
    assert report.issues[0].code == "START_FAILED"


def test_background_start_retries_dead_supervisor_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "resolve_run_plan",
        lambda settings: RunPlan(["demo"], "test"),
    )

    class DeadSupervisor:
        def poll(self) -> int:
            return 1

    spawned: list[list[str]] = []

    def spawn_dead_supervisor(command: list[str], cwd: Path) -> DeadSupervisor:
        del cwd
        spawned.append(command)
        return DeadSupervisor()

    monkeypatch.setattr(runner, "_spawn_supervisor", spawn_dead_supervisor)
    states = iter(({}, {"status": "running", "supervisor_pid": 1, "child_pid": 2}))
    monkeypatch.setattr(runner, "_wait_for_state", lambda path, statuses, timeout: next(states))

    report = run_application(tmp_path, RunOptions())

    assert report.status == "success"
    assert report.summary["startup_attempts"] == 2
    assert len(spawned) == 2


def test_background_start_never_duplicates_live_supervisor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "resolve_run_plan",
        lambda settings: RunPlan(["demo"], "test"),
    )

    class LiveSupervisor:
        def poll(self) -> None:
            return None

    spawned: list[list[str]] = []

    def spawn_live_supervisor(command: list[str], cwd: Path) -> LiveSupervisor:
        del cwd
        spawned.append(command)
        return LiveSupervisor()

    monkeypatch.setattr(runner, "_spawn_supervisor", spawn_live_supervisor)
    monkeypatch.setattr(runner, "_wait_for_state", lambda path, statuses, timeout: {})

    report = run_application(tmp_path, RunOptions())

    assert report.status == "failed"
    assert report.summary["startup_attempts"] == 1
    assert len(spawned) == 1


def test_background_start_stops_after_two_dead_supervisors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "resolve_run_plan",
        lambda settings: RunPlan(["demo"], "test"),
    )

    class DeadSupervisor:
        def poll(self) -> int:
            return 1

    spawned: list[list[str]] = []

    def spawn_dead_supervisor(command: list[str], cwd: Path) -> DeadSupervisor:
        del cwd
        spawned.append(command)
        return DeadSupervisor()

    monkeypatch.setattr(runner, "_spawn_supervisor", spawn_dead_supervisor)
    monkeypatch.setattr(runner, "_wait_for_state", lambda path, statuses, timeout: {})
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    report = run_application(tmp_path, RunOptions())

    assert report.status == "failed"
    assert report.summary["startup_attempts"] == 2
    assert len(spawned) == 2


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


def test_readiness_helpers_support_tcp_http_timeout_and_bounded_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert runner._parse_tcp_endpoint("127.0.0.1:8080") == ("127.0.0.1", 8080)
    for invalid in ("localhost", "localhost:0", "localhost:70000"):
        try:
            runner._parse_tcp_endpoint(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid endpoint: {invalid}")

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda address, timeout: nullcontext(),
    )
    tcp = runner._wait_for_readiness(RunOptions(readiness_tcp="localhost:8080"))
    assert tcp["status"] == "ready"

    class Response:
        status = 204

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(urllib_request, "urlopen", lambda url, timeout: Response())
    http = runner._wait_for_readiness(RunOptions(readiness_http="http://localhost/health"))
    assert http["status"] == "ready"

    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda url, timeout: (_ for _ in ()).throw(OSError("not ready")),
    )
    timed_out = runner._wait_for_readiness(
        RunOptions(readiness_http="http://localhost/health", startup_timeout_seconds=0)
    )
    assert timed_out["status"] == "timeout"
    assert timed_out["last_error"] == "not ready"

    log = tmp_path / "run.log"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert runner._tail_log(log, 2) == ["two", "three"]
    assert runner._tail_log(log, 0) == []
    assert runner._tail_log(tmp_path / "missing.log", 2) == []


def test_background_readiness_failure_stops_owned_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "resolve_run_plan",
        lambda settings: RunPlan(["demo"], "test"),
    )
    monkeypatch.setattr(runner, "_spawn_supervisor", lambda command, cwd: None)
    monkeypatch.setattr(
        runner,
        "_wait_for_state",
        lambda path, statuses, timeout: {
            "status": "running",
            "supervisor_pid": 1,
            "child_pid": 2,
        },
    )
    monkeypatch.setattr(
        runner,
        "_wait_for_readiness",
        lambda options: {"status": "timeout", "attempts": 1},
    )
    stopped: list[str] = []
    monkeypatch.setattr(
        runner,
        "_request_managed_stop",
        lambda paths, token, timeout: stopped.append(token),
    )

    report = run_application(
        tmp_path,
        RunOptions(readiness_http="http://localhost/health", startup_timeout_seconds=0),
    )

    assert report.status == "failed"
    assert report.issues[0].code == "READINESS_TIMEOUT"
    assert len(stopped) == 1
