# Context Builder

`ai-dev context build` creates a bounded context package for coding agents. It is local-only and deterministic: no embeddings, no LLM calls, and no cloud service dependencies.

## Outputs

By default the command writes:

- `.ai/context/context-latest.md`
- `.ai/context/context-latest.json`

Use `--format markdown`, `--format json`, or `--format both` to control artifacts. Use `--output <directory>` to write to a different directory.

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

## Safety

The builder excludes `.env`, private keys, binary files, cache directories, build outputs, and `.ai/logs` or `.ai/reports`. Snippets and diffs are masked with the same secret patterns used by git inspection.

## Current Limits

- Monorepo/workspace detection: experimental.
- Per-subproject runner isolation: planned after v0.3.0.
- Runtime version validation: partial.
- Dependency analysis is lightweight and static for Python, JS/TS, Java, Rust, and PHP.
