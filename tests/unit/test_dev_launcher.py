from pathlib import Path
from typing import cast

import pytest

from scripts import dev


def test_child_environment_isolated_and_workspace_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)

    environment = dev.child_environment()

    expected = str(tmp_path / ".ai" / "tmp" / "dev")
    assert environment["TMP"] == expected
    assert environment["TEMP"] == expected
    assert environment["TMPDIR"] == expected
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_diagnose_reports_writable_workspace_and_git_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    monkeypatch.setattr(dev, "ROOT", tmp_path)

    report = dev.diagnose()

    assert report["status"] == "ok"
    report_checks = cast(list[dict[str, object]], report["checks"])
    checks = {str(item["code"]): item for item in report_checks}
    assert checks["DEV_WORKSPACE_TEMP"]["status"] == "ok"
    assert checks["DEV_GIT_METADATA"]["status"] == "ok"


def test_environment_fingerprint_tracks_python_project_and_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text("project-v1", encoding="utf-8")
    lock = tmp_path / "requirements-dev.lock"
    lock.write_text("lock-v1", encoding="utf-8")
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(dev, "LOCK", lock)

    first = dev.environment_fingerprint()
    lock.write_text("lock-v2", encoding="utf-8")

    assert len(first) == 64
    assert dev.environment_fingerprint() != first


def test_no_bootstrap_returns_actionable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(dev, "VENV", tmp_path / ".venv")
    monkeypatch.setattr(dev, "MARKER", tmp_path / ".venv" / "marker")
    lock = tmp_path / "requirements-dev.lock"
    lock.write_text("lock", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("project", encoding="utf-8")
    monkeypatch.setattr(dev, "LOCK", lock)

    with pytest.raises(RuntimeError, match="DEV_ENV_MISSING"):
        dev.ensure_environment(allow_bootstrap=False)
