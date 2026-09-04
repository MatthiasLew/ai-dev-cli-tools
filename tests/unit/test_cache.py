from pathlib import Path
from typing import cast

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
    assert first["summary"] == {
        "files": 1,
        "hashed": 1,
        "reused": 0,
        "removed": 0,
        "graph_edges": 0,
    }

    second = update_repository_index(tmp_path)
    assert second["summary"] == {
        "files": 1,
        "hashed": 0,
        "reused": 1,
        "removed": 0,
        "graph_edges": 0,
    }

    source.write_text("different size\n", encoding="utf-8")
    third = update_repository_index(tmp_path)
    assert third["summary"] == {
        "files": 1,
        "hashed": 1,
        "reused": 0,
        "removed": 0,
        "graph_edges": 0,
    }
    assert read_repository_index(tmp_path)["entries"] == third["entries"]


def test_repository_index_reports_removed_files(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("one\n", encoding="utf-8")
    update_repository_index(tmp_path)
    source.unlink()

    result = update_repository_index(tmp_path)

    assert result["summary"] == {
        "files": 0,
        "hashed": 0,
        "reused": 0,
        "removed": 1,
        "graph_edges": 0,
    }


def test_repository_index_ignores_named_virtualenvs(tmp_path: Path) -> None:
    venv_dir = tmp_path / ".venv-release" / "lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "pkg.py").write_text("code\n", encoding="utf-8")
    source = tmp_path / "main.py"
    source.write_text("print(1)\n", encoding="utf-8")
    result = update_repository_index(tmp_path)
    entries = cast(list[dict[str, object]], result["entries"])
    paths = [entry["path"] for entry in entries]
    assert "main.py" in paths
    assert not any(".venv-release" in str(p) for p in paths)



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
    assert missing.summary["reason_code"] == "INDEX_MISSING"

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


def test_repository_index_builds_and_reuses_impact_graph(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    test = tmp_path / "tests" / "test_service.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    test.write_text("from src.service import VALUE\n", encoding="utf-8")

    first = update_repository_index(tmp_path)
    second = update_repository_index(tmp_path)
    first_graph = cast(list[dict[str, str]], first["graph"])
    second_graph = cast(list[dict[str, str]], second["graph"])

    assert {(edge["from"], edge["to"], edge["kind"]) for edge in first_graph} >= {
        ("src/service.py", "tests/test_service.py", "test")
    }
    assert second_graph == first_graph
    second_summary = cast(dict[str, object], second["summary"])
    assert cast(int, second_summary["graph_edges"]) >= 1


def test_impact_graph_extracts_python_js_rust_and_reuses_edges(tmp_path: Path) -> None:
    from ai_dev_tools.cache.graph import build_impact_graph, related_tests, shortest_reason_paths

    files = {
        "src/app.py": "import util\n",
        "util.py": "VALUE = 1\n",
        "web/app.ts": "import {value} from './util'\n",
        "web/util.ts": "export const value = 1\n",
        "rust/main.rs": "mod helper;\n",
        "rust/helper.rs": "pub fn helper() {}\n",
        "tests/test_app.py": "def test_app(): pass\n",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    graph = build_impact_graph(tmp_path, set(files))
    edges = {(edge["from"], edge["to"], edge["kind"]) for edge in graph}

    assert ("src/app.py", "util.py", "import") in edges
    assert ("web/app.ts", "web/util.ts", "import") in edges
    assert ("rust/main.rs", "rust/helper.rs", "import") in edges
    assert related_tests(graph, ["src/app.py"]) == ["tests/test_app.py"]
    assert related_tests("invalid", ["src/app.py"]) == []
    paths = shortest_reason_paths(
        graph,
        ["src/app.py"],
        selected_files=["util.py"],
        changed_symbols=[{"path": "src/app.py", "name": "run"}],
        selected_tests=["tests/test_app.py"],
        selected_commands=[["pytest", "tests/test_app.py"]],
        selection_reason_code="CHANGED_DIRECT_TEST_MATCH",
    )
    by_target = {item["target"]: item for item in paths}
    util_steps = cast(list[dict[str, object]], by_target["util.py"]["steps"])
    command_steps = cast(
        list[dict[str, object]], by_target["pytest tests/test_app.py"]["steps"]
    )
    assert [step["value"] for step in util_steps] == [
        "src/app.py",
        "util.py",
    ]
    assert by_target["src/app.py#run"]["target_kind"] == "symbol"
    assert command_steps[-1]["kind"] == "check"

    reused = build_impact_graph(
        tmp_path,
        set(files),
        reused_paths={"src/app.py"},
        previous_edges=graph,
    )
    assert ("src/app.py", "util.py", "import") in {
        (edge["from"], edge["to"], edge["kind"]) for edge in reused
    }


def test_impact_graph_tracks_configuration_generated_code_and_reverse_dependents(
    tmp_path: Path,
) -> None:
    from ai_dev_tools.cache.graph import build_impact_graph, shortest_reason_paths

    files = {
        "pyproject.toml": "[project]\nname='demo'\n",
        "schema.proto": "message Item {}\n",
        "src/generated.py": "# generated from ../schema.proto\nVALUE = 1\n",
        "src/consumer.py": "from src.generated import VALUE\n",
        "tests/test_consumer.py": "from src.consumer import VALUE\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    graph = build_impact_graph(tmp_path, set(files))
    edges = {(edge["from"], edge["to"], edge["kind"]) for edge in graph}
    paths = shortest_reason_paths(
        graph,
        ["schema.proto"],
        selected_files=["src/generated.py", "src/consumer.py"],
    )
    by_target = {item["target"]: item for item in paths}

    assert ("pyproject.toml", "src/consumer.py", "configuration") in edges
    assert ("schema.proto", "src/generated.py", "generated") in edges
    assert by_target["src/generated.py"]["reason_code"] == "GENERATED_RELATIONSHIP"
    assert by_target["src/consumer.py"]["reason_code"] == "DEPENDENT_FILE"
