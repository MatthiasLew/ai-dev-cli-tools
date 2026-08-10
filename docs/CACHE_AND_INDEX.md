# Repository Index and Validation Cache

`ai-dev` keeps local, disposable acceleration state under `.ai/cache/`. No repository content or telemetry is transmitted.

## Repository index

```bash
ai-dev index status
ai-dev index update
ai-dev index rebuild
```

The schema-versioned index records relative path, size, modification time, and SHA-256 for eligible project files. An update reuses hashes when size and modification time are unchanged; rebuild hashes every eligible file. Generated, dependency, VCS, fixture, and `.ai` paths are excluded. Deleting the index is safe because it can always be rebuilt.

## Validation cache

Successful, non-timeout check results are cached by default. A cache key includes repository content, workspace, exact command, operating system, machine architecture, and Python runtime. A changed input produces a different key; failures and ambiguous entries are never reused.

```bash
ai-dev check --mode changed
ai-dev check --mode full --no-cache
ai-dev cache status
ai-dev cache prune
ai-dev cache clear
```

Reports expose `cached` per result and `cache_hits` in the execution summary. Each cache hit still produces a run-local log reference. Storage is automatically pruned to the newest 200 validation entries and at most 100 MiB. `cache prune` reapplies those limits; `cache clear` removes validation-result entries but leaves the repository index and context manifest intact.

## Incremental context

`ai-dev context build --incremental` uses the same repository index and a separate schema-versioned context manifest. Only changed candidate files are emitted. Files omitted because of the file budget remain pending for a later run rather than being incorrectly marked as delivered.