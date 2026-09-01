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
`request_id`. It deliberately cannot accept prompt or response bodies.

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
