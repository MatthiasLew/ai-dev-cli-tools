# Context Builder

`ai-dev context build` creates a bounded context package for coding agents. It is local-only and deterministic: no embeddings, no LLM calls, and no cloud service dependencies.

## Outputs

By default the command writes:

- `.ai/context/context-latest.md`
- `.ai/context/context-latest.json`

Use `--incremental` to emit only candidate files whose content fingerprint changed since the previous incremental pack. The schema-versioned manifest is stored at `.ai/cache/context-manifest.json`; unchanged candidates are reported as reused and are not repeated.

Use `--format markdown`, `--format json`, or `--format both` to control artifacts. Use `--output <directory>` to write to a different directory.

## Profiles

Use `--profile minimal|debug|review|full` for stable task-oriented defaults. `minimal` creates a
small handoff, `debug` expands errors and nearby code, `review` focuses on changed files, and
`full` provides broad repository coverage. Explicit non-default budget flags override profile
budgets. The selected profile and resolved limits are recorded in the JSON report.
## Budget Controls

Defaults:

- `--max-chars 50000`
- `--max-files 30`
- `--max-file-chars 8000`
- `--max-diff-chars 15000`

The report records truncation and reasons for selected or rejected files.

## Selection Inputs

The builder reuses existing project scan, repository map, git inspection, and changed-test analysis. It selects changed files, related tests, detected entrypoints, important config, CI workflows, documentation, and files matched by `--include`.

`--changed-only` and `--staged-only` narrow selection to Git changes. `--no-git` skips Git inspection and diffs, which is useful for fixture directories or unpacked source trees.

## Symbol-aware source snippets

When a Python file exceeds `--max-file-chars`, the builder parses it with the standard-library
AST and selects imports plus task-relevant top-level functions, async functions, or classes.

JavaScript and TypeScript files use a dependency-free, conservative structural extractor for
top-level functions, classes, interfaces, types, enums, namespaces, and arrow functions. The
extractor ignores nested declarations and braces inside comments or strings. It deliberately
falls back to bounded file-prefix selection for unbalanced or ambiguous source instead of
guessing.

Every selected snippet reports its symbol name, kind, line range, reason, referenced local
symbols, and truncation state. Import text has a separate bounded budget so it cannot displace
the matching implementation. Syntax errors, small files, unsupported languages, and files
without recognized top-level declarations use the existing bounded file-prefix fallback.

## Safety

The builder excludes `.env`, private keys, binary files, cache directories, build outputs, and `.ai/logs` or `.ai/reports`. Snippets and diffs are masked with the same secret patterns used by git inspection. Report writers also apply a final mask before serializing Markdown or JSON. Check, bootstrap, doctor, foreground runtime, and supervised background output are masked before being persisted.

## Current Limits

- Monorepo/workspace detection and per-subproject command routing: implemented.
- Per-subproject check and bootstrap working directories: implemented.
- Runtime version validation: partial.
- Dependency analysis is lightweight and static for Python, JS/TS, Java, Rust, and PHP.
