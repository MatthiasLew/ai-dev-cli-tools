from pathlib import Path

from ai_dev_tools.cache.repository import read_repository_index, update_repository_index
from ai_dev_tools.cache.validation import (
    load_validation_result,
    prune_validation_cache,
    store_validation_result,
    validation_cache_key,
    validation_cache_stats,
)
from ai_dev_tools.runners.cache import run_cache
from ai_dev_tools.runners.index import run_index
from ai_dev_tools.utils.subprocess import CommandResult


def test_repository_index_reuses_unchanged_hashes_and_detects_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("one\n", encoding="utf-8")

    first = update_repository_index(tmp_path)
    assert first["summary"] == {"files": 1, "hashed": 1, "reused": 0, "removed": 0}

    second = update_repository_index(tmp_path)
    assert second["summary"] == {"files": 1, "hashed": 0, "reused": 1, "removed": 0}

    source.write_text("different size\n", encoding="utf-8")
    third = update_repository_index(tmp_path)
    assert third["summary"] == {"files": 1, "hashed": 1, "reused": 0, "removed": 0}
    assert read_repository_index(tmp_path)["entries"] == third["entries"]


def test_repository_index_reports_removed_files(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("one\n", encoding="utf-8")
    update_repository_index(tmp_path)
    source.unlink()

    result = update_repository_index(tmp_path)

    assert result["summary"] == {"files": 0, "hashed": 0, "reused": 0, "removed": 1}


def test_validation_cache_requires_exact_key_and_only_stores_success(tmp_path: Path) -> None:
    index = update_repository_index(tmp_path)
    command = ["python", "--version"]
    key = validation_cache_key(index["entries"], command, "")
    result = CommandResult(command, 0, "Python", "", 0.25)

    assert store_validation_result(tmp_path, key, result) is not None
    cached = load_validation_result(tmp_path, key, command)
    assert cached is not None
    assert cached.cached is True
    assert cached.duration_seconds == 0.0
    assert load_validation_result(tmp_path, key, ["python", "-V"]) is None

    failed = CommandResult(command, 1, "", "failed", 0.25)
    assert store_validation_result(tmp_path, "failed", failed) is None


def test_validation_cache_prunes_oldest_entries_to_bounds(tmp_path: Path) -> None:
    directory = tmp_path / ".ai" / "cache" / "checks"
    directory.mkdir(parents=True)
    for index in range(3):
        (directory / f"{index}.json").write_text("x" * (index + 1), encoding="utf-8")

    result = prune_validation_cache(tmp_path, max_entries=2, max_bytes=10)

    assert result["entries"] == 2
    assert result["removed"] == 1
    assert validation_cache_stats(tmp_path)["entries"] == 2


def test_index_runner_supports_status_update_and_rebuild(tmp_path: Path) -> None:
    missing = run_index(tmp_path, "status")
    assert missing.status == "partial"
    assert missing.summary["indexed"] is False

    (tmp_path / "file.txt").write_text("content", encoding="utf-8")
    updated = run_index(tmp_path, "update")
    assert updated.status == "success"
    assert updated.summary["hashed"] == 1
    assert updated.artifacts[0].kind == "repository-index"

    status = run_index(tmp_path, "status")
    assert status.summary["indexed"] is True
    rebuilt = run_index(tmp_path, "rebuild")
    assert rebuilt.summary["hashed"] == 1


def test_cache_runner_reports_prunes_and_clears(tmp_path: Path) -> None:
    directory = tmp_path / ".ai" / "cache" / "checks"
    directory.mkdir(parents=True)
    (directory / "entry.json").write_text("{}", encoding="utf-8")

    status = run_cache(tmp_path, "status")
    assert status.summary["validation_cache"]["entries"] == 1
    assert run_cache(tmp_path, "prune").summary["validation_cache"]["entries"] == 1
    cleared = run_cache(tmp_path, "clear")
    assert cleared.summary["validation_cache"]["removed"] == 1
