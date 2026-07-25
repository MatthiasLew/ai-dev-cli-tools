# Changelog

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
