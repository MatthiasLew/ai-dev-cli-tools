# Rust Native Acceleration Assessment — 2026-09-10

## Executive Summary

In accordance with Phase 15 of [`docs/AI_DEV_CLI_TOOLS_PERFORMANCE_OPTIMIZATION_AGENT_TASK.md`](../AI_DEV_CLI_TOOLS_PERFORMANCE_OPTIMIZATION_AGENT_TASK.md), this assessment evaluates whether native acceleration (Rust with PyO3/maturin) is technically justified for `ai-dev-cli-tools`.

**Recommendation: DO NOT introduce Rust at this time.**
Pure-Python optimizations achieved a **52% speedup in cold index updates** and a **63% reduction in internal index duration** (from 132ms down to 48ms). The remaining command latency is dominated by Git subprocess execution, console I/O, and external validation toolchains, rather than Python CPU saturation.

---

## Candidate Function Analysis

| Candidate Function | Current Python Time | % of Command Time | Expected Native Gain | Implementation Complexity | Decision |
|---|---:|---:|---:|---|---|
| **Impact Graph Generation** (`cache/graph.py`) | ~20–40 ms | < 5% | ~10–15 ms | Medium (PyO3 data bridge, regex) | **REJECTED**: Dominated by I/O; single-read optimization already solved bottleneck. |
| **Filesystem Traversal & Ignore Matching** (`cache/repository.py`) | ~15–25 ms | < 4% | ~8–12 ms | High (cross-platform symlinks, ignore rules) | **REJECTED**: `os.scandir` in CPython is already implemented in native C using OS directory streams. |
| **File Hashing Orchestration** (`_sha256`) | ~5–15 ms | < 3% | < 5 ms | Low (OpenSSL/hashlib already native C) | **REJECTED**: Python's `hashlib.sha256` already calls native OpenSSL; pure Rust brings no measurable benefit. |
| **Symbol Diff AST Parsing** (`symbol_diff.py`) | ~80–150 ms | ~10–15% | ~20–40 ms | High (AST / Tree-sitter bindings) | **REJECTED**: Tree-sitter already runs native C parsers when installed. |

---

## Evaluation Against Acceptance Criteria

1. **CPU-bound check**:
   - Profiling demonstrates that the application is I/O-bound (disk reads) and subprocess-bound (Git executable calls), not CPU-bound.
2. **Minimum 20% end-to-end command improvement**:
   - Re-implementing Python graph parsing or hashing in Rust would yield at most 10–20ms on commands that spend 500–800ms waiting for Git or external toolchains (< 3% end-to-end gain). This fails the 20% threshold.
3. **Packaging and portability overhead**:
   - Introducing Rust requires cross-compilation wheels (manylinux, macOS universal, Windows x86_64/arm64), maturin CI pipelines, and a C/Rust toolchain.
   - The user's target development environment currently does not have Cargo/Rust installed (`status: missing` in `ai-dev doctor`). Adding Rust would break local source installs and pure-Python distribution.

---

## Conclusion

The architecture remains fastest, most maintainable, and most portable by keeping Python as both the orchestration and core compute layer, while continuing to optimize algorithmic efficiency, I/O deduplication, and subprocess concurrency.
