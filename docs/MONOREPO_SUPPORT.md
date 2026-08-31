# Monorepo Support

Version 1.0.0 includes workspace detection, ownership, and isolated per-subproject routing for
checks and bootstrap commands.

## Status

- Monorepo/workspace detection and per-subproject command routing: implemented.
- Per-subproject check and bootstrap working directories: implemented.
- Incrementally reused import and related-test impact edges: implemented.
- Runtime requirement detection for Python, Node.js, Java, Rust, and PHP: implemented, with
  conservative warnings when a requirement cannot be evaluated.

Current behavior:

- `scan` reports repository and workspace-level technology signals.
- `check --mode changed --explain` exposes workspace ownership, the changed-file strategy, and
  selected checks before execution.
- Configuration changes such as `package.json`, `pnpm-workspace.yaml`, `Cargo.toml`, `pom.xml`,
  `settings.gradle`, and test fixture files trigger a broader safe plan.
- Mixed Python, Node.js, and Rust fixtures are exercised from paths containing spaces and Unicode
  across Linux, Windows, and macOS.

Broader language-specific symbol extraction and richer ecosystem-specific dependency edges remain
planned. Low-confidence ownership or impact analysis must continue to broaden validation rather
than silently omit potentially affected workspaces.
