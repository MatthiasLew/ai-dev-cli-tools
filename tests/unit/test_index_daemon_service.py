from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from pytest import MonkeyPatch

from ai_dev_tools import index_daemon_service as service


def test_daemon_status_is_local_and_hides_auth_token(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    path = tmp_path / service.STATE_PATH
    service._write_state(
        path,
        {"status": "running", "port": 1234, "token": "secret", "pid": 42, "events": 3},
    )
    monkeypatch.setattr(service, "_request", lambda state, action: service._public(state))

    report = service.control_index_daemon(tmp_path, "status")

    assert report.status == "success"
    assert report.summary["events"] == 3
    assert "token" not in report.summary


def test_daemon_state_file_is_valid_json_and_private(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    service._write_state(path, {"status": "running"})

    assert json.loads(path.read_text()) == {"status": "running"}
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_native_daemon_processes_event_and_stops_over_ipc(tmp_path: Path) -> None:
    token = "unit-test-token"
    thread = threading.Thread(target=service.serve, args=(tmp_path, token), daemon=True)
    thread.start()
    state: dict[str, object] = {}
    for _ in range(100):
        state = service._read_state(tmp_path / service.STATE_PATH)
        if state.get("status") == "running":
            break
        time.sleep(0.02)
    assert service._request(state, "status")["status"] == "running"

    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    for _ in range(100):
        state = service._read_state(tmp_path / service.STATE_PATH)
        if state.get("updates") == 2:
            break
        time.sleep(0.02)
    assert isinstance(state["events"], int)
    assert state["events"] >= 1
    assert state["updates"] == 2
    assert service._request({**state, "token": "wrong"}, "status")["status"] == "unauthorized"
    assert service._request(state, "stop")["status"] == "stopping"
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert service._read_state(tmp_path / service.STATE_PATH)["status"] == "stopped"


def test_daemon_control_handles_inactive_duplicate_and_invalid_actions(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    assert service.control_index_daemon(tmp_path, "status").status == "partial"
    assert service.control_index_daemon(tmp_path, "stop").status == "partial"
    assert service.control_index_daemon(tmp_path, "invalid").status == "invalid_configuration"

    state = {"status": "running", "port": 123, "token": "token", "pid": 4}
    service._write_state(tmp_path / service.STATE_PATH, state)
    monkeypatch.setattr(service, "_request", lambda current, action: service._public(current))
    report = service.control_index_daemon(tmp_path, "start")
    assert report.status == "blocked"
    stopped = service.control_index_daemon(tmp_path, "stop")
    assert stopped.status == "success"


def test_daemon_control_start_success_and_fast_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    def spawn(command: list[str], root: Path) -> None:
        service._write_state(
            root / service.STATE_PATH,
            {"status": "running", "port": 10, "token": command[-1], "pid": 7},
        )

    monkeypatch.setattr(service, "_spawn", spawn)
    monkeypatch.setattr(service, "_request", lambda state, action: service._public(state))
    report = service.control_index_daemon(tmp_path, "start")
    assert report.status == "success"

    (tmp_path / service.STATE_PATH).unlink()
    monkeypatch.setattr(service, "_spawn", lambda command, root: None)
    ticks = iter((0.0, 11.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    failed = service.control_index_daemon(tmp_path, "start")
    assert failed.status == "failed"


def test_daemon_helpers_reject_broken_state_and_spawn_without_shell(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("not-json", encoding="utf-8")
    assert service._read_state(broken) == {}
    assert service._request({"port": "bad", "token": 1}, "status") == {}

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append(kwargs))
    service._spawn(["python", "worker.py"], tmp_path)
    assert calls[0]["cwd"] == tmp_path
    assert calls[0]["stdin"] == subprocess.DEVNULL


def test_internal_daemon_entrypoint_routes_to_service(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(service, "serve", lambda root, token: 9)
    monkeypatch.setattr(
        sys,
        "argv",
        ["index-daemon", "--serve", "--root", str(tmp_path), "--token", "token"],
    )
    assert service.main() == 9
