import json
from pathlib import Path

from ai_dev_tools.runners.index import run_index
from ai_dev_tools.runners.index_daemon import run_index_daemon


def test_index_daemon_supports_bounded_foreground_run(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    report = run_index_daemon(tmp_path, poll_ms=50, max_updates=1)

    assert report.status == "success"
    assert report.summary["updates"] == 1
    state = json.loads((tmp_path / ".ai" / "cache" / "index-daemon.json").read_text())
    assert state["status"] == "stopped"
    assert state["local_only"] is True


def test_index_daemon_rejects_busy_polling(tmp_path: Path) -> None:
    report = run_index_daemon(tmp_path, poll_ms=1, max_updates=1)
    assert report.status == "invalid_configuration"


def test_index_daemon_updates_changed_fingerprint_and_is_visible(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import index_daemon

    indexes = iter(
        [
            {"entries": [{"path": "app.py", "sha256": "one"}]},
            {"entries": [{"path": "app.py", "sha256": "two"}]},
        ]
    )
    monkeypatch.setattr(index_daemon, "update_repository_index", lambda root: next(indexes))
    monkeypatch.setattr(index_daemon.time, "sleep", lambda seconds: None)

    report = run_index_daemon(tmp_path, poll_ms=50, max_updates=2)

    assert report.summary["updates"] == 2
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    status = run_index(tmp_path, "update")
    assert status.summary["daemon"]["status"] == "stopped"


def test_index_daemon_handles_interrupt_and_invalid_fingerprint(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import index_daemon

    monkeypatch.setattr(index_daemon, "update_repository_index", lambda root: {"entries": "bad"})
    monkeypatch.setattr(
        index_daemon.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    report = run_index_daemon(tmp_path, poll_ms=50)

    assert report.status == "partial"
