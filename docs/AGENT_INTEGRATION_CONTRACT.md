# Coding Agent Integration Contract

The supported integration surfaces are the `ai-dev` command line, report schema `1.1`, and the
local `ai-dev mcp serve` STDIO server.
Integrations must request JSON with `--json` and must not parse Markdown or terminal prose.

## Stability

- `schema_version`, `command`, `status`, `exit_code`, `summary`, `issues`, `artifacts`, and
  `metadata` are stable top-level fields for schema 1.x.
- Consumers must ignore unknown fields and tolerate new enum values.
- Paths are native absolute paths in artifacts and project-relative paths in repository data.
- `success`, `partial`, and `warning` are non-error CLI outcomes; other statuses return nonzero.
- Breaking removals or type changes require a schema-major change.

## Recommended loop

1. Run `ai-dev cache layout --json` once per content state and place its stable sections before task-specific content at the recommended breakpoint.
2. Prefer `ai-dev feedback --task "<task>" --json` for the normal compact loop.
3. Inspect `decision`, `changes`, `validation`, `context`, `observations`, and `performance`.
4. Use `ai-dev session status --json` after an interrupted handoff.
5. Read `metadata.progressive.references` and call `ai-dev explain <evidence-id> --json` only for needed evidence.
6. Use failure signatures to deduplicate retries and optionally compare a named local baseline.
7. Treat FLAKY_PASS and checks_flaky as unresolved warning evidence; never report them as a clean first-pass success.
8. Before handoff, run `ai-dev finish --json`.

All acceleration state is local under `.ai/`; no command transmits repository contents or
metrics.

## MCP integration

Use the local MCP server when the agent supports structured tools. Tool results contain concise
text and machine-readable `structuredContent`; consumers should prefer the structured data.

- Call `project_status` before planning broad repository work.
- Use `feedback`, `build_context`, and `run_checks` in their preview-only defaults.
- Set execution or artifact-writing flags only when the task requires them.
- Expand one stable ID with `explain_evidence` instead of requesting full logs.
- Treat tool names and required fields as compatibility contracts.
- Ignore new optional fields and new tools.
- Respect MCP annotations and the configured client approval policy.

See `MCP_SERVER.md` for setup and complete safety boundaries.
