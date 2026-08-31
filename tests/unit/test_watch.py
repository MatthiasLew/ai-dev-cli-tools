from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import pytest

from ai_dev_tools.cli import main
from ai_dev_tools.models.report import Report
from ai_dev_tools.runners import watch
from ai_dev_tools.runners.watch import WatchOptions, run_watch


def test_watch_initial_run_is_bounded_and_writes_latest_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_check(root: Path, **kwargs: object) -> Report:
        calls.append(str(kwargs["mode"]))
        return Report(command="check --mode changed", project_root=root).finish()

    monkeypatch.setattr(watch, "run_check", fake_check)

    report = run_watch(
        tmp_path,
        WatchOptions(initial=True, max_runs=1, debounce_ms=0, poll_ms=10),
    )

    assert report.status == "success"
    assert calls == ["changed"]
    assert report.summary["validations"] == 1
    assert report.summary["foreground"] is True
    assert (tmp_path / ".ai" / "reports" / "watch-latest.json").exists()


def test_watch_detects_and_debounces_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = iter(
        [
            {},
            {"src/demo.py": (1, 1)},
            {"src/demo.py": (1, 1)},
            {"src/demo.py": (1, 1)},
        ]
    )
    monkeypatch.setattr(watch, "_snapshot", lambda root, ignored: next(snapshots))
    monkeypatch.setattr(
        watch,
        "run_check",
        lambda root, **kwargs: Report(command="check", project_root=root).finish(),
    )

    report = run_watch(
        tmp_path,
        WatchOptions(max_runs=1, debounce_ms=0, poll_ms=10),
    )

    assert report.summary["validations"] == 1
    assert report.summary["latest_status"] == "success"


def test_watch_rejects_invalid_options(tmp_path: Path) -> None:
    report = run_watch(tmp_path, WatchOptions(poll_ms=1))

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "INVALID_WATCH_OPTIONS"


def test_watch_cli_is_wired(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        watch,
        "run_check",
        lambda root, **kwargs: Report(command="check", project_root=root).finish(),
    )

    exit_code = main(
        [
            "--project",
            str(tmp_path),
            "--json",
            "watch",
            "--initial",
            "--max-runs",
            "1",
            "--debounce",
            "0",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["command"] == "watch --mode changed"
    assert payload["summary"]["validations"] == 1


def test_watch_cancels_obsolete_validation_and_queues_latest_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = [
        {},
        {"src/demo.py": (1, 1)},
        {"src/demo.py": (1, 1)},
        {"src/demo.py": (2, 1)},
    ]
    cancellation_seen: list[bool] = []

    monkeypatch.setattr(
        watch,
        "_snapshot",
        lambda root, ignored: snapshots.pop(0) if len(snapshots) > 1 else snapshots[0],
    )

    def fake_check(root: Path, **kwargs: object) -> Report:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, Event)
        cancel_event.wait(1)
        cancellation_seen.append(cancel_event.is_set())
        return Report(command="check", project_root=root, status="failed").finish()

    monkeypatch.setattr(watch, "run_check", fake_check)
    report = run_watch(tmp_path, WatchOptions(max_runs=1, debounce_ms=0, poll_ms=10))

    assert cancellation_seen == [True]
    assert report.summary["cancelled_obsolete"] == 1
    assert report.summary["queued_during_validation"] == 1
