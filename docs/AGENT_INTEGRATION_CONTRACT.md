# Coding Agent Integration Contract

The supported integration surface is the `ai-dev` command line and report schema `1.1`.
Integrations must request JSON with `--json` and must not parse Markdown or terminal prose.

## Stability

- `schema_version`, `command`, `status`, `exit_code`, `summary`, `issues`, `artifacts`, and
  `metadata` are stable top-level fields for schema 1.x.
- Consumers must ignore unknown fields and tolerate new enum values.
- Paths are native absolute paths in artifacts and project-relative paths in repository data.
- `success`, `partial`, and `warning` are non-error CLI outcomes; other statuses return nonzero.
- Breaking removals or type changes require a schema-major change.

## Recommended loop

1. Prefer `ai-dev feedback --task "<task>" --json` for the normal compact loop.
2. Inspect `decision`, `changes`, `validation`, `context`, and `performance`.
3. Use `ai-dev session status --json` after an interrupted handoff.
4. Read `metadata.progressive.references` and call `ai-dev explain <evidence-id> --json` only for needed evidence.
5. Use failure signatures to deduplicate retries and optionally compare a named local baseline.
6. Before handoff, run `ai-dev finish --json`.

All acceleration state is local under `.ai/`; no command transmits repository contents or
metrics.