# TODO

This file contains only active implementation work. Completed historical items were removed after
the 0.5.0 alpha foundation was implemented and verified. Product status and rationale are recorded
in `docs/AGENT_EFFICIENCY_ROADMAP.md`; released behavior is recorded in `CHANGELOG.md`.

An item is complete only when implementation, tests, user documentation, report contracts, and
cross-platform behavior are covered where applicable.

## P1 — Complete partial agent workflows

- [ ] Add named historical context selection so incremental builds can compare against an explicit
  prior context ID rather than only the latest manifest.
- [ ] Integrate named baseline comparison directly into check and context workflows while preserving
  the existing `baseline create/list/compare` commands and schema compatibility.
- [ ] Add symbol-targeted evidence expansion without allowing references outside the project root.
- [ ] Add deterministic `implement` and `docs` context profiles with documented budgets, ranking,
  include/exclude precedence, and contract tests.

## P2 — Improve selection and execution precision

- [ ] Extend Java, Rust, and PHP structural adapters only where conservative parsing and fallback can
  be maintained; cover overloads, nested declarations, constructors, and qualified identities.
- [ ] Add generated-code relationships, richer configuration ownership, and shortest reason paths to
  the bounded dependency/impact graph.
- [ ] Extend the parallel scheduler with an explicit dependency graph and conservative local resource
  limits while retaining deterministic report order and `--jobs 1` behavior.
- [ ] Add safe cancellation of obsolete in-flight watch validation, preserving complete logs and
  never terminating processes outside the active watch run.

## Deferred or explicitly out of scope

The following require a separate design and safety review and must not be introduced implicitly:

- automatic commit, push, merge, release, or deployment;
- destructive Git cleanup or repository reset;
- sending source code, logs, metrics, or secrets to a remote AI service;
- killing arbitrary processes or deleting user-managed runtime data;
- silently installing global tools or changing machine-level configuration;
- learned/model-based semantic compression of code or verification evidence.
