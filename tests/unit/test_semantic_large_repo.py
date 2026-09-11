from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools import semantic
from ai_dev_tools.semantic import (
    SEMANTIC_CACHE_PATH,
    SEMANTIC_INDEX_PATH,
    run_semantic,
)


def test_semantic_cache_under_10k_symbols(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)

    for i in range(2):
        funcs = "\n".join(f"def f_{i}_{j}(): pass" for j in range(5))
        (tmp_path / f"mod_{i}.py").write_text(funcs, encoding="utf-8")

    rep = run_semantic(tmp_path, "index", backend="structural")
    assert rep.status == "success"
    assert rep.summary["symbol_count"] == 10
    assert rep.summary["total_symbol_count"] == 10
    assert rep.summary["truncated"] is False

    index_data = json.loads((tmp_path / SEMANTIC_INDEX_PATH).read_text(encoding="utf-8"))
    assert len(index_data["symbols"]) == 10
    assert index_data["truncated"] is False

    cache_data = json.loads((tmp_path / SEMANTIC_CACHE_PATH).read_text(encoding="utf-8"))
    assert cache_data["total_symbols"] == 10
    assert len(cache_data["file_symbols"]) == 2


def test_semantic_cache_over_10k_symbols_allows_reuse(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)

    (tmp_path / "mod_a.py").write_text("# mod_a\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("# mod_b\n", encoding="utf-8")

    indexed_batches: list[list[str]] = []

    def mock_structural(root: Path, paths: list[Path]) -> list[dict[str, object]]:
        indexed_batches.append([p.name for p in paths])
        result: list[dict[str, object]] = []
        for p in paths:
            rel = p.relative_to(root).as_posix()
            prefix = "a" if "mod_a" in p.name else "b"
            for k in range(6000):
                result.append({
                    "path": rel,
                    "name": f"{prefix}_sym_{k}",
                    "kind": "function",
                    "start_line": k + 1,
                    "end_line": k + 2,
                    "backend": "structural",
                })
        return result

    monkeypatch.setattr(semantic, "_structural_index", mock_structural)

    # 1. Cold Run
    rep1 = run_semantic(tmp_path, "index", backend="structural")
    assert rep1.status == "partial"
    assert rep1.summary["truncated"] is True
    assert rep1.summary["symbol_count"] == 10_000
    assert rep1.summary["total_symbol_count"] == 12_000
    assert len(indexed_batches) == 1
    assert set(indexed_batches[0]) == {"mod_a.py", "mod_b.py"}

    index_data = json.loads((tmp_path / SEMANTIC_INDEX_PATH).read_text(encoding="utf-8"))
    assert len(index_data["symbols"]) == 10_000
    assert index_data["truncated"] is True
    assert index_data["total_symbol_count"] == 12_000

    cache_data = json.loads((tmp_path / SEMANTIC_CACHE_PATH).read_text(encoding="utf-8"))
    assert cache_data["total_symbols"] == 12_000
    assert len(cache_data["file_symbols"]["mod_a.py"]) == 6000
    assert len(cache_data["file_symbols"]["mod_b.py"]) == 6000

    # 2. Warm Run without changes -> MUST REUSE CACHE (0 files re-indexed!)
    indexed_batches.clear()
    rep2 = run_semantic(tmp_path, "index", backend="structural")
    assert rep2.status == "partial"
    assert rep2.summary["truncated"] is True
    assert rep2.summary["total_symbol_count"] == 12_000
    assert rep2.summary["symbol_count"] == 10_000
    assert len(indexed_batches) == 0

    # 3. Single file change (modify mod_b.py) -> ONLY mod_b.py re-indexed!
    (tmp_path / "mod_b.py").write_text("# mod_b modified\n", encoding="utf-8")
    indexed_batches.clear()
    rep3 = run_semantic(tmp_path, "index", backend="structural")
    assert rep3.status == "partial"
    assert len(indexed_batches) == 1
    assert indexed_batches[0] == ["mod_b.py"]

    # 4. Add mod_c.py with 1000 symbols
    (tmp_path / "mod_c.py").write_text("# mod_c\n", encoding="utf-8")
    indexed_batches.clear()
    run_semantic(tmp_path, "index", backend="structural")
    assert len(indexed_batches) == 1
    assert indexed_batches[0] == ["mod_c.py"]

    # 5. Delete mod_a.py
    (tmp_path / "mod_a.py").unlink()
    indexed_batches.clear()
    run_semantic(tmp_path, "index", backend="structural")
    assert len(indexed_batches) == 0
    cache_after_delete = json.loads((tmp_path / SEMANTIC_CACHE_PATH).read_text(encoding="utf-8"))
    assert "mod_a.py" not in cache_after_delete["file_symbols"]

    # 6. Forced rebuild -> all files re-indexed!
    indexed_batches.clear()
    run_semantic(tmp_path, "index", backend="structural", rebuild=True)
    assert len(indexed_batches) == 1
    assert set(indexed_batches[0]) == {"mod_b.py", "mod_c.py"}


def test_semantic_indexing_over_2000_files(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)

    # Generate 2,050 files (exceeds previous 2,000 artificial cap)
    file_count = 2050
    content = "def sample():\n    return 42\n"
    for i in range(file_count):
        (tmp_path / f"mod_{i:04d}.py").write_text(content, encoding="utf-8")

    # 1. Cold Run
    rep = run_semantic(tmp_path, "index", backend="structural")
    assert rep.status == "success"
    assert rep.summary["files_total"] == file_count
    assert rep.summary["files_indexed"] == file_count
    assert rep.summary["files_omitted"] == 0
    assert rep.summary["total_symbol_count"] == file_count

    cache_data = json.loads((tmp_path / SEMANTIC_CACHE_PATH).read_text(encoding="utf-8"))
    assert cache_data["total_symbols"] == file_count
    assert len(cache_data["file_symbols"]) == file_count

    # Verify file index 2000 and 2049 are genuinely parsed and NOT cached as empty
    assert "mod_2000.py" in cache_data["file_symbols"]
    assert len(cache_data["file_symbols"]["mod_2000.py"]) == 1
    assert cache_data["file_symbols"]["mod_2000.py"][0]["name"] == "sample"

    assert "mod_2049.py" in cache_data["file_symbols"]
    assert len(cache_data["file_symbols"]["mod_2049.py"]) == 1

    # 2. Warm Run -> 100% reused, 0 reindexed
    rep_warm = run_semantic(tmp_path, "index", backend="structural")
    assert rep_warm.status == "success"
    assert rep_warm.summary["files_total"] == file_count
    assert rep_warm.summary["files_indexed"] == 0
    assert rep_warm.summary["files_reused"] == file_count
    assert rep_warm.summary["files_omitted"] == 0


def test_semantic_warm_no_op_write_avoidance(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)

    (tmp_path / "mod_1.py").write_text("def a(): pass\n", encoding="utf-8")
    (tmp_path / "mod_2.py").write_text("def b(): pass\n", encoding="utf-8")

    rep1 = run_semantic(tmp_path, "index", backend="structural")
    assert rep1.status == "success"

    cache_file = tmp_path / SEMANTIC_CACHE_PATH
    index_file = tmp_path / SEMANTIC_INDEX_PATH
    assert cache_file.exists()
    assert index_file.exists()

    cache_mtime_before = cache_file.stat().st_mtime_ns
    index_mtime_before = index_file.stat().st_mtime_ns

    # Warm run with 0 changes -> must NOT rewrite JSON files!
    rep2 = run_semantic(tmp_path, "index", backend="structural")
    assert rep2.status == "success"
    assert rep2.summary["files_indexed"] == 0

    assert cache_file.stat().st_mtime_ns == cache_mtime_before, (
        "Cache file must not be rewritten on no-op warm run"
    )
    assert index_file.stat().st_mtime_ns == index_mtime_before, (
        "Index file must not be rewritten on no-op warm run"
    )

