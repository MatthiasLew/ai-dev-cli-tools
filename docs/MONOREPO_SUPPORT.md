# Monorepo Support

Version 0.4.0 detects monorepo signals but does not yet fully isolate every workspace runner.

## Status

- Monorepo/workspace detection and per-subproject command routing: implemented.
- Per-subproject check and bootstrap working directories: implemented.
- Runtime version validation: partial and handled outside this monorepo routing layer.

This document does not claim full runner isolation between subprojects in v0.4.0.
Current behavior:

- `scan` reports project-level signals and can identify multiple technology signals in one repository.
- `check --mode changed --explain` exposes the changed-file strategy and selected checks before execution.
- Configuration changes such as `package.json`, `pnpm-workspace.yaml`, `Cargo.toml`, `pom.xml`, `settings.gradle`, and test fixture files trigger a broader plan.

Planned workspace-specific routing includes npm, pnpm, Yarn, Cargo workspace, Maven multi-module, Gradle multi-project, and mixed Python/Node repositories.

Mixed Python/Node/Rust fixtures are exercised from paths containing spaces and Unicode. The same integration test runs in the Linux, Windows, and macOS GitHub Actions matrix and verifies POSIX plus Windows-style workspace ownership paths.
