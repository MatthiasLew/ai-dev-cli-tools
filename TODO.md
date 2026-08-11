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
- [x] Add mixed-language monorepo fixtures and integration tests for Windows and POSIX paths.

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
- [x] Test signal and process handling on Linux, macOS, and Windows.

### Validation reliability

- [x] Add end-to-end fixture projects whose real toolchains can be executed in CI, not only
  detected or parsed from saved logs.
- [x] Test failure, timeout, missing executable, malformed output, and partial-log paths for
  every supported runner family.
- [x] Add schema contract tests that reject accidental breaking changes to JSON reports.
- [x] Define confidence levels for affected-test selection and make fallback behavior part of
  the public report schema.
- [x] Add explicit tests for filenames containing spaces, Unicode, renames, deletions, and
  non-UTF-8 tool output.

## P2 — Improve agent efficiency and maintainability

- [x] Add incremental context manifests that emit changed candidates and reference reused files.
- [x] Add content-addressed validation caching with exact command, workspace, repository,
  platform, and runtime fingerprints.
- [x] Add stable failure signatures to validation reports.
- [x] Add Python AST-aware context snippets with symbol names, kinds, line ranges,
  selection reasons, local references, and conservative fallback.
- [x] Add conservative JavaScript/TypeScript top-level symbol selection for functions,
  classes, interfaces, types, enums, namespaces, and arrow functions, with task matching,
  local-reference metadata, secret masking, bounded imports, and safe file-prefix fallback.
- [x] Continue the remaining high-priority features from
  `docs/AGENT_EFFICIENCY_ROADMAP.md`, starting with progressive report expansion and
  baseline-aware reports.
- [x] Split the large `context.builder`, `runners.check`, and `runners.bootstrap` modules into
  small strategy and orchestration modules with stable interfaces.
- [x] Replace hard-coded parser selection with a parser registry and documented extension API.
- [x] Add parser fixtures for warnings, multiple simultaneous failures, localized output, and
  new tool versions.
- [x] Add bounded cache storage under `.ai/cache/` with schema versions, fingerprints,
  explicit invalidation rules, pruning, and local diagnostics.
- [x] Add configurable context profiles such as `minimal`, `debug`, `review`, and `full`.
- [x] Add machine-readable reason codes wherever reports currently expose only prose.
- [x] Ensure secret masking is applied consistently to snippets, diffs, command output,
  environment diagnostics, and generated reports.
- [x] Add tests proving that blocked files, private keys, tokens, and `.env` values never enter
  context artifacts in clear text.

- [x] Add a local MCP STDIO server with focused tools for project status, feedback,
  bounded context, validation, and evidence expansion; default potentially expensive
  operations to preview-only and document Codex configuration.
- [x] Add symbol-level working-tree diffs for Python and JavaScript/TypeScript with changed
  signatures, line counts, risk, related tests, conservative fallbacks, and compact review or
  minimal context output.
- [x] Add local multi-agent task coordination with atomic state, expiring claim leases,
  dependency gates, declared-path conflict detection, CLI/MCP operations, and stable reason codes.
- [x] Add conservative Java, Rust, and PHP symbol adapters to bounded context selection and
  symbol-level diffs, with task matching, local references, and safe parse fallback.

## P3 — Distribution and ecosystem

- [x] Decide whether the package will be published to PyPI and document the supported install
  and upgrade path.
- [x] Add shell completion for Bash, Zsh, Fish, and PowerShell if it can be done without adding
  heavy runtime dependencies.
- [x] Document a stable integration contract for coding agents and editor extensions.
- [x] Provide example integrations that consume JSON reports without parsing Markdown.
- [x] Add a local-only diagnostics command for cache size, report retention, and configuration
  provenance.
- [x] Add opt-in bounded flaky retries, deterministic-failure exclusions, preserved first
  failures, non-cacheable flaky passes, and bounded local test history.
- [x] Add revalidated warm environment state, bootstrap --if-needed, and environment explain
  without retaining secrets or silently trusting changed tools and dependency inputs.
- [x] Add foreground watch mode with ignored generated roots, debounced change coalescing,
  changed validation, queued changes, bounded automation, and latest-result reports.
- [x] Add reproducible local A/B workflow benchmarks with versioned fixtures, correctness
  validation, repeated cold/warm trials, machine-readable results, and compact comparisons,
  including real repair, affected-test, multi-turn, and monorepo-routing scenarios.
- [x] Evaluate opt-in, local metrics that estimate context size and tokens avoided without
  transmitting repository contents.
- [x] Add local stage timing records, configurable performance budgets, bounded retention, and
  `performance latest/compare` regression diagnostics for scan, check explain, and incremental
  context creation.

## Research-backed next improvements

The supporting evidence, trade-offs, and source links are documented in
`docs/TOKEN_EFFICIENCY_RESEARCH.md`.

- [x] Add an explainable selective-retrieval gate that can abstain from cross-file retrieval,
  preserves conservative fallback behavior, and measures selection false negatives.
- [x] Add an observation lifecycle that replaces superseded tool output with stable evidence
  references while retaining current failures and final verification.
- [x] Add a deterministic cache-layout manifest with stable-prefix fingerprints and recommended
  provider cache breakpoints, without embedding volatile timestamps or absolute paths.
- [ ] Add optional exact tokenizer/provider usage accounting and separate budgets for source,
  diffs, tests, logs, maps, history, cached input, and output.
- [ ] Add bounded hierarchical retrieval refinement driven by failure signatures, changed symbols,
  and explicit evidence expansion.
- [ ] Evaluate optional semantic compression only for prose and repetitive natural-language logs;
  preserve exact code, JSON, diffs, commands, locations, hashes, and verification evidence.

## Deferred or explicitly out of scope

The following must not be added implicitly as part of another task. They require a separate
design and safety review:

- automatic commit, push, merge, release, or deployment;
- destructive Git cleanup or repository reset;
- sending source code, logs, metrics, or secrets to a remote AI service;
- killing arbitrary processes or deleting user-managed runtime data;
- silently installing global tools or changing machine-level configuration.
