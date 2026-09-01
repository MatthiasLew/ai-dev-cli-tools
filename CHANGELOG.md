# Changelog

## Unreleased

- Make benchmark corpus and comparison evidence IDs resolvable through `ai-dev explain`.
- Make index-daemon state writes resilient to transient Windows sharing violations and count
  repository updates only when the indexed content fingerprint actually changes.
- Add explicit MCP `build_context` acknowledgements: clients can return `acknowledged_state` to
  receive a compact unchanged-context receipt, while changed, partial, or unsafe states retain
  the full live payload. `delta=false` always requests full context.
- Add deterministic adaptive context budgets and task-scoped incremental memory for agent turns.
- Require a configurable minimum token reduction in A/B release corpus gates.
- Add client-acknowledged feedback deltas that replace repeated successful validation and context
  with fingerprinted receipts while retaining failures and warnings live.

## 1.1.0 - 2026-08-31

Stable promotion of `1.1.0rc1` after cross-platform CI, benchmark regression gates, and a clean
TestPyPI installation smoke test.

- Add `plan` and MCP `plan_work` for bounded, preview-only implementation plans with scope,
  dependencies, validation, risk, policy assessments, and stable evidence references.
- Add built-in Tree-sitter AST and LSP document-symbol backends alongside the local structural
  fallback and semantic plugin contract.
- Add a detached, localhost-authenticated index daemon using native filesystem events, IPC
  start/status/stop control, lifecycle state, and no periodic repository rescans.
- Classify command failures and retry only transient infrastructure failures while preserving the
  first failure and recovery evidence.
- Add configurable command allow/deny prefixes and impact limits, enforced by checks, bootstrap,
  and application startup, plus a preview-only `policy assess` command.
- Extend reproducible benchmarks with precision, recall, false negatives, iterations, files read,
  reported token metrics, a versioned real-agent corpus, and enforceable regression gates.
- Add ready project-scoped MCP configurations for Codex, Claude Code, Cursor, and generic clients.
- Add a loopback-only local dashboard for index, semantic, cache, runtime, daemon, and error health.
- Add deterministic report-to-SARIF conversion and a GitHub Actions code-scanning summary job.
- Upgrade and SHA-pin supported GitHub Actions used by CI, docs, and publishing workflows.

## 1.0.0 - 2026-08-31

- Stabilize the local CLI and report schema for the 1.0 release line.
- Add deterministic `implement` and `docs` context profiles with contract-tested budgets.
- Add project-scoped `explain --symbol PATH#QUALIFIED_SYMBOL` with bounded content and related tests.
- Add configuration ownership, generated-source relationships, reverse-dependent traversal, and
  bounded reason paths to the impact graph.
- Add nested Java/PHP owner qualification and overload-safe Java member identities.
- Add dependency-aware, resource-bounded check scheduling with deterministic report order.
- Safely cancel only subprocesses owned by obsolete watch validations while retaining their logs.
- Add a pinned development-tool baseline and disable unrelated globally installed pytest-qt hooks.
- Add an end-to-end regression for ignored virtual environments, CP1250 output, and non-zero check
  result status consistency.
- Add retained historical incremental context manifests and `context build --since <context-id>`.
- Add direct named baseline regression checks through `check --compare` and
  `context build --compare`.
- Add bounded shortest reason paths for changed-file, related-test, symbol, and check selection.
- Exclude `env` and `venv` dependency trees from workspace discovery, make text reports safe on
  legacy Windows console encodings, and keep non-zero check results from reporting success.
- Add explainable `auto|always|never` selective retrieval with conservative fallback and related-test false-negative measurement.
- Add a local observation lifecycle that replaces superseded feedback with expandable content-addressed evidence while retaining current failures, warnings, and final verification.
- Add a relocatable deterministic prompt-cache layout manifest with stable-prefix fingerprints and OpenAI, Anthropic, and provider-neutral breakpoint recommendations.
- Add optional exact tiktoken accounting, provider usage normalization, and enforced per-category token budgets for context packs.
- Add bounded multi-round context refinement driven by failures, changed symbols, dependencies, and expandable evidence.
- Add opt-in deterministic prose/log deduplication with fail-closed protected-evidence fingerprints.
- Add owner-qualified Java/PHP methods and Rust impl/trait functions, Java constructor detection,
  and correct global PHP function classification.
- Replace the completed historical backlog with an active backlog and mark every roadmap capability
  as implemented or partial against the supported CLI.

- Document research-backed selective retrieval, prompt-cache layout, observation lifecycle, token accounting, and safe compression priorities.
- Add local stage timing records, configurable performance budgets, and latest/compare diagnostics.
- Add versioned real-agent benchmark fixtures for repair, affected tests, multi-turn context, and monorepo routing, with private measured workflow telemetry and published raw trials.
- Add a dependency-free local MCP STDIO server with focused, bounded project tools.
- Add symbol-level Python and JavaScript/TypeScript working-tree diffs with compact review contexts.
- Add local multi-agent task coordination with expiring leases and path-conflict detection.
- Add conservative Java, Rust, and PHP adapters for context selection and symbol-level diffs.

- Add task-aware JavaScript/TypeScript top-level symbol selection for bounded context packs.
- Correct capabilities metadata for flaky retries and completed cross-platform CI.

- Add reproducible, correctness-gated local A/B workflow benchmarks and comparison reports.
- Add foreground watch mode with debounced changed validation and latest-result reports.
- Add revalidated warm environment state and bootstrap --if-needed.
- Add opt-in bounded flaky retries with preserved first failures and local history.

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
