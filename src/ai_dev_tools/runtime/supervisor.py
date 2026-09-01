from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import TextIO

from ai_dev_tools.security.secrets import mask_text

_STOP = Event()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-dev-runtime-supervisor")
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--supervisor-cwd", type=Path)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return 2

    for signal_name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, signal_name, None)
        if value is not None:
            # Embedded callers may run the supervisor in a non-main thread.
            with suppress(ValueError):
                signal.signal(value, _request_stop)

    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8", errors="replace") as log:
        starting: dict[str, object] = {
            "schema_version": "1",
            "status": "starting",
            "supervisor_pid": os.getpid(),
            "command": command,
            "cwd": str(args.cwd),
            "log": str(args.log),
            "token": args.token,
            "started_at": _now(),
            "heartbeat_at": _now(),
        }
        _write_json(args.metadata, starting)
        child, start_error, start_attempts = _spawn_child(command, args.cwd)
        if child is None:
            starting.update(
                {
                    "status": "failed",
                    "start_attempts": start_attempts,
                    "error": mask_text(start_error),
                    "finished_at": _now(),
                    "heartbeat_at": _now(),
                }
            )
            _write_json(args.metadata, starting)
            return 75
        if child.stdout is None:
            return 2
        output_thread = Thread(target=_copy_output, args=(child.stdout, log), daemon=True)
        output_thread.start()
        state: dict[str, object] = {
            "schema_version": "1",
            "status": "running",
            "supervisor_pid": os.getpid(),
            "child_pid": child.pid,
            "command": command,
            "cwd": str(args.cwd),
            "log": str(args.log),
            "token": args.token,
            "started_at": _now(),
            "heartbeat_at": _now(),
            "start_attempts": start_attempts,
        }
        _write_json(args.metadata, state)
        try:
            while child.poll() is None:
                if _STOP.is_set() or _stop_requested(args.request, args.token):
                    state["status"] = "stopping"
                    _write_json(args.metadata, state)
                    _terminate(child)
                    break
                state["heartbeat_at"] = _now()
                _write_json(args.metadata, state)
                time.sleep(0.25)
        finally:
            exit_code = child.poll()
            if exit_code is None:
                _terminate(child)
                exit_code = child.poll()
            output_thread.join(timeout=1)
            _release_working_directory(args.supervisor_cwd)
            state["status"] = "stopped" if _STOP.is_set() or args.request.exists() else "exited"
            state["exit_code"] = exit_code
            state["finished_at"] = _now()
            state["heartbeat_at"] = _now()
    # Publish terminal acknowledgement only after the application log is
    # closed and the project working directory has been released.
    _write_json(args.metadata, state)
    if args.request.exists():
        with suppress(OSError):
            args.request.unlink()
    return 0 if state["status"] == "stopped" else int(exit_code or 0)


def _spawn_child(
    command: list[str], cwd: Path, *, attempts: int = 3
) -> tuple[subprocess.Popen[str] | None, str, int]:
    """Start the child with bounded backoff for transient OS resource failures."""
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            child = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                env=os.environ.copy(),
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return child, "", attempt
        except OSError as exc:
            last_error = str(exc)
            if attempt < attempts:
                time.sleep(min(0.1 * attempt, 0.3))
    return None, last_error, attempts


def _request_stop(signum: int, frame: object) -> None:
    del signum, frame
    _STOP.set()


def _stop_requested(path: Path, token: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").strip() == token
    except OSError:
        return False


def _terminate(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _copy_output(stream: TextIO, log: TextIO) -> None:
    for line in stream:
        log.write(mask_text(line))
        log.flush()


def _release_working_directory(
    expected: Path | None, *, current_directory: Path | None = None
) -> None:
    """Release the project directory before publishing the terminal state.

    A detached Windows process keeps its current directory open. Pytest and
    other callers may otherwise receive ``WinError 5`` while cleaning up a
    successfully stopped temporary project.
    """
    if expected is None:
        return
    resolved = expected.resolve()
    current = (current_directory or Path.cwd()).resolve()
    if current != resolved:
        return
    anchor = current.anchor or os.sep
    with suppress(OSError):
        os.chdir(anchor)


def _write_json(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    deadline = time.monotonic() + 1.0
    while True:
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
