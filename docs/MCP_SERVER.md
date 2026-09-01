# Local MCP server

`ai-dev mcp serve` exposes the existing project analysis workflow as focused Model Context
Protocol tools over local STDIO. It does not use an OpenAI API, listen on a network port, or
transmit repository contents.

The server implements MCP protocol version `2025-06-18`. Each request and response is one
UTF-8 JSON-RPC object per line. Normal startup writes no banner or diagnostic text to stdout.

## Connect Codex

Install the package first:

```bash
pipx install ai-dev-cli-tools
```

Register one repository with Codex:

```bash
codex mcp add ai-dev -- ai-dev --project "/absolute/path/to/project" mcp serve
codex mcp list
```

Restart the Codex client after changing MCP configuration. The ChatGPT desktop app, Codex CLI,
and Codex IDE extension share MCP configuration on the same Codex host.

A project-scoped `.codex/config.toml` can express the same setup for a trusted repository:

```toml
[mcp_servers.ai_dev]
command = "ai-dev"
args = ["--project", ".", "mcp", "serve"]
cwd = "/absolute/path/to/project"
default_tools_approval_mode = "writes"
startup_timeout_sec = 10
tool_timeout_sec = 300
```

The official Codex MCP configuration reference is available in the
[Codex MCP documentation](https://developers.openai.com/codex/mcp/).

## Tools

| Tool | Purpose | Default behavior | MCP annotation |
| --- | --- | --- | --- |
| `plan_work` | Scope, risk, dependencies, validation, and policy assessment | Preview-only; writes bounded plan artifacts | local write |
| `project_status` | Project technology, Git state, cache/index health, and diagnostics | Read-only and does not write reports | read-only |
| `feedback` | Changes, validation state, failures, timings, bounded context, and session deltas | Plans checks unless `execute_checks=true`; a receipt requires the prior `acknowledged_state`, and `delta=false` forces full output | local write |
| `build_context` | Task-relevant files, symbols, diffs, tests, adaptive budgets, and evidence | Preview-only unless `write_artifacts=true`; return `delta.state_fingerprint` as `acknowledged_state` for an unchanged receipt, or set `delta=false` for full live context | local write |
| `run_checks` | Deterministic validation plan or execution | Plans checks unless `execute=true`; retries transient infrastructure failures once by default | local write |
| `coordinate_agents` | Register, claim, renew, release, complete, or inspect local tasks | Mutates local coordination state | local write |
| `explain_evidence` | Expand one stable evidence ID | Read-only | read-only |

Tool results use a one-line text status plus `structuredContent`. The text does not duplicate
the full report, which keeps agent-visible output smaller. Existing report summaries, reason
codes, bounded context, secret masking, and evidence IDs remain the source contracts.

## Safety

- The project root is fixed when the server starts; tools cannot select another root.
- Inputs use strict JSON Schemas with bounded strings, character budgets, files, jobs, retries,
  and evidence length.
- No tool accepts a shell command, executable, URL, environment mutation, Git write, release,
  deployment, or deletion request.
- Validation execution is opt-in per call.
- Context and feedback continue to exclude sensitive paths and mask detected secrets.
- `readOnlyHint`, `destructiveHint`, and `openWorldHint` describe actual behavior;
  they do not replace client approval policy.
- Protocol errors never include tracebacks, source contents, tokens, or unmasked exceptions.

The server exits cleanly when its STDIO input closes. Use the client process lifecycle rather
than running it as an unsupervised background daemon.

## Compatibility and testing

The source test suite verifies initialization, tool discovery, notifications, parse errors,
strict arguments, preview defaults, read-only status behavior, concise structured results, CLI
wiring, and installed-wheel initialization. MCP tool names and required input fields should
remain backward compatible within the 1.x release line.

For manual inspection, use an MCP Inspector that supports local STDIO and call every tool with
both representative and invalid inputs. The official implementation guidance recommends focused
tools, explicit schemas, concise structured results, accurate annotations, and keeping secrets
out of metadata and results:
[Build an MCP server](https://developers.openai.com/plugins/build/mcp-server).
## Reproducible benchmark

The versioned `examples/benchmarks/mcp-recurring-status.json` suite compares three separate
CLI status processes with one recurring MCP `project_status` call. It measures agent-visible
bytes and process time while requiring the same validation outcome.

```bash
ai-dev benchmark run --suite examples/benchmarks/mcp-recurring-status.json --variant baseline --trials 5
ai-dev benchmark run --suite examples/benchmarks/mcp-recurring-status.json --variant ai-dev --trials 5
ai-dev benchmark compare .ai/benchmarks/runs/<baseline>.json .ai/benchmarks/runs/<candidate>.json
```

MCP schema discovery is a separate one-time session cost and is intentionally not counted as a
recurring tool-call payload. Record it separately when evaluating cold client startup.
