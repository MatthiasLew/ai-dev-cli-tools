# TODO

This file contains only active implementation work. The 1.0 backlog was implemented and moved to
`CHANGELOG.md`; product status and rationale are recorded in
`docs/AGENT_EFFICIENCY_ROADMAP.md`.

An item is complete only when implementation, tests, user documentation, report contracts, and
cross-platform behavior are covered where applicable.

## Active work

The [development tracker](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/144) links to
current acceptance criteria. The roadmap documents the capabilities shipped in the 1.x contracts.

| Priority | Issues |
| --- | --- |
| P0 | [MCP metadata #131](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/131), [correctness gate #134](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/134), [agent measurement #133](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/133) |
| P1 | [Node diagnostics #128](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/128), [repository navigation #136](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/136), [MCP symbol lookup #137](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/137), [module responsibilities #135](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/135), [adoption #138](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/138), [failure loops #139](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/139), [affected tests #140](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/140) |
| P2 | [Verified repository knowledge #141](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/141), [FTS5 evaluation #142](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/142), [native profiling #143](https://github.com/MatthiasLew/ai-dev-cli-tools/issues/143) |

## Deferred or explicitly out of scope

The following require a separate design and safety review and must not be introduced implicitly:

- automatic commit, push, merge, release, or deployment;
- destructive Git cleanup or repository reset;
- sending source code, logs, metrics, or secrets to a remote AI service;
- killing arbitrary processes or deleting user-managed runtime data;
- silently installing global tools or changing machine-level configuration;
- learned/model-based semantic compression of code or verification evidence.
