from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from ai_dev_tools.cache.repository import repository_fingerprint, update_repository_index
from ai_dev_tools.models.report import Issue, Report

STATE_PATH = Path(".ai/cache/index-daemon.json")
IGNORED_EVENT_PARTS = {".ai", ".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__"}


def control_index_daemon(project_root: Path, action: str) -> Report:
    root = project_root.resolve()
    report = Report(command=f"index daemon {action}", project_root=root)
    state_path = root / STATE_PATH
    state = _read_state(state_path)
    if action == "status":
        alive = _request(state, "status") if state else {}
        report.status = "success" if alive else "partial"
        report.summary = alive or {"status": "stopped", "reason_code": "INDEX_DAEMON_NOT_RUNNING"}
        return report
    if action == "stop":
        response = _request(state, "stop") if state else {}
        report.status = "success" if response else "partial"
        report.summary = response or {
            "status": "stopped",
            "reason_code": "INDEX_DAEMON_NOT_RUNNING",
        }
        return report
    if action != "start":
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "UNKNOWN_INDEX_DAEMON_ACTION"}
        return report
    if state and _request(state, "status"):
        report.status = "blocked"
        report.summary = {"reason_code": "INDEX_DAEMON_ALREADY_RUNNING", **_public(state)}
        return report
    token = secrets.token_urlsafe(24)
    command = [
        sys.executable,
        "-m",
        "ai_dev_tools.index_daemon_service",
        "--serve",
        "--root",
        str(root),
        "--token",
        token,
    ]
    _spawn(command, root)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = _read_state(state_path)
        if state.get("status") == "running" and _request(state, "status"):
            report.summary = _public(state)
            return report
        time.sleep(0.05)
    report.status = "failed"
    report.issues.append(Issue("error", "Index daemon failed to start", code="DAEMON_START_FAILED"))
    report.summary = {"reason_code": "DAEMON_START_FAILED"}
    return report


def serve(root: Path, token: str) -> int:
    try:
        # isort: off
        from watchdog.events import (
            FileSystemEvent,
            FileSystemEventHandler,
        )
        from watchdog.observers import Observer
        # isort: on
    except ImportError:
        return 2

    root = root.resolve()
    changes: queue.Queue[str] = queue.Queue()

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event: FileSystemEvent) -> None:
            source_path = os.fsdecode(event.src_path)
            try:
                relative_parts = Path(source_path).resolve().relative_to(root).parts
            except (OSError, ValueError):
                return
            if not IGNORED_EVENT_PARTS.intersection(relative_parts):
                changes.put(source_path)

    index = update_repository_index(root)
    current_fingerprint = repository_fingerprint(index.get("entries", []))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    server.settimeout(0.2)
    port = int(server.getsockname()[1])
    state_path = root / STATE_PATH
    state: dict[str, object] = {
        "schema_version": "2",
        "pid": os.getpid(),
        "status": "running",
        "port": port,
        "token": token,
        "updates": 1,
        "events": 0,
        "watch_mode": "native",
        "ipc": "tcp-localhost",
        "local_only": True,
    }
    observer = Observer()
    observer.schedule(Handler(), str(root), recursive=True)
    observer.start()
    # A published "running" state is a readiness contract: the native
    # watcher must already be accepting events before clients can observe it.
    _write_state(state_path, state)
    stopping = False
    pending_paths: set[str] = set()
    last_event_at = 0.0
    try:
        while not stopping:
            try:
                connection, _ = server.accept()
            except TimeoutError:
                connection = None
            if connection is not None:
                with connection:
                    request = _read_request(connection)
                    authorized = request.get("token") == token
                    action = request.get("action")
                    if authorized and action in {"status", "stop"}:
                        stopping = action == "stop"
                        response = _public(state)
                        if stopping:
                            response["status"] = "stopping"
                        connection.sendall((json.dumps(response) + "\n").encode())
                    else:
                        connection.sendall(b'{"status":"unauthorized"}\n')
            paths: set[str] = set()
            while True:
                try:
                    paths.add(changes.get_nowait())
                except queue.Empty:
                    break
            if paths:
                state["events"] = _state_counter(state, "events") + len(paths)
                pending_paths.update(paths)
                last_event_at = time.monotonic()
            if pending_paths and time.monotonic() - last_event_at >= 0.25:
                current_fingerprint = _refresh_index(
                    root, state, previous_fingerprint=current_fingerprint
                )
                _write_state(state_path, state)
                pending_paths.clear()
    finally:
        if pending_paths:
            _refresh_index(root, state, previous_fingerprint=current_fingerprint)
        observer.stop()
        observer.join(timeout=3)
        server.close()
        state["status"] = "stopped"
        state.pop("token", None)
        _write_state(state_path, state)
    return 0


def _request(state: dict[str, object], action: str) -> dict[str, object]:
    port = state.get("port")
    token = state.get("token")
    if not isinstance(port, int) or not isinstance(token, str):
        return {}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5) as connection:
            connection.sendall((json.dumps({"token": token, "action": action}) + "\n").encode())
            response = json.loads(connection.makefile("rb").readline())
            return response if isinstance(response, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_request(connection: socket.socket) -> dict[str, object]:
    try:
        value = json.loads(connection.makefile("rb").readline(65_536))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_state(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.chmod(0o600)
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def _refresh_index(
    root: Path,
    state: dict[str, object],
    *,
    previous_fingerprint: str,
) -> str:
    index = update_repository_index(root)
    current_fingerprint = repository_fingerprint(index.get("entries", []))
    if current_fingerprint != previous_fingerprint:
        state["updates"] = _state_counter(state, "updates") + 1
    return current_fingerprint


def _public(state: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in state.items() if key != "token"}


def _state_counter(state: dict[str, object], key: str) -> int:
    value = state.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _spawn(command: list[str], cwd: Path) -> None:
    flags = 0
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=os.name != "nt",
        creationflags=flags,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    return serve(args.root, args.token) if args.serve else 2


if __name__ == "__main__":
    raise SystemExit(main())
