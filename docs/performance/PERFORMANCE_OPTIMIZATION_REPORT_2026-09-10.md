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
| **`ai-dev context build`** | Cold Execution | 8.5087 s | **4.7895 s** | **43.7% faster (-3.719 s)** |

---

## 5. Correctness & Security Validation

- **Test Suite**: 100% pass (540 passed, 7 skipped).
- **Static Type Checking**: `mypy` strict mode passes with 0 errors across 163 source files.
- **Linter**: `ruff` passes with 0 warnings or errors.
- **Cross-Platform & Multi-Process**: Unique temporary files eliminate race conditions on Windows and POSIX; paths remain deterministic POSIX format.

---

## 6. Rust Assessment Summary

As documented in `docs/performance/RUST_NATIVE_ACCELERATION_ASSESSMENT.md`, native Rust acceleration is currently **not justified**:
- Python-level I/O and subprocess optimizations delivered over **50% speedup** on repository index updates.
- Total command durations are now dominated by Git CLI operations and external tool execution, not Python CPU bottlenecks.
- Maintaining pure Python preserves zero-dependency cross-platform portability without compilation overhead.
