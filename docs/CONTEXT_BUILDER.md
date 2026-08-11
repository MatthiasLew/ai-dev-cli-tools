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

## Selective retrieval

`--retrieval auto|always|never` controls broad cross-file candidate expansion. The default `auto`
abstains only when explicit includes or Git changes provide focused roots. It preserves inferred or
changed-test evidence and adds static dependencies after the gate. Missing focus, broad task terms,
or changes to project/workflow configuration trigger a conservative full-candidate fallback.

`always` is the stable expansion override. `never` is an explicit user override that keeps focused
roots and related tests even when the automatic policy would expand. Every report includes a
`retrieval` object with the decision, confidence, reason code, input signals, focused roots,
omitted-candidate count (with at most 100 paths), fallback state, and
`ai-dev context build --retrieval always` as the expansion command. `expected_related_tests`,
`selected_related_tests`, `missed_related_tests`, and `false_negative_proxy` make the measurable
selection safety check explicit.

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

Java, Rust, and PHP use the same bounded selection contract with conservative structural
extractors. Java and PHP include class methods; Rust includes top-level functions, structs, enums,
traits, and impl blocks. Ambiguous or unbalanced input always falls back to the file prefix.

## Symbol-level diffs

Detailed Git inspection maps zero-context working-tree hunks to top-level Python and
JavaScript/TypeScript, Java, Rust, and PHP symbols. Reports expose changed signatures, added and deleted line counts,
change type, risk, related tests, and parser confidence. Module-level edits are retained as a
`<module>` entry, while deleted symbols are resolved against `HEAD`.

The `minimal` and `review` profiles compact eligible raw diffs into a bounded `symbol-diff`
summary. Raw diffs remain the fallback whenever parsing is ambiguous, a file is unsupported, or
no useful symbol mapping exists. The default, debug, and full profiles retain their raw diffs.

## Token accounting and category budgets

The default tokenizer is the dependency-free `estimate` method: masked UTF-8 bytes divided by four,
rounded up. Install `ai-dev-cli-tools[tokenizers]` and select `--tokenizer cl100k_base` or
`--tokenizer o200k_base` for exact local tiktoken counts. If the optional tokenizer is unavailable,
the report exposes `TOKENIZER_UNAVAILABLE` and uses the documented estimate.

Repeat `--token-budget category=N` for `source`, `diffs`, `tests`, `logs`, `maps`, `history`,
`cached_input`, or `output`. Content categories are truncated or structurally omitted before report
rendering. Cached-input and output budgets validate provider-reported usage. Use
`--provider-usage <project-relative-json>` to normalize OpenAI `input_tokens_details.cached_tokens`
or Anthropic cache read/write fields. Files outside the project root and files over 64 KiB are
rejected. The `token_accounting` report block records method, exactness, original/final counts,
truncation, budgets, normalized provider usage, totals, and violations.

## Safety

The builder excludes `.env`, private keys, binary files, cache directories, build outputs, and `.ai/logs` or `.ai/reports`. Snippets and diffs are masked with the same secret patterns used by git inspection. Report writers also apply a final mask before serializing Markdown or JSON. Check, bootstrap, doctor, foreground runtime, and supervised background output are masked before being persisted.

## Current Limits

- Monorepo/workspace detection and per-subproject command routing: implemented.
- Per-subproject check and bootstrap working directories: implemented.
- Runtime version validation: partial.
- Dependency analysis is lightweight and static for Python, JS/TS, Java, Rust, and PHP.
