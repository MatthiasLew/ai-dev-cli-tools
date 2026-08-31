from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    cached: bool = False
    attempts: int = 1
    flaky: bool = False
    initial_exit_code: int | None = None
    initial_output: str = ""
    cancelled: bool = False
    failure_class: str = "success"
    retryable: bool = False
    infrastructure_recovered: bool = False
    infrastructure_attempts: int = 0

    @property
    def combined_output(self) -> str:
        if self.stderr:
            return f"{self.stdout}\n{self.stderr}".strip()
        return self.stdout.strip()


def split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: int = 300,
    cancel_event: Event | None = None,
) -> CommandResult:
    started = time.monotonic()
    executable_command = _windows_batch_command(command)
    if cancel_event is not None:
        return _run_cancellable(
            command, executable_command, cwd, timeout_seconds, cancel_event, started
        )
    try:
        completed = subprocess.run(
            executable_command,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
        return CommandResult(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=round(time.monotonic() - started, 3),
        )
    except FileNotFoundError as exc:
        return CommandResult(command, 127, "", str(exc), round(time.monotonic() - started, 3))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(
            command, 124, stdout, stderr, round(time.monotonic() - started, 3), True
        )


def _run_cancellable(
    command: list[str],
    executable_command: list[str],
    cwd: Path,
    timeout_seconds: int,
    cancel_event: Event,
    started: float,
) -> CommandResult:
    try:
        process = subprocess.Popen(
            executable_command,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(command, 127, "", str(exc), round(time.monotonic() - started, 3))
    deadline = started + max(timeout_seconds, 0)
    while process.poll() is None:
        cancelled = cancel_event.wait(0.05)
        timed_out = time.monotonic() >= deadline
        if not cancelled and not timed_out:
            continue
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        return CommandResult(
            command,
            130 if cancelled else 124,
            stdout,
            stderr,
            round(time.monotonic() - started, 3),
            timed_out=timed_out,
            cancelled=cancelled,
        )
    stdout, stderr = process.communicate()
    return CommandResult(
        command,
        process.returncode,
        stdout,
        stderr,
        round(time.monotonic() - started, 3),
    )


def _windows_batch_command(command: list[str]) -> list[str]:
    if os.name != "nt" or not command:
        return command
    resolved = shutil.which(command[0]) or command[0]
    executable = resolved.lower()
    if executable.endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        executable_command = [resolved, *command[1:]]
        return [comspec, "/d", "/c", *executable_command]
    return command
