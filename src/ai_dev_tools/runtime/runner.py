from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.security.execution import ExecutionPolicy, assess_command
from ai_dev_tools.security.secrets import mask_text
from ai_dev_tools.utils.subprocess import run_command, split_command


@dataclass(frozen=True, slots=True)
class RunOptions:
    explain: bool = False
    dry_run: bool = False
    foreground: bool = False
    timeout_seconds: int = 300
    readiness_http: str | None = None
    readiness_tcp: str | None = None
    startup_timeout_seconds: int = 10
    startup_log_lines: int = 50


@dataclass(frozen=True, slots=True)
class RunPlan:
    command: list[str]
    source: str
    cwd: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_application(project_root: Path, options: RunOptions) -> Report:
    settings = load_settings(project_root)
    report = Report(command="run", project_root=settings.project_root)
    plan = resolve_run_plan(settings)
    configured = settings.execution
    assessment = (
        assess_command(
            plan.command,
            settings.project_root / plan.cwd,
            ExecutionPolicy(
                mode=configured.mode,
                allow_prefixes=tuple(configured.allow_prefixes),
                deny_prefixes=tuple(configured.deny_prefixes),
                maximum_impact=configured.maximum_impact,
            ),
        )
        if plan is not None
        else None
    )
    paths = _runtime_paths(settings.project_root)
    current = _read_json(paths["metadata"])
    if current.get("status") in {"running", "stopping"} and _heartbeat_is_fresh(current):
        report.status = "blocked"
        report.issues.append(
            Issue("error", "A managed project process is already running.", code="ALREADY_RUNNING")
        )
    elif plan is None:
        report.status = "blocked"
        report.issues.append(
            Issue(
                "error",
                "No safe run command detected. Configure [commands].run.",
                code="NO_RUN_COMMAND",
            )
        )
    elif assessment is not None and not assessment.allowed:
        report.status = "blocked"
        report.exit_code = 126
        report.issues.append(
            Issue(
                "error",
                "Run command blocked by execution policy.",
                code=assessment.reason_code,
            )
        )
        report.summary = {
            "plan": plan.to_dict(),
            "execution_policy": assessment.to_dict(),
            "modifications": "NONE",
        }
    elif options.explain or options.dry_run:
        report.summary = {
            "plan": plan.to_dict(),
            "explain": options.explain,
            "dry_run": options.dry_run,
            "modifications": "NONE",
            "readiness": _readiness_config(options),
            "execution_policy": assessment.to_dict() if assessment is not None else {},
        }
    elif options.foreground:
        result = run_command(
            plan.command,
            settings.project_root / plan.cwd,
            timeout_seconds=options.timeout_seconds,
        )
        report.status = "success" if result.exit_code == 0 else "failed"
        report.exit_code = result.exit_code
        paths["log"].parent.mkdir(parents=True, exist_ok=True)
        paths["log"].write_text(mask_text(result.combined_output) + "\n", encoding="utf-8")
        report.artifacts.append(Artifact(str(paths["log"]), "log", "Application output"))
        report.summary = {
            "plan": plan.to_dict(),
            "mode": "foreground",
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        }
    else:
        token = secrets.token_urlsafe(24)
        _remove_stale_request(paths["request"])
        supervisor_command = [
            sys.executable,
            "-m",
            "ai_dev_tools.runtime.supervisor",
            "--metadata",
            str(paths["metadata"]),
            "--request",
            str(paths["request"]),
            "--token",
            token,
            "--cwd",
            str(settings.project_root / plan.cwd),
            "--log",
            str(paths["log"]),
            "--",
            *plan.command,
        ]
        state: dict[str, object] = {}
        startup_attempts = 0
        for attempt in range(1, 3):
            startup_attempts = attempt
            supervisor = _spawn_supervisor(supervisor_command, settings.project_root)
            state = _wait_for_state(paths["metadata"], {"running", "exited"}, 10.0)
            if state.get("status") in {"running", "exited"}:
                break
            # Retry only after the supervisor itself has exited before publishing
            # a handshake. A live supervisor must never be duplicated.
            if supervisor.poll() is None:
                break
            time.sleep(0.1)
        readiness: dict[str, object] = {"status": "not_configured"}
        if state.get("status") != "running":
            report.status = "failed"
            report.issues.append(
                Issue("error", "Managed process failed to start.", code="START_FAILED")
            )
        else:
            readiness = _wait_for_readiness(options)
            if readiness["status"] == "ready":
                report.status = "success"
            else:
                report.status = "failed"
                report.issues.append(
                    Issue(
                        "error",
                        "Managed process did not pass its readiness check in time.",
                        code="READINESS_TIMEOUT",
                    )
                )
                _request_managed_stop(paths, token, 5)
        report.summary = {
            "plan": plan.to_dict(),
            "mode": "background",
            "status": state.get("status", "unknown"),
            "supervisor_pid": state.get("supervisor_pid"),
            "child_pid": state.get("child_pid"),
            "readiness": readiness,
            "startup_attempts": startup_attempts,
            "startup_log": _tail_log(paths["log"], options.startup_log_lines),
            "stale_metadata_recovered": bool(current) and not _heartbeat_is_fresh(current),
        }
        report.artifacts.extend(
            [
                Artifact(str(paths["log"]), "log", "Application output"),
                Artifact(str(paths["metadata"]), "runtime-state", "Managed process state"),
            ]
        )
    if not report.summary:
        report.summary = {
            "plan": plan.to_dict() if plan else None,
            "explain": options.explain,
            "dry_run": options.dry_run,
        }
    report.finish()
    write_markdown(report, settings.reports_directory / "run-latest.md")
    write_json(report, settings.reports_directory / "run-latest.json")
    return report


def stop_application(
    project_root: Path, *, explain: bool = False, timeout_seconds: int = 10
) -> Report:
    settings = load_settings(project_root)
    report = Report(command="stop", project_root=settings.project_root)
    paths = _runtime_paths(settings.project_root)
    state = _read_json(paths["metadata"])
    public_state = _public_state(state)
    if not state:
        report.status = "partial"
        report.summary = {"status": "not_running", "state": {}}
    elif state.get("status") not in {"running", "stopping"}:
        report.status = "partial"
        report.summary = {"status": "not_running", "state": public_state}
    elif not isinstance(state.get("token"), str):
        report.status = "blocked"
        report.issues.append(
            Issue(
                "error", "Runtime state has no valid control token.", code="INVALID_RUNTIME_STATE"
            )
        )
        report.summary = {"status": "unknown", "state": public_state}
    elif explain:
        report.summary = {
            "status": "would_request_stop",
            "state": public_state,
            "modifications": "NONE",
        }
    else:
        paths["request"].parent.mkdir(parents=True, exist_ok=True)
        paths["request"].write_text(str(state["token"]), encoding="utf-8")
        stopped = _wait_for_state(paths["metadata"], {"stopped", "exited"}, timeout_seconds)
        if stopped.get("status") not in {"stopped", "exited"}:
            report.status = "failed"
            report.issues.append(
                Issue(
                    "error",
                    "Supervisor did not acknowledge the stop request; no arbitrary PID was killed.",
                    code="STOP_TIMEOUT",
                )
            )
        else:
            report.status = "success"
        report.summary = {
            "status": stopped.get("status", "unknown"),
            "state": _public_state(stopped),
        }
    if paths["metadata"].exists():
        report.artifacts.append(
            Artifact(str(paths["metadata"]), "runtime-state", "Managed process state")
        )
    report.finish()
    write_markdown(report, settings.reports_directory / "stop-latest.md")
    write_json(report, settings.reports_directory / "stop-latest.json")
    return report


def resolve_run_plan(settings: Settings) -> RunPlan | None:
    configured = settings.commands.get("run")
    if configured:
        command = split_command(configured)
        return RunPlan(command, "configured") if command else None
    package_path = settings.project_root / "package.json"
    if package_path.exists():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if isinstance(scripts, dict):
            for name in ("dev", "start", "serve"):
                if isinstance(scripts.get(name), str):
                    manager = _node_manager(settings.project_root)
                    return RunPlan([manager, "run", name], f"package.json#scripts.{name}")
    return None


def _node_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _spawn_supervisor(command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    flags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        shell=False,
        start_new_session=start_new_session,
        creationflags=flags,
    )


def _readiness_config(options: RunOptions) -> dict[str, object]:
    return {
        "http": options.readiness_http,
        "tcp": options.readiness_tcp,
        "timeout_seconds": options.startup_timeout_seconds,
    }


def _wait_for_readiness(options: RunOptions) -> dict[str, object]:
    if options.readiness_http is None and options.readiness_tcp is None:
        return {"status": "ready", "check": "process_started", "attempts": 0}
    deadline = time.monotonic() + max(options.startup_timeout_seconds, 0)
    attempts = 0
    last_error = ""
    while True:
        attempts += 1
        try:
            if options.readiness_http is not None:
                with urllib_request.urlopen(options.readiness_http, timeout=0.5) as response:
                    if response.status >= 500:
                        raise OSError(f"HTTP {response.status}")
            if options.readiness_tcp is not None:
                host, port = _parse_tcp_endpoint(options.readiness_tcp)
                with socket.create_connection((host, port), timeout=0.5):
                    pass
            return {"status": "ready", "check": _readiness_config(options), "attempts": attempts}
        except (OSError, ValueError, urllib_error.URLError) as exc:
            last_error = mask_text(str(exc))
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
    return {
        "status": "timeout",
        "check": _readiness_config(options),
        "attempts": attempts,
        "last_error": last_error,
    }


def _parse_tcp_endpoint(value: str) -> tuple[str, int]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host:
        raise ValueError("TCP readiness must use host:port")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise ValueError("TCP readiness port must be between 1 and 65535")
    return host, port


def _tail_log(path: Path, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    except OSError:
        return []


def _request_managed_stop(paths: dict[str, Path], token: str, timeout: int) -> None:
    paths["request"].parent.mkdir(parents=True, exist_ok=True)
    paths["request"].write_text(token, encoding="utf-8")
    _wait_for_state(paths["metadata"], {"stopped", "exited"}, timeout)


def _runtime_paths(root: Path) -> dict[str, Path]:
    directory = root / ".ai" / "runtime"
    return {
        "metadata": directory / "process.json",
        "request": directory / "stop.request",
        "log": root / ".ai" / "logs" / "run-latest.log",
    }


def _wait_for_state(path: Path, statuses: set[str], timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + max(timeout, 0)
    latest: dict[str, object] = {}
    while time.monotonic() <= deadline:
        latest = _read_json(path)
        if latest.get("status") in statuses:
            return latest
        pending = _read_json(path.with_suffix(path.suffix + ".tmp"))
        if pending.get("status") in statuses:
            return pending
        time.sleep(0.05)
    return latest


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _heartbeat_is_fresh(state: dict[str, object]) -> bool:
    heartbeat = state.get("heartbeat_at")
    if not isinstance(heartbeat, str):
        return False
    try:
        from datetime import datetime

        age = datetime.now().astimezone() - datetime.fromisoformat(heartbeat).astimezone()
        return age.total_seconds() < 5
    except ValueError:
        return False


def _public_state(state: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in state.items() if key != "token"}


def _remove_stale_request(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()
