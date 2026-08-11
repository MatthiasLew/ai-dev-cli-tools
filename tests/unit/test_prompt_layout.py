from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.cache.prompt_layout import (
    CACHE_LAYOUT_PATH,
    read_cache_layout_manifest,
    write_cache_layout_manifest,
)
from ai_dev_tools.runners.cache import run_cache


def _project(root: Path, value: int = 1) -> None:
    (root / "src").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='layout-demo'\nversion='0.0.0'\n", encoding="utf-8"
    )
    (root / "src" / "app.py").write_text(f"VALUE = {value}\n", encoding="utf-8")


def test_cache_layout_is_relocatable_deterministic_and_has_breakpoints(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _project(left)
    _project(right)

    first, first_path = write_cache_layout_manifest(left)
    second, second_path = write_cache_layout_manifest(right)

    assert first == second
    assert first_path == left / CACHE_LAYOUT_PATH
    assert second_path == right / CACHE_LAYOUT_PATH
    serialized = json.dumps(first, sort_keys=True)
    assert str(left) not in serialized
    assert str(right) not in serialized
    assert "generated_at" not in _keys(first)
    assert "timestamp" not in _keys(first)
    assert "project_root" not in _keys(first)
    assert first["section_order"] == [
        "protocol",
        "project_identity",
        "repository_facts",
        "git_state",
        "task",
        "current_observation",
        "model_response",
    ]
    assert {item["provider"] for item in first["provider_breakpoints"]} == {
        "openai",
        "anthropic",
        "provider-neutral",
    }
    assert all(
        item["after_section"] == "repository_facts" for item in first["provider_breakpoints"]
    )


def test_cache_layout_changes_repository_prefix_but_not_protocol_section(tmp_path: Path) -> None:
    _project(tmp_path)
    first, _ = write_cache_layout_manifest(tmp_path)
    protocol = first["stable_prefix"]["section_fingerprints"]["protocol"]
    fingerprint = first["stable_prefix"]["fingerprint"]

    (tmp_path / "src" / "app.py").write_text("VALUE = 200\n", encoding="utf-8")
    second, _ = write_cache_layout_manifest(tmp_path)

    assert second["stable_prefix"]["section_fingerprints"]["protocol"] == protocol
    assert second["stable_prefix"]["fingerprint"] != fingerprint
    assert (
        second["provider_breakpoints"][0]["prefix_fingerprint"]
        == second["stable_prefix"]["fingerprint"]
    )


def test_cache_layout_runner_writes_artifact_and_reader_rejects_invalid_schema(
    tmp_path: Path,
) -> None:
    _project(tmp_path)

    report = run_cache(tmp_path, "layout")

    assert report.status == "success"
    assert report.summary["cache_layout"]["invariants"]["absolute_paths"] is False
    assert report.artifacts[0].kind == "cache-layout"
    assert read_cache_layout_manifest(tmp_path)["schema_version"] == "1"

    path = tmp_path / CACHE_LAYOUT_PATH
    path.write_text('{"schema_version":"999"}', encoding="utf-8")
    assert read_cache_layout_manifest(tmp_path) == {}
    path.write_text("not-json", encoding="utf-8")
    assert read_cache_layout_manifest(tmp_path) == {}


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {
            key for child in value.values() for key in _keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _keys(child)}
    return set()
