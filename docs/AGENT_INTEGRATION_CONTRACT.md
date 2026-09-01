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

1. Call `plan_work` or run `ai-dev plan --task "<task>" --json` before broad edits.
2. Run `ai-dev cache layout --json` once per content state and place stable sections before task-specific content at the recommended breakpoint.
3. Prefer `ai-dev feedback --task "<task>" --json` for the normal compact loop.
4. Inspect `decision`, `changes`, `validation`, `context`, `observations`, `delta`, and `performance`.
   Pass the prior `delta.state_fingerprint` as `--ack-state` (or MCP `acknowledged_state`) only
   after consuming that response. When `delta.reused=true`, expand only the evidence required for
   the next decision. Use `--no-delta` when a consumer explicitly requires the repeated payload.
5. Use `ai-dev session status --json` after an interrupted handoff.
6. Read `metadata.progressive.references` and expand only the evidence needed.
7. Use failure signatures to deduplicate retries and optionally compare a named local baseline.
8. Treat flaky passes, low confidence, and recall regressions as unresolved evidence.
9. Before handoff, run `ai-dev finish --json` and a complete validation pass.

All acceleration state is local under `.ai/`; no command transmits repository contents or
metrics.

## MCP integration

Use the local MCP server when the agent supports structured tools. Tool results contain concise
text and machine-readable `structuredContent`; consumers should prefer the structured data.

- Call `project_status`, then `plan_work`, before broad repository work.
- Use `feedback`, `build_context`, and `run_checks` in their preview-only defaults.
- Set execution or artifact-writing flags only when the task requires them.
- Expand one stable ID with `explain_evidence` instead of requesting full logs.
- Treat tool names and required fields as compatibility contracts.
- Ignore new optional fields and new tools.
- Respect MCP annotations and the configured client approval policy.

For repeated `build_context` calls, return the prior `summary.delta.state_fingerprint` as
`acknowledged_state`. A receipt is emitted only when repository contents, request parameters, and
the safe successful state still match. Changed, partial, warning, error, and secret-bearing states
return full live context. Set `delta=false` whenever a complete refresh is required.
- Keep infrastructure retry separate from flaky-test retry; neither may retry code failures.

See `MCP_SERVER.md` for setup and complete safety boundaries.
