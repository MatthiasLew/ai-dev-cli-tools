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
