# Client integrations and local dashboard

Generate project-scoped MCP configurations without sending repository data anywhere:

```bash
ai-dev integrations install all
ai-dev integrations install codex
ai-dev integrations install claude
ai-dev integrations install cursor
```

The generated files are `.codex/config.toml`, `.mcp.json`, `.cursor/mcp.json`, and
`mcp.ai-dev.json`. Matching reference-first task profiles are written to `.ai-dev/clients/`.
Existing files are preserved unless `--force` is explicitly supplied. Each
configuration launches the same Python environment as the installer via stdio and pins the
project root, which avoids working-directory ambiguity.

The health dashboard binds only to a loopback address:

```bash
ai-dev dashboard serve --host 127.0.0.1 --port 8765
ai-dev dashboard status --json
```

It shows repository and semantic index size, cache use, daemon and managed-runtime state, recent
local report errors, total recorded token savings, provider-reported token use by client, the
latest delivery mode, and cache-hit state.
The JSON endpoint is `GET /api/status`; no mutation endpoint exists.

## Provider telemetry

Clients with MCP support should call `record_usage` after a completed model response. The tool
accepts `client`, total `input_tokens`, `cached_input_tokens` (cache reads),
`cache_write_input_tokens`, `output_tokens`, `reasoning_tokens`, and optional `model` and
`request_id`. To enable attribution without recording content, clients may also provide bounded
`phase`, `tool_name`, and `task_kind` labels plus a boolean `quality_passed` result from an eval,
test gate, or other application-owned quality check and bounded `duration_seconds`. It deliberately cannot accept prompt or
response bodies.

Existing JSON or JSONL can be imported from inside the project:

```bash
ai-dev telemetry import response.json --client codex --format openai --json
ai-dev telemetry import anthropic.json --client claude --format anthropic --json
ai-dev telemetry import cursor-usage.jsonl --client cursor --format generic --json
ai-dev telemetry status --json
```

`--format auto` recognizes only explicit cache-field signatures. Ambiguous input fails closed and
must use a named format. Imports are limited to 5 MB, reject paths outside the project, deduplicate
provider response IDs inside JSONL, and are idempotent for identical source content. Normalized
sessions under `.ai/token-efficiency/sessions/` contain counts and identifiers only.

Cost calculation is opt-in. Create `.ai-dev/telemetry-pricing.json` or pass `--pricing` with this
shape:

```json
{
  "currency": "USD",
  "models": {
    "gpt-example": {
      "input_per_million": 2.0,
      "cached_input_per_million": 0.5,
      "cache_write_input_per_million": 2.5,
      "output_per_million": 8.0
    }
  }
}
```

Use actual contracted rates. Prices are intentionally not bundled because provider, model,
service-tier, and account terms change. Dashboard cost values are labeled
`local_pricing_estimate`; they are not billing records. The OpenAI Responses adapter follows the
official `usage.input_tokens`, `usage.input_tokens_details.cached_tokens`,
`usage.output_tokens`, and `usage.output_tokens_details.reasoning_tokens` fields documented in the
[OpenAI Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create).
For Anthropic, total normalized input is the sum of uncached input, cache creation, and cache read
fields as specified by the
[Anthropic pricing and usage documentation](https://docs.anthropic.com/en/docs/about-claude/pricing).

## Versioned pricing snapshots

Importing a cennik creates an immutable project-local snapshot and, unless `--no-activate` is
used, updates the active pointer:

```bash
ai-dev telemetry pricing import pricing.json \
  --provider openai \
  --version 2026-09-01 \
  --source https://developers.openai.com/api/docs/models/compare
ai-dev telemetry pricing import pricing.json --provider openai --version candidate --no-activate
ai-dev telemetry pricing activate openai candidate
```

Snapshots live under `.ai-dev/pricing/<provider>/<version>.json`. Reusing a version with different
content fails closed. Activation verifies the snapshot hash and writes only a project-relative
pointer to `.ai-dev/telemetry-pricing.json`. Every newly priced session records the provider,
version, and snapshot hash that produced its local estimate. This is important because official
model pricing can include cached-input rates, long-context thresholds, or promotional periods;
the [OpenAI model comparison](https://developers.openai.com/api/docs/models/compare) is the source
to review before creating an OpenAI snapshot.

## Budgets and regressions

Create `.ai-dev/telemetry-budgets.json`:

```json
{
  "schema_version": "1",
  "window_sessions": 20,
  "limits": {
    "max_total_tokens": 200000,
    "max_estimated_costs": {"USD": 5.0}
  },
  "clients": {
    "codex": {"max_input_tokens": 120000}
  },
  "models": {
    "gpt-example": {"max_output_tokens": 20000}
  },
  "regression": {
    "recent_sessions": 5,
    "min_baseline_sessions": 5,
    "max_total_tokens_percent": 20,
    "max_estimated_cost_percent": 25,
    "currency": "USD"
  }
}
```

Run `ai-dev telemetry gate --json` in CI. Limits aggregate over the newest chronological
`window_sessions`. Regression compares the average of the newest `recent_sessions` with the
immediately preceding baseline window. Too little history produces an informational
`TELEMETRY_REGRESSION_INSUFFICIENT_DATA`; it does not fail the gate. A configured cost limit or
cost regression fails closed when any evaluated session lacks a matching currency estimate.
`record_usage` and `telemetry import` return `partial` with `TELEMETRY_ALERT` after storing valid
usage that breaches policy, so the next AI step can stop without losing the evidence.

## Token optimizer

```powershell
ai-dev telemetry optimize --min-sessions 5 --percentile 95 `
  --safety-margin-percent 20 --accuracy-target-percent 95 --json
```

The report attributes token usage, cache share, local estimated cost, and quality outcomes by
client, model, phase, tool, and task kind. Budget suggestions use the nearest-rank percentile of
per-session total tokens plus the requested safety margin. Nothing is written back to the budget
policy.

Model routing is deliberately accuracy-first. The most-used model for a task kind is treated as
the incumbent. A cheaper candidate is suggested only when both models have the minimum number of
quality-labelled sessions, the incumbent and candidate meet the target, the allowed accuracy drop
is respected, and every compared sample has a same-currency local cost estimate. Otherwise the
report returns a stable `MODEL_ROUTING_*` evidence-gap code. This follows the official
[OpenAI model selection guidance](https://developers.openai.com/api/docs/guides/model-selection):
establish the accuracy target first, then optimize cost and latency while maintaining it.

Neither CLI nor MCP automatically changes the selected model. Every routing recommendation
contains `requires_human_approval: true` and `automatic_switch: false`.

Use `ai-dev telemetry export --format json|csv --output <project-path>` to share aggregated
optimizer evidence. The export contains daily and dimensional totals, percentiles, quality,
latency, cache share, and local cost estimates. It never includes request IDs, prompts, responses,
or repository content and refuses to overwrite an existing file.
