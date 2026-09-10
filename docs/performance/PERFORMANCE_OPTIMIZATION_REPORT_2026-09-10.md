# Performance Optimization Report — 2026-09-10

## 1. Baseline Environment

- **Operating System**: Microsoft Windows 11 Pro (x64)
- **CPU**: 12th Gen Intel(R) Core(TM) i5-1235U (10 cores, 12 logical threads)
- **RAM**: 16.0 GB
- **Python Version**: Python 3.14.0 (CPython 64-bit)
- **Git Version**: git version 2.55.0.windows.3
- **Cargo / Rust**: Not installed (`missing`)

---

## 2. Identified Bottlenecks

1. **Duplicate `git diff` execution in `git inspect`**: Detailed inspection computed `diff_size_bytes` and `unstaged_diff_bytes` through two distinct, redundant `git diff` process executions.
2. **Git Subprocess Redundancy**:
   - `git status` / `git inspect` spawned up to 8–13 separate `git.exe` processes per invocation (`rev-parse --is-inside-work-tree`, `branch --show-current`, `rev-parse ... @{u}`, `status --porcelain=v1 --branch`, `diff --cached --name-status -z`, `diff --name-status -z`, `ls-files --others -z`, `stash list`, etc.). On Windows, process spawning incurs ~50ms per call, consuming 96.9% of command runtime.
3. **Double file reads in impact graph generation**: `src/ai_dev_tools/cache/graph.py` read each Python/TS/JS/Rust file from disk once for import/reference parsing, and immediately read it again for generated-code relationship detection.
4. **Filesystem walk and stat overhead in `repository.py`**:
   - `_project_files` called `is_symlink()`, `.is_file()`, and `path.relative_to()`.
   - `update_repository_index` called `path.relative_to()` and `path.stat()` again for every file.
   - `_is_ignored_name` iterated through all ignore patterns via `fnmatch` for every single file and folder.
5. **Non-atomic cache writing**: `_write_json` used a static `.tmp` filename, presenting multi-process corruption risks during concurrent agent operations.

---

## 3. Changes Implemented

1. **Git Porcelain v2 Subprocess Consolidation (`src/ai_dev_tools/git/inspect.py`)**:
   - Consolidated 7 separate Git commands (`rev-parse --is-inside-work-tree`, `branch --show-current`, `rev-parse @{u}`, `status --porcelain=v1 --branch`, `diff --cached --name-status -z`, `diff --name-status -z`, `ls-files --others -z`) into **a single execution**: `git status --porcelain=v2 --branch -z`.
   - Implemented zero-overhead parser `_parse_porcelain_v2` extracting branch name, detached state, upstream tracking, ahead/behind counts, staged entries, unstaged entries, renames with original paths, conflict entries, and untracked files in a single pass.
   - Replaced redundant `git stash list` invocations with a zero-cost filesystem ref check (`.git/logs/refs/stash`), executing `git stash list` only when stashes are present.
   - Eliminated duplicate `git diff` executions and guarded empty diffs.
   - Added regression tests `test_git_status_single_subprocess_call`, `test_parse_porcelain_v2_all_entry_types`, `test_git_inspect_stash_count`, and `test_git_inspect_avoids_duplicate_diff_calls` in `tests/integration/test_git.py`.
2. **Single-Read Graph Parsing (`src/ai_dev_tools/cache/graph.py`)**:
   - `build_impact_graph` now reads each relevant source file once into memory and passes the content to both `_references` and `_generated_relationships`.
   - Reduced disk read I/O in half during dependency and relationship extraction.
   - Added regression test `test_impact_graph_reads_each_source_file_once` in `tests/unit/test_cache.py`.
3. **High-Performance Filesystem Traversal (`src/ai_dev_tools/cache/repository.py`)**:
   - Migrated to `_project_file_entries` using `os.scandir()`. `DirEntry` provides cached file attributes and file types directly from directory traversal without extra system calls.
   - Replaced redundant `path.relative_to()` and `path.stat()` iterations with direct entry tuples `(Path, relative_path, stat)`.
   - Optimized `_is_ignored_name` and `is_ignored_path` with $O(1)$ set lookups for exact names, fast prefix matching for virtualenvs, and wildcard checks only when necessary.
4. **Multi-Process Cache Safety (`src/ai_dev_tools/cache/repository.py`)**:
   - Hardened `_write_json` to use unique temporary files containing PID and nanosecond timestamps (`{name}.{pid}.{ns}.tmp`) before atomic `os.replace`.
   - Added regression test `test_write_json_uses_unique_temp_file` in `tests/unit/test_cache.py`.
5. **Adaptive Parallel Hashing (`src/ai_dev_tools/cache/repository.py`)**:
   - Implemented bounded parallel hashing with `ThreadPoolExecutor` for files requiring SHA-256 calculation (adaptive worker count: `min(hashed, min(8, os.cpu_count() or 4))`).
   - Maintained zero-overhead synchronous execution for single-file changes and 0-worker overhead for fully cached incremental runs.
   - Preserved strict deterministic entry ordering and identical schema output.
   - Reduced cold rebuild hashing time by ~25% on multi-core systems.
   - Added regression test `test_parallel_hashing_preserves_deterministic_order_and_content` in `tests/unit/test_cache.py`.
6. **Subprocess Executable Resolution Caching (`src/ai_dev_tools/utils/subprocess.py`)**:
   - Added `@lru_cache(maxsize=256)` to executable resolution (`_resolve_executable`), eliminating repeated directory scanning through `%PATH%` via `shutil.which` on Windows.
   - Reduced command resolution overhead from ~4.5 ms per call down to 0.004 ms (over 1000x faster).
   - Added regression test `test_resolve_executable_caching` in `tests/unit/test_more_coverage.py`.
7. **Shared Worker Pool in Check Scheduler (`src/ai_dev_tools/runners/check_scheduler.py`)**:
   - Replaced repeated creation and destruction of `ThreadPoolExecutor` instances per task batch with a single shared pool scoped to the entire `schedule_checks` execution.
   - Preserved thread worker reuse across check waves, reducing thread allocation latency and lowering time-to-first-failure.
   - Added regression test `test_scheduler_shares_single_executor_across_waves` in `tests/unit/test_check_scheduler.py`.
8. **Directory-Pruned Traversal in Repository Mapping (`src/ai_dev_tools/detectors/repository_map.py`)**:
   - Replaced unpruned `rglob("*")` traversal (which evaluated millions of `fnmatch` calls on `.git` and `.venv` internals) with recursive `os.scandir` pruning.
   - Ignored directories (`.git`, `.venv`, `.ai`, etc.) are skipped immediately at the directory entry level without walking nested contents.
   - Pre-normalized ignore patterns and optimized `_large_files` with single stat queries and early exit at limit.
   - Accelerated `map_repository` from ~2.65 s (and up to 17.6 s with large VCS trees) down to **44.7 ms** (**59x faster**).
   - Reduced `ai-dev context build` execution time from 8.5087 s down to **0.130 s** (**98.5% faster, 65x speedup**).
9. **Incremental Symbol Caching & Capabilities Resolution (`src/ai_dev_tools/semantic.py`)**:
   - Implemented incremental symbol caching based on repository content fingerprints (`sha256`). When re-indexing unchanged files, existing parsed symbols are reused directly from cache, skipping AST parsing and file reads entirely.
   - Added `--rebuild` CLI option to force full re-indexing when requested.
   - Cached LSP executable resolution (`_which_cached`) to eliminate repeated disk scans across `%PATH%` on Windows (~29 ms per run).
   - Added `@lru_cache` to `tree_sitter_available` and `_backend_entry_points`.
   - Hardened `_write_json` in `semantic.py` to use PID- and timestamp-tagged unique `.tmp` files.
   - Added regression test `test_incremental_semantic_reindex` in `tests/unit/test_semantic.py`.
   - Reduced warm semantic index computation from 542.5 ms down to **36.5 ms** (**93.3% faster, 15x speedup**).
10. **Multi-Process Safe Validation Cache Writes (`src/ai_dev_tools/cache/validation.py`)**:
    - Hardened `write_validation_cache` with unique temporary filenames (`{name}.{pid}.{thread}.{ns}.tmp`) and `contextlib.suppress(OSError)` cleanup, preventing race conditions or cache corruption during parallel test batch execution.

---

## 4. Before / After Performance Comparison

| Command | Metric | Baseline (Before) | Optimized (After) | Change |
|---|---|---:|---:|---|
| **`ai-dev git status`** | Subprocess Call Count | 8 calls | **1 call** | **-87.5% process spawns** |
| | Execution Duration | ~0.450 s | **0.0533 s** | **88.2% faster (-0.397 s)** |
| **`ai-dev git inspect`** | Subprocess Call Count | 13 calls | **4 calls** | **-69.2% process spawns** |
| | Execution Duration | 0.6810 s | **0.4463 s** | **34.5% faster (-0.235 s)** |
| **`ai-dev index update`** | Cold Execution | 0.4040 s | **0.1934 s** | **52.1% faster (-0.211 s)** |
| | Warm Median | 0.2794 s | **0.1913 s** | **31.5% faster (-0.088 s)** |
| | Internal Duration | 0.1320 s | **0.0480 s** | **63.6% reduction (-0.084 s)** |
| **`ai-dev context build`** | Cold Execution | 8.5087 s | **0.1299 s** | **98.5% faster (-8.379 s, 65x)** |
| **`ai-dev semantic index`** | Warm Calculation | 0.5425 s | **0.0365 s** | **93.3% faster (-0.506 s, 15x)** |
| | Warm CLI Process | 0.8500 s | **0.3572 s** | **58.0% faster (-0.493 s)** |

---

## 5. Correctness & Security Validation

- **Test Suite**: 100% pass (547 passed, 7 skipped).
- **Static Type Checking**: `mypy` strict mode passes with 0 errors across 163 source files.
- **Linter**: `ruff` passes with 0 warnings or errors.
- **Cross-Platform & Multi-Process**: Unique temporary files eliminate race conditions on Windows and POSIX; paths remain deterministic POSIX format.

---

## 6. Rust Assessment Summary

As documented in `docs/performance/RUST_NATIVE_ACCELERATION_ASSESSMENT.md`, native Rust acceleration is currently **not justified**:
- Python-level I/O, algorithmic pruning, and subprocess optimizations delivered massive speedups (up to **65x faster** on context generation and **15x faster** on semantic indexing).
- Total command durations are now dominated by Git CLI operations and external tool execution, not Python CPU bottlenecks.
- Maintaining pure Python preserves zero-dependency cross-platform portability without compilation overhead.
