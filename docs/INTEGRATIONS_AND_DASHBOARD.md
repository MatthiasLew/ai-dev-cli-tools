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
local report errors, total recorded token savings, the latest delivery mode, and cache-hit state.
The JSON endpoint is `GET /api/status`; no mutation endpoint exists.
