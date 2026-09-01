import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import cast

import pytest

from ai_dev_tools.runtime import supervisor


def test_supervisor_records_natural_exit(tmp_path: Path) -> None:
    metadata = tmp_path / "process.json"
    request = tmp_path / "stop.request"
    log = tmp_path / "application.log"

    exit_code = supervisor.main(
        [
            "--metadata",
            str(metadata),
            "--request",
            str(request),
            "--token",
            "test-token",
            "--cwd",
            str(tmp_path),
            "--log",
            str(log),
            "--",
            sys.executable,
            "-c",
            "print('ready')",
        ]
    )

    state = json.loads(metadata.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert state["status"] == "exited"
    assert state["exit_code"] == 0
    assert "ready" in log.read_text(encoding="utf-8")


def test_supervisor_honors_matching_stop_request(tmp_path: Path) -> None:
    metadata = tmp_path / "process.json"
    request = tmp_path / "stop.request"
    log = tmp_path / "application.log"
    result: list[int] = []

    def supervise() -> None:
        result.append(
            supervisor.main(
                [
                    "--metadata",
                    str(metadata),
                    "--request",
                    str(request),
                    "--token",
                    "stop-token",
                    "--cwd",
                    str(tmp_path),
                    "--log",
                    str(log),
                    "--",
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ]
            )
        )

    thread = threading.Thread(target=supervise)
    thread.start()
    deadline = time.monotonic() + 5
    while not metadata.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    request.write_text("stop-token", encoding="utf-8")
    thread.join(timeout=10)

    state = json.loads(metadata.read_text(encoding="utf-8"))
    assert not thread.is_alive()
    assert result == [0]
    assert state["status"] == "stopped"
    assert not request.exists()


def test_supervisor_rejects_empty_command(tmp_path: Path) -> None:
    assert (
        supervisor.main(
            [
                "--metadata",
                str(tmp_path / "process.json"),
                "--request",
                str(tmp_path / "stop.request"),
                "--token",
                "token",
                "--cwd",
                str(tmp_path),
                "--log",
                str(tmp_path / "log"),
            ]
        )
        == 2
    )


def test_release_working_directory_uses_filesystem_anchor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed_to: list[str] = []
    monkeypatch.setattr(os, "chdir", changed_to.append)

    supervisor._release_working_directory(tmp_path, current_directory=tmp_path)

    assert changed_to == [tmp_path.resolve().anchor]


def test_supervisor_masks_streamed_application_output(tmp_path: Path) -> None:
    metadata = tmp_path / "process.json"
    log = tmp_path / "application.log"
    secret = "sk-" + "s" * 24

    exit_code = supervisor.main(
        [
            "--metadata",
            str(metadata),
            "--request",
            str(tmp_path / "stop.request"),
            "--token",
            "control-token",
            "--cwd",
            str(tmp_path),
            "--log",
            str(log),
            "--",
            sys.executable,
            "-c",
            f"print('{secret}')",
        ]
    )

    output = log.read_text(encoding="utf-8")
    assert exit_code == 0
    assert secret not in output
    assert "MASKED_OPENAI_KEY" in output


def _wait_for_metadata(path: Path) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.02)
    raise AssertionError(f"supervisor metadata was not created: {path}")


def _external_supervisor(tmp_path: Path) -> tuple[subprocess.Popen[str], Path, Path]:
    metadata = tmp_path / "external-process.json"
    request = tmp_path / "external-stop.request"
    command = [
        sys.executable,
        "-m",
        "ai_dev_tools.runtime.supervisor",
        "--metadata",
        str(metadata),
        "--request",
        str(request),
        "--token",
        "external-token",
        "--cwd",
        str(tmp_path),
        "--log",
        str(tmp_path / "external.log"),
        "--",
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
    ]
    process = subprocess.Popen(command, text=True)
    _wait_for_metadata(metadata)
    return process, metadata, request


def test_external_supervisor_honors_control_token_on_every_platform(tmp_path: Path) -> None:
    process, metadata, request = _external_supervisor(tmp_path)
    try:
        request.write_text("external-token", encoding="utf-8")
        assert process.wait(timeout=10) == 0
        state = _wait_for_metadata(metadata)
        assert state["status"] == "stopped"
        assert not request.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal semantics")
def test_external_supervisor_handles_sigterm_and_reaps_child(tmp_path: Path) -> None:
    process, metadata, _ = _external_supervisor(tmp_path)
    child_pid_value = _wait_for_metadata(metadata)["child_pid"]
    assert isinstance(child_pid_value, int)
    child_pid = child_pid_value
    try:
        os.kill(process.pid, signal.SIGTERM)
        assert process.wait(timeout=10) == 0
        state = _wait_for_metadata(metadata)
        assert state["status"] == "stopped"
        assert state["exit_code"] is not None
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
