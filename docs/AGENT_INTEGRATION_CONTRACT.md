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

1. Prefer MCP `prepare_task` or `ai-dev task --task "<task>" --client <client> --json` for a
   single bounded handoff. Use `plan_work` alone only when context selection is not yet needed.
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
10. When the provider exposes numeric usage, call MCP `record_usage` once after the response.
    Send total input, cache read/write, output and reasoning counts, client, and optional
    model/request ID and optional bounded phase/tool/task-kind labels plus a boolean quality
    outcome; never send prompt or response text. Treat `measurement=provider_reported` as the
    provenance of counts and any
    `cost.kind=local_pricing_estimate` as an estimate, not billed cost.
11. Read `summary.policy` returned by `record_usage`. Stop additional expensive work on active
    violations unless the user explicitly changes the budget. Use read-only `usage_status` before
    a costly phase and `ai-dev telemetry gate --json` in deterministic CI/release gates.
12. Call read-only `optimize_usage` after enough representative sessions. Treat budget output as
    a proposal, never permission to overwrite policy. Never switch to a cheaper model unless the
    recommendation includes sufficient quality samples, meets the accuracy target, proves a
    same-currency saving, and a human or owning agent approves the change.

All acceleration state is local under `.ai/`; no command transmits repository contents or
metrics.

## MCP integration

Use the local MCP server when the agent supports structured tools. Tool results contain concise
text and machine-readable `structuredContent`; consumers should prefer the structured data.

- Call `project_status`, then `plan_work`, before broad repository work.
- Prefer `prepare_task` when one compact call should replace separate planning, context, and check
  discovery calls. File bodies are references by default; request `include_content=true` only on
  demand.
- Use `feedback`, `build_context`, and `run_checks` in their preview-only defaults.
- Set execution or artifact-writing flags only when the task requires them.
- Expand one stable ID with `explain_evidence` instead of requesting full logs.
- Treat tool names and required fields as compatibility contracts.
- Ignore new optional fields and new tools.
- Use `record_usage` only with usage returned by the provider. Do not substitute tokenizer or
  character estimates, because estimated context savings and provider-reported consumption are
  separate measurements.
- Treat `TELEMETRY_REGRESSION_INSUFFICIENT_DATA` as informational. Treat budget, cost-data, and
  regression violations as unresolved until the policy or measured workload changes.
- Treat every `MODEL_ROUTING_*` gap as evidence that routing must remain unchanged. A
  `MODEL_ROUTING_RECOMMENDATION` is advisory and never grants permission to mutate client config.
- Respect MCP annotations and the configured client approval policy.

For repeated `build_context` calls, return the prior `summary.delta.state_fingerprint` as
`acknowledged_state`. A receipt is emitted only when repository contents, request parameters, and
the safe successful state still match. Changed, partial, warning, error, and secret-bearing states
return full live context. Set `delta=false` whenever a complete refresh is required.
- `prepare_task` accepts `client=codex|claude|cursor|generic`. Persisted acknowledgement state is
  updated only when the caller explicitly supplies `acknowledged_state` with `persist_ack=true`.
- Keep infrastructure retry separate from flaky-test retry; neither may retry code failures.

See `MCP_SERVER.md` for setup and complete safety boundaries.
