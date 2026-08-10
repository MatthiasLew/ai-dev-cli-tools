# TODO

This file tracks concrete work that remains after version 0.4.0. It is intentionally
separate from the product ideas in `docs/AGENT_EFFICIENCY_ROADMAP.md`: this document is
the execution backlog, while the roadmap explains why future agent-oriented features
are valuable.

## Priority definitions

- **P0**: release correctness, safety, or documentation that currently contradicts the code.
- **P1**: the next core capabilities needed for dependable use across real repositories.
- **P2**: important scalability, maintainability, and agent-efficiency improvements.
- **P3**: useful integrations and user-experience improvements after the core is stable.

An item is complete only when implementation, tests, user documentation, JSON report
changes, and cross-platform behavior are covered where applicable.

## P0 — Align and stabilize the 0.4 baseline

- [x] Reconcile version and milestone statements across `README.md`, `CHANGELOG.md`,
  `docs/MONOREPO_SUPPORT.md`, `docs/CONTEXT_BUILDER.md`, and `docs/BOOTSTRAP.md`.
  Remove stale promises that assign unfinished work to versions 0.3.0 or earlier.
- [x] Choose one enforced coverage threshold. The contributor instructions currently use
  90%, while `pyproject.toml` and CI effectively use 85%.
- [x] Confirm that the full GitHub Actions matrix passes on Linux, Windows, and macOS with
  Python 3.11, 3.12, and 3.13. Record any known platform exception explicitly.
- [x] Add a release checklist covering version bumping, changelog updates, wheel validation,
  report-schema compatibility, and clean-install smoke tests.
- [x] Decide whether generated context artifacts under `.ai/context/` should be ignored by
  default and document their retention policy.
- [x] Make every command that writes a report include those report paths in its returned
  `artifacts` collection, including `finish`.

## P1 — Complete the core workflow

### Monorepo and workspace execution

- [x] Introduce a `Workspace` model with root, technology, package manager, commands,
  configuration files, and changed-file ownership.
- [x] Detect npm, pnpm, Yarn, Cargo, Maven, Gradle, and mixed Python/Node workspaces.
- [x] Route checks and bootstrap steps to the owning subproject instead of executing every
  command from the repository root.
- [x] Deduplicate repository-wide checks while keeping subproject checks isolated.
- [x] Report which workspace selected each command and why.
- [ ] Add mixed-language monorepo fixtures and integration tests for Windows and POSIX paths.

### Runtime compatibility

- [x] Read runtime requirements from `pyproject.toml`, `.python-version`, `package.json`,
  `.nvmrc`, `engines`, Maven/Gradle configuration, `rust-toolchain.toml`, and Composer.
- [x] Distinguish missing runtime, unsupported version, and unknown version in `doctor`.
- [x] Include required and detected runtime versions in scan, bootstrap, check, and context
  reports.
- [x] Block modifying bootstrap steps when the detected runtime is known to be incompatible.

### Safe `run` and `stop`

- [x] Define non-destructive lifecycle semantics before implementing the reserved commands.
- [x] Resolve run commands from project configuration and detected entrypoints.
- [x] Store process metadata under `.ai/runtime/`; never terminate a process that was not
  started and positively identified by `ai-dev`.
- [x] Add foreground mode, bounded startup-log capture, readiness checks, timeout handling,
  stale metadata recovery, and clear exit statuses.
- [x] Provide `--explain` and `--dry-run` behavior before allowing background execution.
- [ ] Test signal and process handling on Linux, macOS, and Windows.

### Validation reliability

- [ ] Add end-to-end fixture projects whose real toolchains can be executed in CI, not only
  detected or parsed from saved logs.
- [ ] Test failure, timeout, missing executable, malformed output, and partial-log paths for
  every supported runner family.
- [x] Add schema contract tests that reject accidental breaking changes to JSON reports.
- [x] Define confidence levels for affected-test selection and make fallback behavior part of
  the public report schema.
- [ ] Add explicit tests for filenames containing spaces, Unicode, renames, deletions, and
  non-UTF-8 tool output.

## P2 — Improve agent efficiency and maintainability

- [x] Add incremental context manifests that emit changed candidates and reference reused files.
- [x] Add content-addressed validation caching with exact command, workspace, repository,
  platform, and runtime fingerprints.
- [x] Add stable failure signatures to validation reports.
- [x] Add Python AST-aware context snippets with symbol names, kinds, line ranges,
  selection reasons, local references, and conservative fallback.
- [ ] Continue the remaining high-priority features from
  `docs/AGENT_EFFICIENCY_ROADMAP.md`, starting with progressive report expansion and
  baseline-aware reports.
- [ ] Split the large `context.builder`, `runners.check`, and `runners.bootstrap` modules into
  small strategy and orchestration modules with stable interfaces.
- [x] Replace hard-coded parser selection with a parser registry and documented extension API.
- [x] Add parser fixtures for warnings, multiple simultaneous failures, localized output, and
  new tool versions.
- [x] Add bounded cache storage under `.ai/cache/` with schema versions, fingerprints,
  explicit invalidation rules, pruning, and local diagnostics.
- [x] Add configurable context profiles such as `minimal`, `debug`, `review`, and `full`.
- [ ] Add machine-readable reason codes wherever reports currently expose only prose.
- [x] Ensure secret masking is applied consistently to snippets, diffs, command output,
  environment diagnostics, and generated reports.
- [x] Add tests proving that blocked files, private keys, tokens, and `.env` values never enter
  context artifacts in clear text.

## P3 — Distribution and ecosystem

- [x] Decide whether the package will be published to PyPI and document the supported install
  and upgrade path.
- [x] Add shell completion for Bash, Zsh, Fish, and PowerShell if it can be done without adding
  heavy runtime dependencies.
- [x] Document a stable integration contract for coding agents and editor extensions.
- [x] Provide example integrations that consume JSON reports without parsing Markdown.
- [x] Add a local-only diagnostics command for cache size, report retention, and configuration
  provenance.
- [x] Evaluate opt-in, local metrics that estimate context size and tokens avoided without
  transmitting repository contents.

## Deferred or explicitly out of scope

The following must not be added implicitly as part of another task. They require a separate
design and safety review:

- automatic commit, push, merge, release, or deployment;
- destructive Git cleanup or repository reset;
- sending source code, logs, metrics, or secrets to a remote AI service;
- killing arbitrary processes or deleting user-managed runtime data;
- silently installing global tools or changing machine-level configuration.
