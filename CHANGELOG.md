# Changelog

## Unreleased

- Add reproducible, correctness-gated local A/B workflow benchmarks and comparison reports.
- Add foreground watch mode with debounced changed validation and latest-result reports.

## 0.5.0a1 - 2026-08-10

- Add workspace models and isolated check/bootstrap routing for mixed monorepos.
- Add cross-platform mixed-monorepo and Git path fixtures covering spaces, Unicode, rename, deletion, and non-UTF-8 output.
- Add runner failure matrices and real Python, Node, Rust, Maven, Gradle, and Composer fixture execution in CI.
- Detect and validate Python, Node.js, Java, Rust, and PHP runtime requirements.
- Implement safe managed `run` and `stop` with supervisor-owned process termination.
- Add HTTP/TCP readiness probes, bounded startup logs, and readiness-timeout cleanup.
- Add bounded parallel check execution with `--jobs`.
- Add a versioned repository index and content-addressed validation cache with bounded retention.
- Add incremental context manifests and `context build --incremental`.
- Add AST-aware Python symbol snippets for large context files.
- Add minimal, debug, review, and full context profiles.
- Add local diagnostics, efficiency estimates, a stable agent contract, and JSON integration example.
- Add dependency-free completion generators for Bash, Zsh, Fish, and PowerShell.
- Add stable failure signatures and a machine-readable report JSON Schema.
- Add an extensible tool-output parser registry with deterministic precedence.
- Add compatibility fixtures and prevent cross-line test-count overcounting.
- Apply defense-in-depth secret masking to command logs, diagnostics, runtime streams, and report writers.
- Raise and enforce the coverage threshold to 90%.
- Add agent-efficiency and execution TODO roadmaps.

## 0.4.0

- Add `ai-dev bootstrap` with safe explain, dry-run, and execution modes.
- Support bootstrap strategies for Python, Node.js, Maven, Gradle, Rust, and PHP.
- Add guarded `.env.example` to `.env` creation via `--create-env`.
- Add installed-wheel entrypoint smoke validation to local and CI standards.
- Keep cross-platform CI marked as externally blocked until GitHub Actions jobs actually run.
## 0.3.0

- Add `ai-dev context build` for bounded local AI context packages.
- Write `.ai/context/context-latest.md` and `.ai/context/context-latest.json` artifacts.
- Reuse scan, repository map, git inspect, changed-test selection, validation planning, and secret masking.
- Keep monorepo detection experimental, per-subproject runner isolation planned, and runtime validation partial.
## 0.2.0

- Add schema 1.1 reports with exit codes and metadata.
- Add tool-specific output parser layer with fixtures for Python, JavaScript, Java, Rust, and PHP logs.
- Add `ai-dev capabilities` and `ai-dev check --explain`.
- Add `logs summarize <path> --tool auto|name` with a 50 MB input limit.
- Improve changed-file strategies with configuration-change and changed-test-direct reporting.
- Prepare package version 0.2.0 without creating a release.

## 0.1.0

- Initial private foundation for cross-platform AI development CLI helpers.
