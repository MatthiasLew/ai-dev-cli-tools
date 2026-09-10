# Performance Baseline Report — 2026-09-10

## Environment Profile

- **Operating System**: Microsoft Windows 11 Pro (Windows NT 10.0; Win64; x64)
- **CPU**: 12th Gen Intel(R) Core(TM) i5-1235U (10 cores, 12 logical processors)
- **RAM**: 16.0 GB
- **Python Version**: Python 3.14.0 (CPython 64-bit)
- **Git Version**: git version 2.55.0.windows.3
- **Repository Commit**: `bfefc8edf8da07f54e68fe76c5b41be0c28a53a6` (clean working tree)
- **Cargo / Rust**: Not installed in environment (`missing`)

## Pre-Optimization Test Suite Status

- **Unit & Integration Tests (`pytest`)**: 100% pass (538 passed, 7 skipped)
- **Linter (`ruff`)**: Pass (0 errors)
- **Type Checker (`mypy`)**: Pass (0 errors across 163 source files)

---

## Baseline Latency Metrics

Measurements conducted on the local repository. Cold numbers represent first invocation; warm numbers represent statistics across 10 sequential trials.

| Command | Cold Latency (s) | Warm Median (s) | Warm Min (s) | Warm Max (s) | Warm StdDev (s) | Internal Command Duration (s) |
|---|---:|---:|---:|---:|---:|---:|
| `ai-dev scan` | 0.3192 | 0.2525 | 0.2365 | 0.2701 | 0.0105 | 0.108 |
| `ai-dev git status` | 0.5235 | 0.5483 | 0.5210 | 0.7094 | 0.0721 | 0.363 |
| `ai-dev git inspect` | 0.8524 | 0.8436 | 0.8220 | 0.9131 | 0.0326 | 0.745 |
| `ai-dev index update` | 0.4040 | 0.2794 | 0.2500 | 0.4722 | 0.0721 | 0.132 |
| `ai-dev context build --incremental` | 8.5087 | 5.6776 | 4.3975 | 6.8934 | 0.7463 | 5.239 |

---

## Identified Bottlenecks

1. **Git Subprocess Redundancy (`ai-dev git inspect`)**:
   - `git diff` is executed multiple times in detailed inspect mode (`diff_size_bytes` and `unstaged_diff_bytes`).
   - Multiple separate calls to `git diff`, `git diff --cached`, `git diff --stat`, `git status`, `git stash list`, `git rev-parse`. On Windows, each subprocess spawn has measurable overhead (~50-80ms per process).

2. **Duplicate File Reads in Impact Graph (`ai-dev context build` / `index update`)**:
   - `build_impact_graph` reads each source file once in `_references()` and again in `_generated_relationships()`.
   - On repositories with hundreds or thousands of files, this doubles filesystem I/O during graph calculation.

3. **Filesystem Traversal & Path Normalization Overhead (`repository.py`)**:
   - `_project_files()` calls `is_symlink()`, `.is_file()`, and `path.relative_to()`.
   - `update_repository_index()` calls `path.relative_to()` and `path.stat()` again for every file.
   - `_is_ignored_name()` iterates through all patterns using `fnmatch` for every single file and directory rather than using $O(1)$ set lookup for literal names.

4. **Concurrent Cache Writing Risk**:
   - `_write_json` uses a static `.tmp` filename suffix which can collide if multiple processes update the cache simultaneously.
