# Agent Efficiency Roadmap

## Purpose

`ai-dev` should reduce the amount of repository state and tool output that a coding agent must
read while preserving enough evidence to make correct decisions. The goal is not merely to
produce shorter text. The goal is to produce the smallest trustworthy context for the current
task and make additional evidence available only when the agent asks for it.

This document describes product capabilities worth adding after version 0.4.0. Concrete
implementation work is tracked in `TODO.md`.

## Design principles

1. **Local and deterministic by default.** Context selection, caching, parsing, and ranking
   must not require an LLM or network service.
2. **Evidence before prose.** Reports should point to files, lines, commands, logs, and reason
   codes instead of generating long narrative explanations.
3. **Progressive disclosure.** Start with a compact summary and allow targeted expansion of a
   failure, file, workspace, or command.
4. **Safe uncertainty.** When selection confidence is low, report that fact and broaden the
   validation plan instead of presenting a guess as certainty.
5. **Stable machine contracts.** Agents should consume versioned JSON fields, not scrape
   human-oriented Markdown.
6. **Measurable efficiency.** New features should report context characters, selected versus
   rejected files, cache hits, duplicated messages removed, and available expansion paths.

## Implemented foundation

The current implementation now includes:

- incremental context manifests with changed/reused accounting;
- a reusable, schema-versioned repository index;
- content-addressed validation caching with bounded retention and explicit bypass;
- stable failure signatures, bounded parallel checks, and workspace-aware execution;
- Python AST-aware snippets and conservative JavaScript/TypeScript top-level snippets with line
  ranges, selection reasons, and referenced local symbols;
- local index/cache status and maintenance commands;
- stable evidence IDs with targeted local expansion;
- named local baselines with failure and status regression comparison.
- exact-fingerprint checkpoint/resume and priority feedback scheduling;
- one-shot compact `feedback` reports with stage timings and local session state;
- incrementally reused import/test impact edges and focused rerun hints;
- a dependency-free local MCP STDIO adapter with focused project tools and strict schemas.
- symbol-level working-tree diff summaries for Python and JavaScript/TypeScript, including
  signatures, related tests, risk, and conservative fallback metadata.
- local multi-agent task coordination with atomic state, expiring leases, dependency gates,
  and declared-path conflict detection through CLI and MCP.
- conservative Java, Rust, and PHP declaration adapters shared by bounded context selection
  and symbol-level working-tree diff analysis.

The sections below remain the long-term target design. JavaScript and TypeScript now have a
conservative top-level symbol extractor. Java, Rust, and PHP now have conservative structural
extractors as well; deeper method and ecosystem-specific adapters remain planned. A first
version of reproducible local A/B workflow benchmarks is implemented in ai-dev benchmark.

## Recommended capabilities

### 1. Incremental context packs

Add a context mode that emits only information that changed since the previous successful
context build.

Possible interface:

```bash
ai-dev context build --incremental
ai-dev context build --since <context-id>
```

The context manifest should fingerprint selected files, Git state, diffs, validation results,
and configuration. Unchanged snippets would be represented by stable references rather than
repeated in full.

**Expected impact:** very high for multi-turn tasks, where agents currently receive the same
repository overview and source snippets repeatedly.

### 2. Symbol-aware source selection

Select the relevant function, class, method, imports, and nearby tests instead of including the
first `N` characters of an entire file. Use standard-library parsers where available, beginning
with Python `ast`, and conservative language-specific extractors for other ecosystems.

Each snippet should include:

- file and line range;
- selected symbol name and type;
- reason for selection;
- referenced local symbols;
- whether surrounding content was omitted.

**Implementation status:** top-level symbol selection and working-tree symbol diffs are implemented
for Python and JavaScript/TypeScript. Minimal and review context profiles replace eligible raw
diffs with bounded symbol summaries; ambiguous or unsupported files retain the raw-diff fallback.
Additional language and method-level adapters remain planned.

**Expected impact:** very high for large source files and review tasks.

### 3. Content-addressed validation cache

Cache a check result only when all inputs that can affect it are unchanged: command, working
directory, relevant files, lockfiles, tool version, runtime version, environment allowlist, and
configuration.

Possible interface:

```bash
ai-dev check --mode changed --cache
ai-dev cache explain
ai-dev cache clear --expired
```

Every reused result must state its fingerprint, age, and invalidation inputs. Required checks
must never be skipped on an ambiguous cache match.

**Expected impact:** very high for repeated agent loops and medium-to-large repositories.

### 4. Failure signatures and deduplication

Normalize repeated failures into stable signatures based on tool, error code, file, symbol,
message pattern, and root cause. A report should show one representative failure, its count,
affected locations, and a reference to the full log.

This would allow an agent to distinguish:

- the same failure repeated across hundreds of tests;
- one root compilation error causing many downstream failures;
- a new failure introduced after a change;
- an unchanged known failure from the baseline.

**Expected impact:** high for CI logs, compiler cascades, and flaky test suites.

### 5. Baseline-aware reports

Compare the latest scan, check, Git inspection, or context pack with a named local baseline.

```bash
ai-dev baseline create main
ai-dev check --compare main
ai-dev context build --compare main
```

The compact report should lead with new failures, resolved failures, changed warnings, and
changed project capabilities. Unchanged information should be summarized by count.

**Expected impact:** high for code review and long-running repair tasks.

### 6. Progressive report expansion

Give every issue, check, snippet, diff, and workspace a stable local ID. Add commands that
retrieve only one requested piece of evidence.

```bash
ai-dev explain issue:<id>
ai-dev explain check:<id> --tail 100
ai-dev explain file:<id> --symbol <name>
```

The top-level report can then remain small while agents retain a deterministic way to inspect
details without reading a full log or rebuilding all context.

**Expected impact:** high and broadly applicable.

### 7. Task-aware context profiles

Add deterministic profiles that change ranking and budgets according to the type of task:

- `debug`: failing command, first root cause, related source, and related tests;
- `review`: diff, changed symbols, risk areas, tests, and configuration impact;
- `implement`: requested area, entrypoints, local dependencies, and validation plan;
- `docs`: documentation, public interfaces, examples, and terminology;
- `minimal`: only changed files, plan, failures, and references to expandable evidence.

Profiles should be explainable rule sets, not hidden AI prompts. User include/exclude rules must
continue to take precedence.

**Expected impact:** medium to high by preventing irrelevant context from entering a task.

### 8. Workspace-aware routing

Represent a monorepo as a graph of workspaces and route changed files, tests, bootstrap steps,
and context snippets to the smallest owning workspace. Repository-wide checks should run only
when shared configuration or dependency boundaries change.

The report should explain the route:

```text
packages/api/src/auth.py
  -> workspace packages/api
  -> Python runtime and lockfile
  -> tests/api/test_auth.py
  -> pytest tests/api/test_auth.py
```

**Expected impact:** very high for monorepos, where repository-wide context and validation are
the largest source of avoidable cost.

### 9. Dependency and impact graph

Build a bounded local graph from imports, package manifests, workspace declarations, test
mappings, generated-code relationships, and configuration ownership. Use the graph for ranking,
not as a reason to include every reachable file.

Reports should include the shortest reason path from a changed file to every selected file or
check. This makes selection auditable and helps an agent reject irrelevant context.

**Expected impact:** high for accurate changed-test selection and medium for context reduction.

### 10. Failure-focused reruns

After a failed check, generate the smallest safe rerun command supported by the tool: a pytest
node ID, Jest test path, Maven module, Gradle task, Cargo package, or equivalent. Preserve the
original full-validation command as the final verification step.

The workflow becomes:

```text
full or changed check -> focused repair loop -> required final validation
```

This reduces both execution time and the quantity of repeated output an agent must inspect.

**Expected impact:** high during debugging loops.

### 11. Compact agent protocol

Define a dedicated versioned JSON format optimized for agent consumption. It should avoid
duplicating human-readable prose and use stable codes plus references.

Suggested top-level sections:

- `decision`: status, confidence, and blocking reason codes;
- `changes`: compact file and symbol summaries;
- `validation`: selected, cached, passed, failed, and required checks;
- `evidence`: bounded inline evidence with IDs;
- `expand`: commands or artifact references for additional local evidence;
- `budget`: characters emitted, omitted, deduplicated, and reused.

Markdown should remain available for humans but should not be the primary integration format.

**Expected impact:** medium per report and high across frequent agent interactions.

### 12. Local session state

Maintain a small, versioned session manifest containing the last known task, relevant files,
validation state, context fingerprints, and unresolved failure signatures. This is operational
state, not a natural-language conversation transcript.

The manifest would let a new agent turn answer: "What changed since the last successful check?"
without resending the entire previous context.

**Expected impact:** high for interrupted or multi-agent workflows.

## General workflow acceleration

Token reduction is only one part of agent efficiency. The following mechanisms reduce elapsed
time between a code change and trustworthy feedback, while keeping execution local,
deterministic, and explainable.

### 13. Dependency-aware parallel check scheduler

Run independent checks concurrently while preserving explicit dependencies. For example, lint,
type checking, and unrelated workspace tests may run in parallel, while packaging waits for its
required build step.

The scheduler should:

- expose a check dependency graph in `--explain` output;
- limit concurrency based on CPU, memory, and user configuration;
- stream only compact status changes while retaining complete per-check logs;
- cancel dependent work when a prerequisite fails;
- keep deterministic report ordering regardless of completion order;
- support `--jobs 1` for reproducible sequential diagnosis.

**Expected impact:** very high for repositories whose validation plan contains several
independent tools or workspaces.

### 14. Persistent repository index

Maintain a small local index of files, symbols, imports, workspace ownership, tests, and relevant
configuration. Update only entries whose content fingerprint changed instead of walking and
parsing the entire repository on every command.

```bash
ai-dev index status
ai-dev index update
ai-dev index rebuild
```

The index must be schema-versioned, safe to delete, stored under `.ai/cache/`, and automatically
invalidated when configuration or indexer versions change.

**Expected impact:** high for repeated scans, context builds, and changed-test selection in large
repositories.

### 15. Watch mode with debounced validation

Add an opt-in foreground mode that observes project changes and runs the smallest justified
validation after a short debounce period.

```bash
ai-dev watch --profile debug
ai-dev watch --mode changed --debounce 500ms
```

The watcher should coalesce rapid editor writes, ignore generated output, cancel obsolete runs,
and retain only the latest useful result. It must not become a hidden background service unless
the user explicitly requests that lifecycle.

Implemented as a foreground polling loop with debounce, generated-root exclusion, changed-check
validation, queued changes, and a deterministic run bound. It never becomes a hidden service.

**Expected impact:** high during interactive implementation and repair loops.

### 16. Priority and fail-fast scheduling

Order checks by expected information value and cost. Fast syntax, configuration, lint, and
compile checks should normally run before expensive suites when they are likely to reveal a
blocking root cause.

Provide two explicit policies:

- `feedback-first`: stop or postpone expensive dependent checks after a blocking failure;
- `complete`: run all independent checks to produce a comprehensive report.

Historical local durations may improve ordering, but correctness must not depend on them.

**Expected impact:** high for reducing time to the first actionable error.

### 17. Warm toolchain and environment state

Record safe, non-secret facts about the prepared environment: resolved executable paths,
versions, virtual environment, lockfile fingerprints, installed dependency state, and last
successful bootstrap plan. Use this information to avoid repeated environment discovery and
unnecessary installation commands.

```bash
ai-dev bootstrap --if-needed
ai-dev environment explain
```

The tool must revalidate executable existence and fingerprints before reusing state. It must not
silently install global software or assume that an activated shell remains unchanged.

Implemented with a schema-versioned local snapshot, input and plan fingerprints, executable
path revalidation, bootstrap --if-needed, and environment explain. Only a successful bootstrap
can refresh reusable state.

**Expected impact:** medium to high for fresh sessions and multi-workspace repositories.

### 18. Checkpoint and resume

Persist the validation plan and completed step fingerprints so an interrupted run can resume
without repeating successful work whose inputs remain unchanged.

```bash
ai-dev check --resume
ai-dev session status
```

Resume should reject stale checkpoints when Git state, commands, configuration, runtime, or
relevant files changed. Reports must distinguish resumed, cached, newly executed, and skipped
steps.

**Expected impact:** high for long test suites, machine restarts, and interrupted agent tasks.

### 19. Flaky-test awareness and bounded retries

Track local failure signatures and durations to identify tests that alternate between pass and
fail without relevant input changes. Allow an explicitly bounded retry policy and report the
original failure as flaky rather than hiding it behind a successful retry.

```bash
ai-dev check --retry-flaky 1
ai-dev test flaky
```

Retries must be opt-in or configured, capped, and excluded from deterministic failures such as
syntax errors. A passing retry must never be presented as a clean first-pass result.

Implemented as an opt-in zero-to-three retry policy for test tasks only. Deterministic and
environment failures are excluded; first failures remain visible, flaky passes are not cached or
checkpointed, and bounded fingerprint-scoped history powers test flaky.

**Expected impact:** medium for noisy suites and high for avoiding unproductive repair attempts.

### 20. Unified fast feedback command

Provide one command that performs the normal agent feedback loop: inspect changes, select the
smallest safe checks, reuse valid results, execute independent work in parallel, summarize new
failures, and emit a bounded context delta.

```bash
ai-dev feedback --task "fix authentication timeout"
ai-dev feedback --explain
```

This command should orchestrate existing primitives rather than introduce separate detection,
runner, or reporting logic. Its report should state exactly what was reused, executed, omitted,
cancelled, and selected for context.

**Expected impact:** very high for agent integrations because it replaces several sequential CLI
round trips with one stable operation.

### 21. Performance budgets and diagnostics

Measure command startup, detection, indexing, scheduling, subprocess execution, parsing, report
generation, and context selection separately. Expose slow stages without requiring verbose raw
logs.

```bash
ai-dev performance latest
ai-dev performance compare <run-a> <run-b>
```

Budgets should detect regressions in `scan`, `check --explain`, and incremental context creation.
Measurements remain local and should not include repository contents.

**Expected impact:** indirect but essential for preventing new functionality from making the CLI
progressively slower.

### 22. Reproducible agent workflow benchmarks

Build a local A/B benchmark suite that measures complete coding-agent workflows with and without
`ai-dev`. Representative tasks should include a small single-file fix, a failure in a large test
suite, a multi-turn repair, and a change inside a monorepo workspace. Both variants must start
from the same repository commit, environment state, task description, and validation policy.

Record at least:

- time to the first actionable failure and to final verified completion;
- commands and validation subprocesses executed;
- files, source characters, log bytes, and report bytes read by the agent;
- estimated input and output tokens, with the estimation method and model tokenizer identified;
- cache, checkpoint, focused-rerun, and incremental-context reuse;
- task correctness, affected-test false negatives, and whether final full validation passed.

Store machine-readable results and a compact comparison report so changes can be compared across
versions. Repeated trials should report medians and variability, while warm-cache and cold-cache
runs must remain separate. A benchmark result is valid only when both variants produce the same
correct outcome and required final verification.

Possible interface:

```bash
ai-dev benchmark run --suite agent-workflows --variant baseline
ai-dev benchmark run --suite agent-workflows --variant ai-dev
ai-dev benchmark compare <baseline-run> <ai-dev-run>
```

Benchmark fixtures should be local, deterministic, versioned, and safe to run without network
access. Published performance claims must link to the fixture version, raw measurements, machine
profile, and configuration used.

**Expected impact:** essential for proving real time and context savings, finding regressions, and
prioritizing the remaining roadmap by measured agent benefit.

## Suggested implementation order

1. Stable evidence IDs, timing data, and budget metrics.
2. Failure signatures and deduplication.
3. Incremental context manifests and a persistent repository index.
4. Content-addressed validation cache and checkpoint/resume.
5. Priority scheduling, fail-fast policies, and bounded parallel execution.
6. Symbol-aware Python selection.
7. Progressive report expansion and a unified `feedback` command.
8. Workspace-aware routing and dependency graph.
9. Watch mode, task-aware profiles, and adapters for additional languages.
10. Baselines, focused reruns, flaky-test awareness, and local session state.
11. A compact, documented agent integration protocol.
12. Reproducible A/B agent workflow benchmarks and published local comparison reports.

The first five items provide meaningful time and context savings without requiring a full
semantic model of every supported language.

## Success metrics

Efficiency should be evaluated on representative small projects and monorepos. Record at least:

- context characters emitted before and after the feature;
- percentage of emitted snippets later used to explain or fix the task;
- repeated log lines and duplicate failures removed;
- checks executed, safely reused, or skipped;
- time to first actionable failure;
- total wall-clock validation time and aggregate subprocess time;
- scheduler utilization and time saved through safe parallel execution;
- repository files walked or parsed on full and incremental runs;
- time saved through cache reuse, checkpoint resume, and avoided bootstrap work;
- obsolete watch runs cancelled before expensive work completed;
- number of progressive-expansion requests;
- false-negative rate for affected tests and relevant-file selection;
- percentage of runs that fall back because confidence is too low;
- successful task completion rate and final full-validation pass rate;
- median end-to-end task time, command count, and agent-visible bytes for equivalent A/B runs;
- estimated agent input/output tokens, reported together with the tokenizer and estimation method;
- benchmark variability across repeated cold-cache and warm-cache trials.

Token estimates may be shown as an approximation, but raw character and byte counts should remain
the reproducible source metrics.

## Safety and privacy constraints

- All analysis remains local unless the user explicitly invokes a separate remote integration.
- Cache and session files must never store unmasked secrets.
- Evidence references must resolve only inside the selected project root.
- Cached success must not override a changed runtime, dependency lockfile, command, or relevant
  configuration file.
- Compact output must never hide uncertainty, truncation, skipped required checks, or a failed
  secret scan.
- Efficiency improvements must not add automatic commit, push, deployment, or destructive cleanup.
