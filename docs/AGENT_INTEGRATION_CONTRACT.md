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

1. Run `ai-dev scan --json` and `ai-dev diagnostics --json` once.
2. Build `ai-dev context build --profile minimal --incremental --json`.
3. Execute `ai-dev check --mode changed --jobs 4 --json`.
4. Follow `artifacts` for full evidence; use failure signatures to deduplicate retries.
5. Before handoff, run `ai-dev finish --json`.

All acceleration state is local under `.ai/`; no command transmits repository contents or
metrics.