# Report Schema

Current schema version: `1.1`.

Required fields:

```json
{
  "schema_version": "1.1",
  "tool_version": "0.2.0",
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

## Migration From 1.0

Schema 1.1 adds `exit_code` and `metadata`. Consumers should treat missing fields from schema 1.0 as `exit_code: 0` for successful reports and `{}` for metadata. Consumers should accept `partial` where schema 1.0 reports may have used `warning`.

## Check Result Summary

`check` command entries include compact log-derived fields so agents do not need to read full logs by default. Parser results include `tool`, `parser`, `parser_confidence`, counts, first failure, project frames, repeated-message grouping, and full log paths.

`check --mode changed` includes `changed_analysis` with `strategy`, `confidence`, `changed_files`, `selected_tests`, `selected_commands`, and `fallback_reason`.