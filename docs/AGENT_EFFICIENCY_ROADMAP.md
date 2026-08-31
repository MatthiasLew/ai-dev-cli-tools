# Agent Efficiency Roadmap

## Purpose

`ai-dev` reduces the repository state and tool output a coding agent must read while preserving
trustworthy evidence. Selection, caching, parsing, and ranking remain local and deterministic by
default. Uncertainty must broaden validation rather than silently omit relevant work.

Concrete unfinished work is tracked in `TODO.md`. This document records the current product status
and longer-term direction without presenting proposed interfaces as available commands.

## Status definitions

- **Implemented**: available through the documented CLI and covered by automated tests.
- **Partial**: a safe useful subset exists, but the target behavior still has explicit gaps.
- **Planned**: no supported implementation exists yet.
- **Out of scope**: intentionally excluded unless a separate design and safety review changes policy.

## Capability status

| # | Capability | Status | Current behavior and remaining gap |
|---|---|---|---|
| 1 | Incremental context packs | Implemented | `context build --incremental` compares with the latest schema-versioned manifest, while `--since <context-id>` selects a retained historical manifest. Reports identify changed/reused candidates and the explicit base context. |
| 2 | Symbol-aware source selection | Implemented | Python, JavaScript/TypeScript, Java, Rust, and PHP have bounded symbol selection and symbol-level diffs. Nested owners, Java overloads and constructors, PHP members, and Rust `impl`/trait functions receive stable qualified identities with conservative fallback. |
| 3 | Content-addressed validation cache | Implemented | Validation uses repository, command, workspace, runtime, platform, and configuration fingerprints. Cache reuse is default; `check --no-cache` bypasses it, while `cache status/prune/clear/layout` provides maintenance and diagnostics. |
| 4 | Failure signatures and deduplication | Implemented | Validation reports expose stable signatures, grouped repeated messages, representative failures, and expandable evidence. |
| 5 | Baseline-aware reports | Implemented | `baseline create/list/compare` stores and compares named local snapshots. `check --compare <name>` and `context build --compare <name>` apply the same regression contract directly to current reports. |
| 6 | Progressive report expansion | Implemented | Issues, checks, files, snippets, diffs, workspaces, and artifacts receive stable evidence IDs expandable with `explain <reference> --tail`; `explain --symbol PATH#SYMBOL` safely expands bounded project-local definitions and related tests. |
| 7 | Task-aware context profiles | Implemented | `minimal`, `debug`, `review`, `implement`, `docs`, and `full` profiles provide stable, explainable and contract-tested budgets. Explicit budget flags retain precedence. |
| 8 | Workspace-aware routing | Implemented | Workspace models route changed files, checks, bootstrap commands, runtime requirements, and ownership evidence across supported monorepos. |
| 9 | Dependency and impact graph | Implemented | The local graph reuses imports, reverse dependents, related tests, configuration ownership, and declared generated-source relationships. Changed selections expose bounded shortest reason paths through files, symbols, tests, and checks. |
| 10 | Failure-focused reruns | Implemented | Reports provide bounded focused rerun hints while preserving comprehensive final verification commands. |
| 11 | Compact agent protocol | Implemented | Schema 1.1 JSON reports, stable reason codes, evidence references, bounded output, and the local MCP server provide the supported machine contract. |
| 12 | Local session state | Implemented | Versioned local session and observation state retains task, validation, context, and unresolved failure evidence without storing a conversation transcript. |
| 13 | Dependency-aware parallel scheduler | Implemented | `check --jobs` respects explicit check dependencies, CPU/memory/exclusive resource classes, feedback-first gates, and deterministic report order. Failed dependencies conservatively cancel their dependents. |
| 14 | Persistent repository index | Implemented | `index status/update/rebuild` maintains a schema-versioned, content-addressed index under `.ai/cache/`; foreground `index daemon` keeps it warm with bounded polling and lifecycle state. |
| 15 | Watch mode | Implemented | Foreground polling, debounce, generated-root exclusion, queued changes, bounded runs, and cancellation of subprocesses owned by obsolete validations are implemented. Cancellation never targets an unrelated PID. |
| 16 | Priority and fail-fast scheduling | Implemented | `feedback-first` and `complete` policies provide deterministic priority waves and required-failure gating. |
| 17 | Warm environment state | Implemented | `bootstrap --if-needed` and `environment explain` reuse only revalidated executable, dependency, configuration, runtime, and plan fingerprints. |
| 18 | Checkpoint and resume | Implemented | `check --resume` reuses exact successful step fingerprints and rejects stale repository, command, runtime, or configuration state. |
| 19 | Flaky-test awareness | Implemented | Opt-in bounded retries preserve first failures, exclude deterministic/environment failures, avoid caching flaky passes, and maintain bounded local history. |
| 20 | Unified feedback command | Implemented | `feedback` composes Git changes, changed validation, incremental context, focused reruns, timings, observations, and session state. |
| 21 | Performance budgets | Implemented | Schema-versioned local timing records, total/per-stage budgets, bounded retention, and `performance latest/compare` diagnostics are available. |
| 22 | Reproducible workflow benchmarks | Implemented | Versioned local suites support repeated cold/warm trials, correctness gates, precision/recall and false-negative metrics, token/iteration/file telemetry, machine-readable results, and compact comparisons. |
| 23 | Agent execution plans | Implemented | `plan` and MCP `plan_work` emit preview-only scope, risk, dependencies, command-policy assessments, validation schedules, and stable evidence references. |
| 24 | Optional semantic providers | Implemented | A bounded local structural index is built in; explicitly selected entry-point providers can add Tree-sitter or LSP-backed semantics, while auto mode fails closed to structural parsing. |
| 25 | Execution policy | Implemented | Audit/enforce modes, allow/deny prefixes, impact ceilings, preview assessment, and enforcement cover checks, bootstrap, and managed application startup. |
| 26 | CI-native agent evidence | Implemented | Reports convert deterministically to SARIF and the pinned GitHub Actions workflow publishes a compact plan summary plus code-scanning evidence. |
| 27 | Adaptive context engine | Implemented | Task intent and local scope signals derive conservative token ceilings, explicit limits win, task-scoped incremental memory prevents cross-task omission, and the release corpus requires a measured token reduction without recall loss. |
| 28 | Session delta feedback | Implemented | A client-acknowledged identical success is replaced by a fingerprinted validation/context receipt with exact expansion handles; missing acknowledgement, changed content, semantic validation changes, failures, warnings, and explicit opt-out preserve the full live payload. |

## Implemented supporting capabilities

The current foundation also includes:

- runtime requirement detection and compatibility reporting for Python, Node.js, Java, Rust, and PHP;
- safe managed `run`/`stop`, readiness checks, supervised metadata, and stale-state recovery;
- parser registry extensions and fixtures for supported tool families;
- consistent secret masking across source, diffs, logs, diagnostics, runtime output, and reports;
- local multi-agent coordination with leases, dependency gates, and declared-path conflict detection;
- selective retrieval with conservative fallback and false-negative measurement;
- optional exact token accounting, category budgets, provider usage normalization, and prompt-cache layout;
- bounded hierarchical retrieval refinement and deterministic prose/log deduplication.

## Active direction

The 1.0 capability set is complete. Further development should prioritize measured correctness,
backward-compatible schema evolution, parser fixtures for newly supported tool versions, and
cross-platform performance evidence rather than adding overlapping commands.

## Success metrics

Efficiency is evaluated on representative small projects and monorepos using:

- context characters, selected files, and emitted evidence before and after a feature;
- affected-test and relevant-file false-negative rates;
- checks executed, reused, skipped, retried, or cancelled;
- time to first actionable failure and final verified completion;
- repository files walked or parsed on full and incremental runs;
- cache, checkpoint, focused-rerun, and context reuse;
- agent-visible bytes and estimated tokens with the counting method identified;
- repeated cold/warm benchmark medians and variability;
- successful task completion and final full-validation pass rates.

Raw character, byte, timing, and correctness measurements remain the reproducible source data.

## Safety and privacy constraints

- Analysis remains local unless the user explicitly invokes a separately reviewed integration.
- Cache, session, context, logs, and reports must never retain unmasked secrets.
- Evidence references resolve only inside the selected project root.
- Cached success never overrides changed runtime, dependencies, commands, configuration, or relevant files.
- Compact output never hides uncertainty, truncation, skipped required checks, or failed secret scans.
- Automatic commit, push, merge, release, deployment, destructive cleanup, arbitrary process
  termination, and remote source transmission remain out of scope.
- Learned/model-based semantic compression remains disabled; only deterministic, fail-closed prose
  and repetitive-log deduplication is supported.
