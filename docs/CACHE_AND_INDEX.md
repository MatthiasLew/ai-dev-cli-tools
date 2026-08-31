# Repository Index and Validation Cache

`ai-dev` keeps local, disposable acceleration state under `.ai/cache/`. No repository content or telemetry is transmitted.

## Repository index

```bash
ai-dev index status
ai-dev index update
ai-dev index rebuild
```

The schema-versioned index records relative path, size, modification time, SHA-256, and a bounded local impact graph for eligible project files. Import and source-to-test edges are recomputed only for changed files and reused for unchanged files. An update reuses hashes when size and modification time are unchanged; rebuild hashes every eligible file. Generated, dependency, VCS, fixture, and `.ai` paths are excluded. Deleting the index is safe because it can always be rebuilt.

`ai-dev index daemon start` launches a detached background process. Native filesystem events are
debounced into incremental index updates, so there is no periodic full-tree scan. Control uses an
authenticated loopback-only IPC socket and keeps private lifecycle state in
`.ai/cache/index-daemon.json`.

```bash
ai-dev index daemon start
ai-dev index daemon status
ai-dev index daemon stop
```

For CI and process supervisors, `ai-dev index daemon foreground --max-updates 2` retains the old
bounded foreground mode.

`ai-dev semantic index --backend auto` builds a separate bounded symbol index at
`.ai/cache/semantic-index.json`. With the `semantic` extra installed, `auto` uses a real
Tree-sitter AST parser; otherwise the dependency-free structural parser is the safe fallback.
`--backend lsp` starts a locally installed language server over JSON-RPC/stdio and requests
document symbols for supported files.
Installed providers may register the `ai_dev_tools.semantic_backends` Python entry-point group;
they are loaded only when explicitly named. `semantic status` reports available providers and
locally discovered language-server executables. An explicitly selected unavailable backend fails
visibly; `auto` remains local and deterministic.

## Prompt cache layout

```bash
ai-dev cache layout --json
```

This writes `.ai/cache/cache-layout.json`. The manifest defines a deterministic section order:
protocol, project identity, content-addressed repository facts, then volatile Git state, task,
current observation, and model response. It fingerprints every stable section and the combined
stable prefix. OpenAI, Anthropic, and provider-neutral recommendations place the cache breakpoint
after repository facts and before volatile content.

The manifest is relocatable and contains no absolute paths, timestamps, random IDs, or repository
contents. Configuration and repository identities use project-relative paths and SHA-256 values.
Re-running it with identical contents produces the same manifest; changing repository content
invalidates the repository and combined-prefix fingerprints while leaving unchanged section
fingerprints reusable. `diagnostics` and MCP `project_status` report whether a layout is available
and its current stable-prefix fingerprint.

## Validation cache

Successful, non-timeout check results are cached by default. A cache key includes repository content, workspace, exact command, operating system, machine architecture, and Python runtime. A changed input produces a different key; failures and ambiguous entries are never reused.

```bash
ai-dev check --mode changed
ai-dev check --mode full --no-cache
ai-dev cache status
ai-dev cache prune
ai-dev cache clear
```

Reports expose `cached` and `reuse` (`executed`, `cached`, or `resumed`) per result and `cache_hits` in the execution summary. A schema-versioned checkpoint under `.ai/cache/check-checkpoint.json` records completed exact fingerprints; stale fingerprints cannot resume after repository, command, workspace, platform, or runtime changes. Each cache hit still produces a run-local log reference. Storage is automatically pruned to the newest 200 validation entries and at most 100 MiB. `cache prune` reapplies those limits; `cache clear` removes validation-result entries but leaves the repository index and context manifest intact.

## Incremental context

`ai-dev context build --incremental` uses the same repository index and a separate schema-versioned
context manifest. Only changed candidate files are emitted. The latest manifest is accompanied by
up to 50 content-addressed historical manifests; `--since <context-id>` selects a retained manifest
as the explicit comparison base. Files omitted because of the file budget remain pending for a
later run rather than being incorrectly marked as delivered.
