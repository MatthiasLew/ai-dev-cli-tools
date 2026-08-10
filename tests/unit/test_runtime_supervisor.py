import json
import sys
import threading
import time
from pathlib import Path

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
