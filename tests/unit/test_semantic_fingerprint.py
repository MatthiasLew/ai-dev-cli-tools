from __future__ import annotations

from pathlib import Path

from ai_dev_tools import semantic
from ai_dev_tools.semantic import run_semantic


def test_same_file_and_fingerprint_reuses_cache(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []
    original_structural = semantic._structural_index

    def tracked_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        return original_structural(root, paths)

    monkeypatch.setattr(semantic, "_structural_index", tracked_structural)

    rep1 = run_semantic(tmp_path, "index", backend="structural")
    assert rep1.status == "success"
    assert len(indexed_batches) == 1

    indexed_batches.clear()
    rep2 = run_semantic(tmp_path, "index", backend="structural")
    assert rep2.status == "success"
    assert len(indexed_batches) == 0, "Same fingerprint and file must reuse cache"


def test_change_schema_version_invalidates_cache_and_rebuilds(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []
    original_structural = semantic._structural_index

    def tracked_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        return original_structural(root, paths)

    monkeypatch.setattr(semantic, "_structural_index", tracked_structural)

    run_semantic(tmp_path, "index", backend="structural")
    assert len(indexed_batches) == 1

    monkeypatch.setattr(semantic, "SEMANTIC_SCHEMA_VERSION", "99")

    indexed_batches.clear()
    rep = run_semantic(tmp_path, "index", backend="structural")
    assert rep.status == "success"
    assert len(indexed_batches) == 1, "Schema version change must force re-indexing"
    assert indexed_batches[0] == ["app.py"]


def test_change_backend_invalidates_cache_and_rebuilds(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: True)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []

    def mock_ts_index(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append(["ts:" + p.name for p in paths])
        return [{"path": "app.py", "name": "run", "kind": "function"}]

    def mock_str_index(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append(["str:" + p.name for p in paths])
        return [{"path": "app.py", "name": "run", "kind": "function"}]

    monkeypatch.setattr(semantic, "tree_sitter_index", mock_ts_index)
    monkeypatch.setattr(semantic, "_structural_index", mock_str_index)

    run_semantic(tmp_path, "index", backend="structural")
    assert indexed_batches == [["str:app.py"]]

    indexed_batches.clear()
    rep = run_semantic(tmp_path, "index", backend="treesitter")
    assert rep.status == "success"
    assert indexed_batches == [["ts:app.py"]]


def test_change_config_invalidates_cache(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []
    original_structural = semantic._structural_index

    def tracked_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        return original_structural(root, paths)

    monkeypatch.setattr(semantic, "_structural_index", tracked_structural)

    run_semantic(tmp_path, "index", backend="structural")
    assert len(indexed_batches) == 1

    new_suffixes = {".py", ".js", ".custom"}
    monkeypatch.setattr(semantic, "SUPPORTED_SUFFIXES", new_suffixes)

    indexed_batches.clear()
    rep = run_semantic(tmp_path, "index", backend="structural")
    assert rep.status == "success"
    assert len(indexed_batches) == 1, "Config change must invalidate cache and rebuild"


def test_package_version_bump_does_not_invalidate_cache(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import ai_dev_tools

    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []
    original_structural = semantic._structural_index

    def tracked_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        return original_structural(root, paths)

    monkeypatch.setattr(semantic, "_structural_index", tracked_structural)

    run_semantic(tmp_path, "index", backend="structural")
    assert len(indexed_batches) == 1

    # Simulate bumping package release version e.g. 1.3.0 -> 9.9.9
    monkeypatch.setattr(ai_dev_tools, "__version__", "9.9.9")

    indexed_batches.clear()
    rep = run_semantic(tmp_path, "index", backend="structural")
    assert rep.status == "success"
    assert len(indexed_batches) == 0, "Package version bump must NOT invalidate semantic cache"


def test_change_extractor_version_invalidates_cache(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []
    original_structural = semantic._structural_index

    def tracked_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        return original_structural(root, paths)

    monkeypatch.setattr(semantic, "_structural_index", tracked_structural)

    run_semantic(tmp_path, "index", backend="structural")
    assert len(indexed_batches) == 1

    monkeypatch.setattr(semantic, "SEMANTIC_EXTRACTOR_VERSION", "99")

    indexed_batches.clear()
    rep = run_semantic(tmp_path, "index", backend="structural")
    assert rep.status == "success"
    assert len(indexed_batches) == 1, "Extractor version change must invalidate cache and rebuild"


def test_treesitter_backend_version_change_invalidates_cache(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.semantic import semantic_cache_fingerprint

    fp1 = semantic_cache_fingerprint("treesitter", backend_version="0.2.0")
    fp2 = semantic_cache_fingerprint("treesitter", backend_version="0.3.0")
    assert fp1 != fp2, "Different tree-sitter versions must produce different fingerprints"

    # Verify structural backend version is constant
    fp_struct1 = semantic_cache_fingerprint("structural")
    fp_struct2 = semantic_cache_fingerprint("structural")
    assert fp_struct1 == fp_struct2

    # Verify caching behavior when backend version changes
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    monkeypatch.setattr(semantic, "_backend_version", lambda b: "1.0.0")

    indexed_batches: list[list[str]] = []
    original_structural = semantic._structural_index

    def tracked_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        return original_structural(root, paths)

    monkeypatch.setattr(semantic, "_structural_index", tracked_structural)

    run_semantic(tmp_path, "index", backend="structural")
    assert len(indexed_batches) == 1

    # Simulate backend package upgrade
    monkeypatch.setattr(semantic, "_backend_version", lambda b: "2.0.0")
    indexed_batches.clear()
    rep = run_semantic(tmp_path, "index", backend="structural")
    assert rep.status == "success"
    assert len(indexed_batches) == 1, "Backend package upgrade must invalidate cache and rebuild"

