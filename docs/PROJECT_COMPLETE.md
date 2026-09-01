# Project completion and maintenance boundary

The planned `ai-dev` product capability set is complete in version 1.2.0. Complete means the local
CLI, MCP contract, context reduction, validation orchestration, semantic indexing, runtime
supervision, agent corpus, telemetry budgets, and evidence-based optimizer are implemented,
documented, packaged, and protected by cross-platform CI. It does not mean defects or ecosystem
changes can never occur.

## Closure acceptance

A release is eligible for final promotion only when all of the following are true:

- Ruff, strict mypy, the complete pytest suite, and at least 90% coverage pass.
- Wheel and sdist build from the release commit and the wheel passes an isolated install smoke test.
- Linux, Windows, and macOS pass on every supported Python version.
- The versioned real-agent corpus preserves correctness, precision, recall, and zero disallowed
  false negatives while meeting token and time gates.
- Telemetry exports contain only bounded aggregate evidence and no prompt, response, request ID,
  repository content, or secret.
- Managed background processes publish authenticated starting, running, failed, and terminal states
  and never kill an unrelated process.
- The release commit is on `main`, the worktree is clean, and no implementation PR or P1/P2 issue
  remains open.

## Maintenance mode

After 1.2.0, accept changes only for security, correctness, supported platform/toolchain drift,
dependency maintenance, reproducible performance regressions, or backward-compatible integration
updates. New overlapping commands, remote source transmission, automatic Git/release/deployment,
automatic model switching, learned code compression, and destructive cleanup remain outside the
completed product contract unless a separate safety design explicitly changes that boundary.

Provider quality, price, and latency evidence remains workload-specific. The optimizer may advise
adopt, keep, or rollback, but a human or owning agent must approve every policy or routing change.
