import json
from pathlib import Path

from ai_dev_tools.semantic import run_semantic, semantic_capabilities


def test_structural_semantic_index_is_bounded_and_local(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class Service:\n    pass\n\ndef run():\n    return 1\n", encoding="utf-8")

    report = run_semantic(tmp_path, "index")

    assert report.status == "success"
    assert report.summary["backend"] == "structural"
    assert report.summary["symbol_count"] == 2
    payload = json.loads((tmp_path / ".ai" / "cache" / "semantic-index.json").read_text())
    assert payload["symbols"][0]["path"] == "src/service.py"


def test_semantic_capabilities_expose_plugins_lsp_and_fallback() -> None:
    capabilities = semantic_capabilities()
    assert capabilities["plugin_group"] == "ai_dev_tools.semantic_backends"
    assert capabilities["fallback"] == "structural"
    assert capabilities["local_only"] is True


def test_unknown_semantic_backend_fails_closed(tmp_path: Path) -> None:
    report = run_semantic(tmp_path, "index", "does-not-exist")
    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "SEMANTIC_BACKEND_UNAVAILABLE"


def test_semantic_index_truncation_warning_at_10k_symbols(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    (tmp_path / "big.py").write_text("def run(): pass\n", encoding="utf-8")

    many_symbols = [
        {"path": "big.py", "name": f"sym_{i}", "kind": "function", "start_line": i, "end_line": i}
        for i in range(10_005)
    ]
    monkeypatch.setattr(semantic, "_structural_index", lambda r, p: many_symbols)
    rep = run_semantic(tmp_path, "index", "structural")
    assert rep.status == "partial"
    assert rep.summary["truncated"] is True
    assert rep.summary["symbol_count"] == 10_000
    assert rep.summary["total_symbol_count"] == 10_005
    assert any(i.code == "SEMANTIC_INDEX_TRUNCATED" for i in rep.issues)



def test_semantic_status_and_explicit_plugin_backend(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    class Provider:
        def index(self, project_root: Path, paths: list[Path]) -> list[dict[str, object]]:
            return [{"path": "app.py", "name": "provided"}, "ignored"]  # type: ignore[list-item]

    class EntryPoint:
        def load(self):  # type: ignore[no-untyped-def]
            return Provider

    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(semantic, "_backend_entry_points", lambda: {"provider": EntryPoint()})

    report = run_semantic(tmp_path, "index", "provider")
    status = run_semantic(tmp_path, "status")

    assert report.summary["backend"] == "provider"
    assert report.summary["symbol_count"] == 1
    assert status.summary["indexed"] is True


def test_semantic_provider_must_return_a_list(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    class Provider:
        def index(self, project_root: Path, paths: list[Path]) -> object:
            return {"not": "a list"}

    class EntryPoint:
        def load(self):  # type: ignore[no-untyped-def]
            return Provider()

    monkeypatch.setattr(semantic, "_backend_entry_points", lambda: {"invalid": EntryPoint()})
    report = run_semantic(tmp_path, "index", "invalid")
    assert report.status == "invalid_configuration"


def test_auto_tree_sitter_failure_uses_structural_fallback(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: True)
    monkeypatch.setattr(
        semantic,
        "tree_sitter_index",
        lambda root, paths: (_ for _ in ()).throw(RuntimeError("grammar unavailable")),
    )
    report = run_semantic(tmp_path, "index", "auto")
    assert report.status == "partial"
    assert report.summary["backend"] == "structural"
    assert report.issues[0].code == "TREE_SITTER_FALLBACK"


def test_incremental_semantic_reindex(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    file_a = tmp_path / "file_a.py"
    file_b = tmp_path / "file_b.py"
    file_a.write_text("def func_a():\n    pass\n", encoding="utf-8")
    file_b.write_text("def func_b():\n    pass\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []
    original_structural = semantic._structural_index

    def tracked_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        return original_structural(root, paths)

    monkeypatch.setattr(semantic, "_structural_index", tracked_structural)

    # 1. Cold index
    rep1 = run_semantic(tmp_path, "index", "structural")
    assert rep1.status == "success"
    assert rep1.summary["symbol_count"] == 2
    assert len(indexed_batches) == 1
    assert set(indexed_batches[0]) == {"file_a.py", "file_b.py"}

    # 2. Warm index with zero changes
    indexed_batches.clear()
    rep2 = run_semantic(tmp_path, "index", "structural")
    assert rep2.status == "success"
    assert rep2.summary["symbol_count"] == 2
    assert len(indexed_batches) == 0  # no files needed re-indexing!

    # 3. Modify only file_b.py
    file_b.write_text("def func_b():\n    pass\n\ndef func_b2():\n    pass\n", encoding="utf-8")
    indexed_batches.clear()
    rep3 = run_semantic(tmp_path, "index", "structural")
    assert rep3.status == "success"
    assert rep3.summary["symbol_count"] == 3
    assert len(indexed_batches) == 1
    assert indexed_batches[0] == ["file_b.py"]  # ONLY file_b.py was re-indexed!

    index_payload = json.loads((tmp_path / ".ai/cache/semantic-index.json").read_text())
    names = [s["name"] for s in index_payload["symbols"]]
    assert set(names) == {"func_a", "func_b", "func_b2"}

    # 4. Force rebuild
    indexed_batches.clear()
    rep4 = run_semantic(tmp_path, "index", "structural", rebuild=True)
    assert rep4.status == "success"
    assert rep4.summary["symbol_count"] == 3
    assert len(indexed_batches) == 1
    assert set(indexed_batches[0]) == {"file_a.py", "file_b.py"}


def test_semantic_empty_paths_auto_fallback(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: True)
    monkeypatch.setattr(
        semantic,
        "_index_with_backend",
        lambda root, paths, backend: (_ for _ in ()).throw(RuntimeError("empty paths failed")),
    )
    rep = run_semantic(tmp_path, "index", "auto")
    assert rep.status == "partial"
    assert rep.issues[0].code == "TREE_SITTER_FALLBACK"


def test_semantic_fallback_to_index_when_cache_file_missing(tmp_path: Path) -> None:
    from ai_dev_tools.semantic import SEMANTIC_CACHE_PATH, SEMANTIC_INDEX_PATH

    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    rep1 = run_semantic(tmp_path, "index", "structural")
    assert rep1.status == "success"
    assert rep1.summary["files_indexed"] == 1

    # Delete semantic-cache.json, keeping semantic-index.json
    cache_file = tmp_path / SEMANTIC_CACHE_PATH
    index_file = tmp_path / SEMANTIC_INDEX_PATH
    assert cache_file.exists() and index_file.exists()
    cache_file.unlink()

    # Next run should fall back to reading semantic-index.json for incremental cache
    rep2 = run_semantic(tmp_path, "index", "structural")
    assert rep2.status == "success"
    assert rep2.summary["files_reused"] == 1
    assert rep2.summary["files_indexed"] == 0



