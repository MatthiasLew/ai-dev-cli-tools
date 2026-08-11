# Report Schema

The machine-readable JSON Schema is stored in `docs/report-schema.json` and is checked against the report model in the test suite.

Current schema version: `1.1`.

Required fields:

```json
{
  "schema_version": "1.1",
  "tool_version": "0.5.0a1",
  "command": "check",
  "status": "success",
  "exit_code": 0,
  "started_at": "ISO-8601",
  "finished_at": "ISO-8601",
  "duration_seconds": 1.23,
  "project_root": ".",
  "summary": {},
  "issues": [],
  "artifacts": [],
  "metadata": {}
}
```

Global statuses are `success`, `failed`, `partial`, `not_implemented`, `invalid_configuration`, `environment_error`, and `blocked`. Legacy internal `warning` statuses are serialized as `partial`.

Issue objects use stable fields:

```json
{
  "severity": "error",
  "code": "TEST_FAILURE",
  "tool": "pytest",
  "message": "expected 200, got 401",
  "file": "src/auth/service.py",
  "line": 84,
  "column": null,
  "masked": false
}
```

Severity values are `info`, `warning`, `error`, and `critical`.

## Machine-readable reason codes

Reports retain human-readable `message`, `reason`, `fallback_reason`, and
`blocking_reasons` fields. Whenever one of these values describes a tool decision or a
blocked/partial outcome, the same object also exposes a stable uppercase reason code. Examples
include `reason_code`, `fallback_reason_code`, and `blocking_reason_codes`. Consumers should
branch on codes and display prose; prose may improve without a schema-version change.

Context file and symbol entries, bootstrap steps, changed-check fallback analysis, missing
index/log/check outcomes, and finish blockers all follow this rule.

## Prompt cache layout

`cache layout` returns a relocatable `cache_layout` manifest with stable and volatile section order,
per-section and combined-prefix SHA-256 fingerprints, recommended OpenAI/Anthropic/provider-neutral
breakpoints, and machine-readable invariants proving timestamps, absolute paths, and random IDs are
excluded. The generated artifact is `.ai/cache/cache-layout.json`.

## Observation lifecycle

`feedback` and `session status` expose `observations` with schema version, a full `current`
observation, `current_retained_reasons`, at most 20 compact `referenced` observations,
`superseded_count`, duplicate suppression, avoided-character metrics, and an expansion command.
Referenced observations have stable `observation:<hash>` evidence IDs and can be retrieved through
`ai-dev explain` from the local content-addressed evidence archive.

## Progressive evidence and baselines

Expandable entries receive deterministic `evidence_id` values. `metadata.progressive` reports
the available references and the command template for targeted `ai-dev explain` calls. Named
baselines are local schema-versioned snapshots under `.ai/cache/baselines/`; comparisons expose
new/resolved failure signatures and issue codes, changed statuses, and blocking regressions.

## Migration From 1.0

Schema 1.1 adds `exit_code` and `metadata`. Consumers should treat missing fields from schema 1.0 as `exit_code: 0` for successful reports and `{}` for metadata. Consumers should accept `partial` where schema 1.0 reports may have used `warning`.

## Check Result Summary

`check` command entries include compact log-derived fields so agents do not need to read full logs by default. Parser results include `tool`, `parser`, `parser_confidence`, counts, first failure, project frames, repeated-message grouping, and full log paths.

`check --mode changed` includes `changed_analysis` with `strategy`, `confidence`, `changed_files`, `selected_tests`, `selected_commands`, and `fallback_reason`.
## Context Build Summary

`context build` reports include `technologies`, `git_state`, `changed_files`, `changed_symbols`, `symbol_diff_summary`, `related_tests`, `validation_plan`, `selected_files`, `rejected_files`, `diffs`, `latest_errors`, `secret_findings`, `recent_commits`, `retrieval`, and `budget` under `summary`. The `retrieval` block records the requested mode, retrieve/abstain decision, confidence, reason code, signals, focused roots, bounded omitted paths, conservative fallback, expansion command, and expected/selected/missed related tests as a false-negative proxy. Each changed symbol includes its path, name, kind, change type, current line range, added/deleted line counts, bounded signature, signature-change flag, risk, related tests, confidence, and reason code.

Consumers should treat snippet and diff content as optional because budget limits may omit or truncate them. Minimal and review profiles may set `selection_strategy: symbol-diff` and `omitted_content: true`; `symbol_diff_fallbacks` identifies files for which conservative parsing was not possible. Secret values are masked before being written to Markdown or JSON artifacts.

## Bootstrap Summary

`bootstrap` reports include `project_type`, `package_manager`, `dry_run`, `explain`, `planned_commands`, `executed_commands`, `created_venv`, `created_env`, `smoke_check`, `plan`, `executed`, `missing_tools`, and `full_log` when commands ran.

A `blocked` status means a required runtime or package manager is unavailable, or no supported bootstrap strategy could be detected.

## Agent Coordination Summary

`agents` reports expose coordination schema `1.0`, a sorted `tasks` list, `active_claims`, the
number of expired claims pruned, and a stable `reason_code`. Task entries contain declared paths,
dependencies, state, timestamps, and an optional claim with agent identity and lease expiry.
Blocked claims use reason codes such as `DEPENDENCIES_INCOMPLETE`, `TASK_CLAIMED`,
`CLAIM_NOT_OWNED`, or `PATH_CONFLICT`.
