# Report Schema

Current schema version: `1.0`.

Required fields:

```json
{
  "schema_version": "1.0",
  "tool_version": "0.1.0",
  "status": "success",
  "command": "check",
  "started_at": "ISO-8601",
  "finished_at": "ISO-8601",
  "duration_seconds": 1.23,
  "project_root": "...",
  "summary": {},
  "issues": [],
  "artifacts": []
}
```

Do not remove or rename existing fields without increasing `schema_version`.


## Check Result Summary

`check` command entries include compact log-derived fields so agents do not need to read full logs by default:

```json
{
  "command": "python -m pytest",
  "exit_code": 0,
  "duration_seconds": 1.23,
  "timed_out": false,
  "full_log": ".ai/logs/check-...log",
  "tests_total": 23,
  "passed": 23,
  "failed": 0,
  "skipped": 0,
  "errors": 0,
  "first_failure_reason": null,
  "first_project_frame": null,
  "grouped_repeated_messages": []
}
```

`check --mode changed` also includes `changed_analysis`. Version 0.1.0 uses a conservative `broad_fallback` strategy unless a reliable dependency/test map is available.
