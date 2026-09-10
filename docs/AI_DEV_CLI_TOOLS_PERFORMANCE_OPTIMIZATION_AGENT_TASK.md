# AI Agent Task — Performance Optimization Phase for `ai-dev-cli-tools`

Repository: `https://github.com/MatthiasLew/ai-dev-cli-tools`

## Objective

Optimize the performance of `ai-dev-cli-tools` without sacrificing correctness, determinism, portability, maintainability, security, or agent-output quality.

Do **not** rewrite the project in another language by default.

The current architecture is already reasonably mature and includes caching, incremental indexing, filesystem watching, parallel check execution, lazy imports, semantic indexing, performance telemetry, benchmark tooling, and context/token optimization.

The goal of this task is to:

1. Measure real bottlenecks.
2. Remove avoidable overhead in the existing Python implementation.
3. Improve filesystem, Git, subprocess, parsing, hashing, scheduling, and serialization hot paths where justified.
4. Establish reliable before/after benchmarks.
5. Investigate Rust only for proven CPU-bound hot paths.
6. Introduce native code only when end-to-end benchmarks justify the added complexity.

---

# Critical Rules

## Do not optimize blindly

Before changing implementation:

- establish a reproducible baseline;
- measure individual stages;
- identify the actual bottleneck;
- record cold and warm results separately;
- keep correctness checks enabled;
- compare end-to-end latency, not only microbenchmarks.

A function becoming 10x faster is irrelevant if the complete user-facing command improves by only 1%.

## Do not introduce Assembly

Assembly is explicitly out of scope unless profiling produces an extremely unusual, clearly CPU-bound kernel where:

- existing optimized libraries cannot solve the problem;
- Rust/C/native libraries are insufficient;
- the benefit is proven by benchmarks.

This is not expected for this repository.

## Preserve Python as the orchestration layer

Python should remain responsible for:

- CLI;
- configuration;
- orchestration;
- policies;
- report generation;
- integrations;
- high-level scheduling;
- fallbacks.

If native acceleration is eventually introduced, prefer:

- Rust;
- PyO3;
- maturin;
- a small isolated native module;
- clean Python fallback where practical.

Do not perform a whole-project rewrite.

---

# Phase 0 — Repository State and Baseline

Before modifying code:

1. Pull/update the repository.
2. Confirm the current branch and working tree.
3. Record the current commit SHA.
4. Run the complete existing validation suite.
5. Record Python version, OS, architecture, CPU, RAM, Git version, and relevant toolchain versions.
6. Confirm existing benchmark and performance commands work.

Run at minimum:

```bash
python -m pytest
ruff check .
mypy src tests scripts
```

Also run the repository's existing validation/release helpers if available.

Confirm:

- all existing tests pass;
- coverage threshold remains satisfied;
- installed-package smoke tests pass;
- CI/release validation remains valid.

Store the baseline results in a dedicated report under:

```text
docs/performance/
```

Suggested name:

```text
docs/performance/PERFORMANCE_BASELINE_YYYY-MM-DD.md
```

---

# Phase 1 — Establish Performance Baselines

Use the project's existing performance system.

Benchmark at minimum:

```bash
ai-dev scan
ai-dev check --mode changed --explain
ai-dev context build --incremental --task "performance benchmark"
ai-dev git status
ai-dev git inspect
ai-dev index update
ai-dev semantic index --backend auto
ai-dev feedback --task "performance benchmark"
```

Where applicable, also compare:

```bash
ai-dev performance latest --json
ai-dev performance compare <baseline> <candidate> --json
```

For each operation collect:

- median wall-clock time;
- minimum;
- maximum;
- standard deviation;
- startup time;
- subprocess time;
- filesystem/index time;
- context selection time;
- serialization/report-writing time;
- number of subprocess launches;
- files scanned;
- files read;
- files hashed;
- cache hits;
- cache misses;
- amount of agent-visible output;
- estimated/reported tokens where available.

Run enough trials to avoid conclusions from one noisy run.

Recommended:

- at least 10 warm trials for small operations;
- at least 5 cold trials;
- separate cold and warm results.

Never compare cold and warm results as if they were equivalent.

---

# Phase 2 — Profile the Python Runtime

Add or use profiling only where useful.

Preferred tools:

- `cProfile`;
- `pstats`;
- `py-spy` if available;
- `time.perf_counter`;
- existing repository performance telemetry.

Profile the main commands and identify:

- cumulative CPU time;
- Python-level hot functions;
- excessive path/stat calls;
- repeated file reads;
- repeated JSON parsing/serialization;
- duplicate Git commands;
- unnecessary subprocess starts;
- repeated regex compilation/work;
- excessive allocations;
- repeated repository scans.

Produce a table similar to:

| Operation | Bottleneck | % total time | CPU/I/O/subprocess | Candidate fix |
|---|---:|---:|---|---|
| `git inspect` | repeated Git subprocesses | ... | subprocess | merge/reuse results |
| `index update` | filesystem traversal | ... | I/O | reduce stat/path overhead |
| `context build` | impact graph | ... | CPU/I/O | single-read parsing |
| ... | ... | ... | ... | ... |

Do not start Rust work until this profiling exists.

---

# Phase 3 — Optimize Git Inspection

This is a high-priority target.

Inspect:

```text
src/ai_dev_tools/git/inspect.py
```

Current implementation launches multiple independent Git processes.

Investigate whether results can be reused or combined.

## Known optimization candidate

Detailed inspection currently computes equivalent unstaged diff data more than once.

Do not execute the same command twice when one result can be reused safely.

Example target:

```text
git diff
```

Cache/reuse its output within a single command invocation when several metrics depend on the same diff.

## Investigate reducing subprocess count

Review these calls:

```text
git rev-parse
git branch
git status
git diff
git diff --cached
git ls-files
git stash list
git log
git diff --stat
```

Determine whether some data can be obtained from:

- one Git command;
- `git status --porcelain=v2`;
- reused command output;
- one diff call used for multiple calculations.

Do not reduce correctness for the sake of subprocess count.

## Tests

Add tests proving:

- output remains semantically identical;
- staged files are correct;
- unstaged files are correct;
- untracked files are correct;
- renamed files are correct;
- conflicts are correct;
- ahead/behind remains correct;
- detached HEAD remains correct;
- stash count remains correct;
- detailed inspection metrics remain correct.

Add a regression test ensuring duplicate Git commands are not executed unnecessarily.

Measure:

- total `git inspect` latency;
- subprocess count;
- total subprocess time.

---

# Phase 4 — Remove Duplicate File Reads

Review:

```text
src/ai_dev_tools/cache/graph.py
```

A source file may currently be read separately for:

- dependency/reference extraction;
- generated-file relationship detection.

Refactor where safe so one file read can feed multiple analyses.

Target design:

```text
read file once
    |
    +-- reference parser
    |
    +-- generated relationship parser
    |
    +-- future analyzers
```

Avoid storing entire repositories in memory.

Use bounded/local reuse only for files already being processed.

## Tests

Verify identical graph output before/after for:

- Python imports;
- JavaScript/TypeScript imports;
- Rust modules;
- generated relationships;
- test relationships;
- configuration relationships;
- unchanged/reused graph entries.

Benchmark:

- small repo;
- medium repo;
- synthetic large repo;
- warm incremental update;
- cold rebuild.

---

# Phase 5 — Filesystem Traversal Optimization

Inspect:

```text
src/ai_dev_tools/cache/repository.py
```

Current logic uses filesystem traversal, path conversion, stat calls, ignore matching, symlink checks, and hashing.

Investigate:

- unnecessary `Path` object creation;
- repeated `stat()` calls;
- repeated ignore checks;
- expensive `fnmatch` patterns;
- redundant `.is_file()` calls after directory walking;
- opportunities to use `os.scandir()`/DirEntry metadata efficiently;
- opportunities to avoid repeated path normalization;
- precompiled ignore rules where useful.

Do not optimize for theoretical microseconds unless profiling confirms impact.

## Important constraints

Preserve:

- symlink safety;
- ignore behavior;
- deterministic ordering;
- cross-platform path handling;
- fixture exclusions;
- `.ai` exclusions;
- generated/dependency/VCS exclusions.

## Tests

Add regression fixtures for:

- nested directories;
- symlinks;
- ignored directories;
- ignored files;
- venv variants;
- `.ai`;
- test fixtures;
- Windows-style paths;
- Linux paths.

---

# Phase 6 — Hashing Strategy

The current incremental index correctly avoids re-hashing unchanged files when metadata matches.

Keep this behavior.

Investigate whether hashing changed files is a meaningful bottleneck.

If profiling shows it is:

1. benchmark sequential hashing;
2. benchmark bounded parallel hashing;
3. test SSD vs slower storage assumptions;
4. avoid oversaturating storage;
5. preserve deterministic output.

Possible approaches:

- bounded `ThreadPoolExecutor` for changed-file hashing;
- adaptive worker count;
- hashing only when required by current fingerprint semantics.

Do not replace SHA-256 with a weaker hash unless the security/correctness implications are explicitly evaluated and approved.

Do not implement SHA-256 manually.

---

# Phase 7 — Subprocess Runtime Improvements

Inspect:

```text
src/ai_dev_tools/utils/subprocess.py
```

The current implementation already supports:

- timeouts;
- cancellation;
- output capture;
- Windows `.cmd/.bat` handling;
- safe `shell=False`.

Preserve all of these.

Investigate:

- unnecessary process launches;
- startup overhead;
- repeated environment resolution;
- excessive polling;
- process cancellation latency;
- output decoding overhead for large outputs.

Do not introduce shell execution merely for speed.

## Tests

Preserve or improve tests for:

- missing executable;
- timeout;
- cancellation;
- large stdout;
- large stderr;
- mixed stdout/stderr;
- Windows batch execution;
- Unicode output;
- invalid bytes;
- killed processes.

---

# Phase 8 — Scheduler and Parallelism

Inspect:

```text
src/ai_dev_tools/runners/check_scheduler.py
```

The scheduler already supports parallel check execution.

Do not replace this blindly with multiprocessing.

Determine whether workload categories are:

- CPU-bound;
- subprocess-bound;
- I/O-bound;
- memory-heavy;
- exclusive.

Investigate whether:

- worker pools are recreated too frequently;
- waves could share one executor;
- resource batches are unnecessarily conservative;
- jobs can be selected adaptively;
- first-actionable-result latency can be improved.

Key metric:

```text
time_to_first_failure_seconds
```

Agent workflow latency may matter more than full suite completion.

Optimize for:

1. correctness;
2. first actionable feedback;
3. total wall time;
4. resource stability.

Do not optimize only aggregate CPU utilization.

---

# Phase 9 — Context Builder Hot Paths

Inspect the context subsystem, especially:

```text
src/ai_dev_tools/context/builder.py
src/ai_dev_tools/context/selection.py
src/ai_dev_tools/context/retrieval.py
src/ai_dev_tools/context/tokens.py
src/ai_dev_tools/context/compression.py
```

Profile:

- repository mapping;
- candidate selection;
- ranking;
- content collection;
- diff generation;
- token estimation;
- compression;
- JSON/Markdown output.

The goal is not only lower runtime.

The context builder exists to reduce agent work and token usage.

All performance changes must preserve:

- selection recall;
- precision;
- explicit include priority;
- source usefulness;
- truncation semantics;
- incremental correctness.

A faster context builder that omits required files is a regression.

Use existing benchmark gates for:

- correctness;
- recall;
- false negatives;
- time;
- token reduction.

---

# Phase 10 — Semantic Analysis

The project already supports optional Tree-sitter-based semantic indexing.

Check whether current Python-side processing around Tree-sitter is a bottleneck.

Do not replace Tree-sitter with custom parsers unless benchmarks and correctness justify it.

Potential optimizations:

- parse changed files only;
- reuse parsed/indexed results;
- avoid repeated source reads;
- cache symbol results using content fingerprints;
- batch processing where library APIs permit it.

Measure semantic indexing separately from normal repository indexing.

---

# Phase 11 — Serialization and Report Generation

Profile:

- `json.dumps`;
- Markdown generation;
- repeated conversion to dictionaries;
- duplicate report serialization;
- temporary-file writing.

Only consider a faster JSON library if serialization is a meaningful portion of total runtime.

Possible candidates can be evaluated, but avoid adding dependencies for negligible gains.

Any alternative serializer must preserve:

- deterministic output where required;
- supported types;
- Unicode behavior;
- formatting expectations;
- compatibility with existing tests;
- packaging simplicity.

---

# Phase 12 — Startup-Time Optimization

The CLI already uses lazy imports for many commands.

Measure startup independently.

Test:

```bash
ai-dev --version
ai-dev scan
ai-dev git status
ai-dev context build ...
```

Investigate:

- import graph;
- expensive module-level initialization;
- unused imports;
- parser construction cost;
- eagerly loaded modules.

Do not over-engineer parser generation unless startup contributes materially to user-visible latency.

---

# Phase 13 — Cache Correctness Improvements

Before adding aggressive caching, address correctness risks documented by the repository audit.

## Environment identity

Validation cache fingerprints should eventually account for relevant external toolchain/environment identity, such as:

- Node version;
- Java version;
- PHP version;
- compiler version;
- dependency state where appropriate;
- explicitly selected non-secret environment inputs.

Do not store secrets.

## Concurrent writers

Review cache writes for multi-process safety.

Use unique temporary files where needed.

Test two concurrent processes attempting identical cache writes.

Performance improvements must not introduce corrupted cache state.

---

# Phase 14 — Create Performance Regression Tests

Add a dedicated performance benchmark corpus.

Do **not** make ordinary unit tests dependent on unstable absolute timings.

Use benchmark/gate infrastructure instead.

Create representative fixtures for:

1. tiny Python repo;
2. medium Python repo;
3. TypeScript repo;
4. Rust repo;
5. mixed monorepo;
6. many-file repo;
7. few very-large-files repo;
8. mostly unchanged incremental repo;
9. many changed files;
10. Git repo with staged/unstaged/untracked changes.

Record:

- baseline;
- candidate;
- machine profile;
- cold/warm state;
- command count;
- subprocess count;
- file count;
- hash count.

---

# Phase 15 — Decide Whether Rust Is Needed

Only after Python optimizations and profiling are complete.

Create a report:

```text
docs/performance/RUST_NATIVE_ACCELERATION_ASSESSMENT.md
```

For each candidate function provide:

| Candidate | Python time | % command time | Expected native gain | Complexity | Decision |
|---|---:|---:|---:|---|---|
| impact graph | ... | ... | ... | ... | ... |
| source symbol scan | ... | ... | ... | ... | ... |
| repository scan | ... | ... | ... | ... | ... |
| hashing | ... | ... | ... | ... | ... |

Rust is justified only if:

- the code is CPU-bound;
- it is called frequently enough;
- Python overhead is material;
- native implementation provides meaningful end-to-end improvement;
- packaging cost is acceptable;
- cross-platform wheels can be supported.

Suggested minimum threshold:

- at least ~20% improvement in an important end-to-end command;

or:

- a smaller latency improvement with a very large CPU/resource reduction that materially benefits repeated agent workflows.

Do not adopt Rust merely because a microbenchmark is faster.

---

# Phase 16 — Optional Rust Prototype

If profiling justifies it, create a minimal prototype.

Suggested module:

```text
native/
    Cargo.toml
    src/
        lib.rs
```

Expose only one or two proven hot functions.

Use:

```text
PyO3
maturin
```

Possible candidates:

- impact graph parsing;
- large-scale symbol scanning;
- repository metadata processing;
- text parsing/compression;
- CPU-heavy hashing orchestration.

Python API example:

```python
try:
    from ai_dev_native import build_impact_graph_native
except ImportError:
    build_impact_graph_native = None
```

Fallback:

```python
if build_impact_graph_native is not None:
    return build_impact_graph_native(...)
return build_impact_graph_python(...)
```

Native and Python implementations must produce equivalent semantic results.

---

# Phase 17 — Native Performance A/B Test

Compare:

```text
Python baseline
vs
optimized Python
vs
Python + Rust native path
```

Measure complete commands, not only functions.

At minimum:

```bash
ai-dev index rebuild
ai-dev index update
ai-dev context build --incremental ...
ai-dev feedback ...
```

Test:

- tiny repository;
- representative real repository;
- synthetic medium repository;
- large monorepo.

Track:

- wall time;
- CPU time;
- memory;
- disk reads;
- subprocess count;
- agent-visible bytes;
- token metrics;
- correctness;
- selection recall.

If native mode fails the benchmark gate or gives insignificant benefit, keep Python.

---

# Phase 18 — Cross-Platform Validation

The repository is cross-platform.

Any optimization must be validated on:

- Windows;
- Linux;
- macOS if CI supports it.

Python versions currently supported by the project must continue to work.

Do not introduce:

- OS-specific path assumptions;
- Unix-only process behavior;
- unsupported filesystem APIs without fallback;
- architecture-specific native binaries without packaging coverage.

If Rust is introduced, ensure release automation can build wheels for supported targets.

---

# Phase 19 — Security Review

Performance optimizations must preserve current security properties.

Do not weaken:

- `shell=False`;
- path validation;
- symlink handling;
- secret masking;
- local-only MCP/daemon assumptions;
- cache isolation;
- authenticated daemon IPC;
- execution policy.

Optimization must never mean bypassing validation or reducing security checks without explicit proof that equivalent protection remains.

---

# Phase 20 — Final Validation

Before considering the task complete:

Run the entire test suite.

Run:

```bash
python -m pytest
ruff check .
mypy src tests scripts
```

Run all project-specific release and CI validation helpers.

Run installed-wheel smoke tests.

Run benchmark corpus.

Run performance comparisons.

Confirm:

- no correctness regression;
- no selection recall regression;
- no new false negatives;
- no cache correctness regression;
- no cross-platform regression;
- no security regression;
- no packaging regression.

---

# Acceptance Criteria

The work is accepted only if all of the following are true:

- Existing behavior remains compatible unless a documented change was explicitly required.
- Full tests pass.
- Ruff passes.
- Strict mypy passes.
- Coverage threshold passes.
- Release validation passes.
- Installed-package smoke passes.
- Performance measurements are reproducible.
- Cold and warm measurements are reported separately.
- Every optimization is backed by before/after evidence.
- Duplicate/redundant Git and filesystem operations are reduced where identified.
- Performance-critical code has regression coverage.
- Context correctness and recall remain intact.
- Rust is introduced only if justified by end-to-end benchmarks.
- Assembly is not introduced.
- Documentation explains every meaningful optimization.

---

# Required Deliverables

Create or update:

```text
docs/performance/PERFORMANCE_BASELINE_YYYY-MM-DD.md
docs/performance/PERFORMANCE_OPTIMIZATION_REPORT_YYYY-MM-DD.md
docs/performance/RUST_NATIVE_ACCELERATION_ASSESSMENT.md
```

The final optimization report must contain:

1. baseline environment;
2. baseline benchmark results;
3. identified bottlenecks;
4. changes implemented;
5. before/after tables;
6. cold results;
7. warm results;
8. subprocess-count changes;
9. filesystem-read/hash changes;
10. context/token impact;
11. correctness validation;
12. regressions encountered and resolved;
13. rejected optimizations and reasons;
14. Rust assessment;
15. final recommendation.

---

# Agent Working Strategy

Use this order:

```text
MEASURE
  ↓
PROFILE
  ↓
REMOVE REDUNDANT WORK
  ↓
REDUCE I/O
  ↓
REDUCE SUBPROCESSES
  ↓
IMPROVE CACHING
  ↓
IMPROVE PARALLELISM
  ↓
BENCHMARK
  ↓
ONLY THEN CONSIDER RUST
  ↓
BENCHMARK AGAIN
```

Avoid:

```text
Python is slow
    ↓
rewrite everything
```

The target is not the fastest possible implementation in isolation.

The target is:

> the fastest, safest, deterministic, maintainable, cross-platform implementation that measurably improves real AI-agent development workflows.

---

# First Concrete Tasks

Start with these tasks before touching native code:

1. Establish benchmark baseline.
2. Profile `git inspect`.
3. Remove duplicate `git diff` execution where confirmed.
4. Count Git subprocesses before/after.
5. Profile repository index update.
6. Remove duplicate reads in impact-graph generation.
7. Profile filesystem traversal.
8. Evaluate use of `os.scandir()`/DirEntry metadata if justified.
9. Profile hashing.
10. Profile context builder.
11. Profile startup time.
12. Run the benchmark corpus.
13. Produce `RUST_NATIVE_ACCELERATION_ASSESSMENT.md`.
14. Only then decide whether a Rust prototype should exist.

Do not merge a performance optimization without measurable evidence.
