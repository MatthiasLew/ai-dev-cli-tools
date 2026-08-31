# TODO

This file contains only active implementation work. The 1.0 backlog was implemented and moved to
`CHANGELOG.md`; product status and rationale are recorded in
`docs/AGENT_EFFICIENCY_ROADMAP.md`.

An item is complete only when implementation, tests, user documentation, report contracts, and
cross-platform behavior are covered where applicable.

## Active work

There are no known incomplete P1 or P2 implementation items for the 1.0 or 1.1 contracts. Adaptive
context work for the next minor line is tracked by tests, documentation, report-contract additions,
and the cross-platform agent corpus rather than an open implementation placeholder.

## Deferred or explicitly out of scope

The following require a separate design and safety review and must not be introduced implicitly:

- automatic commit, push, merge, release, or deployment;
- destructive Git cleanup or repository reset;
- sending source code, logs, metrics, or secrets to a remote AI service;
- killing arbitrary processes or deleting user-managed runtime data;
- silently installing global tools or changing machine-level configuration;
- learned/model-based semantic compression of code or verification evidence.
