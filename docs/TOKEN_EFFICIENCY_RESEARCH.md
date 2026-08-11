# Token-efficiency research for coding agents

This document turns external research and current provider guidance into implementation candidates
for `ai-dev`. It distinguishes fewer model input tokens from lower billed input through provider
caching: cached tokens can cost less and run faster while still occupying the context window.

## Evidence-backed mechanisms

### 1. Selective retrieval and abstention

Do not build a broad repository context pack for every request. First decide whether cross-file
context is necessary from changed paths, task terms, symbol references, failure locations, and
retrieval confidence. If confidence is low, return a small local-file pack plus an explicit offer
to expand.

Repoformer reports that retrieval helped no more than 20% of evaluated instances in its setting;
selective retrieval produced up to 70% inference speedup without harming measured accuracy. Its
exact learned policy is model-specific, but the safe product lesson is applicable: retrieval must
be optional and measured, not automatic.

Recommended interface:

~~~bash
ai-dev context build --retrieval auto|always|never
ai-dev context explain-retrieval
~~~

The report should expose `retrieval_decision`, confidence, signals, omitted candidates, and a
stable expansion command. Benchmarks must measure false-negative selection and final full-test
correctness.

### 2. Cache-friendly stable prefixes

Provider prompt caches require exact reusable prefixes. OpenAI and Anthropic both recommend putting
stable tool definitions, instructions, and shared context before variable user/task content.
Therefore agent integrations should emit deterministic sections in this order:

1. protocol and tool schema version;
2. stable project identity and capabilities;
3. content-addressed repository facts and symbol references;
4. variable Git state, failures, task, and latest tool observations.

Add a `cache_layout` block to the agent contract with a stable prefix fingerprint and recommended
breakpoint positions. Never include timestamps, absolute paths, random evidence IDs, or volatile
ordering in the stable prefix. Record provider-reported cached-token reads/writes when an
integration supplies them; do not claim savings from a local estimate alone.

Prompt caching reduces billed computation and latency, but cached prefixes still occupy the model
context window. It complements rather than replaces context reduction.

### 3. Observation lifecycle and tool-result clearing

Long-running agents should replace obsolete tool output with compact, content-addressed evidence
references. Retain the current failure, the final verification, unresolved warnings, decisions,
and exact expansion handles. Clear superseded successful logs, duplicate scans, old diffs, and
intermediate test progress after their state has been summarized.

The integration contract should describe three states:

- `live`: include bounded content now;
- `referenced`: keep an evidence ID, fingerprint, size, and retrieval command;
- `expired`: content changed and must be recomputed.

Anthropic's current context guidance explicitly recommends compaction and clearing old tool results
for long-running agentic workflows. Local evidence references make the same pattern provider-neutral
and auditable.

### 4. Hierarchical and iterative retrieval

Retrieve in layers rather than returning source immediately:

1. repository/workspace map;
2. file and symbol signatures;
3. selected symbol bodies and nearby tests;
4. raw diff or full logs only on demand.

RepoCoder found that iterative retrieval using the initial generation as a better query improved
repository-level completion over one-shot retrieval. For `ai-dev`, a deterministic alternative is
to refine retrieval after the first failure signature, changed symbol, or requested evidence ID.
Each iteration must have a strict byte/token budget and stop when no new high-confidence evidence
appears.

### 5. Exact token accounting and class budgets

Keep raw UTF-8 bytes as the provider-neutral baseline, but optionally use the tokenizer selected by
an integration. Record input, tool-result, cached-input, cache-write, and output tokens separately.
Apply independent budgets to source, diffs, tests, logs, repository maps, and history so one noisy
class cannot consume the entire pack.

A useful default policy is to reserve most context for task-matched source and failures, retain a
small verification allowance, and leave headroom for the model response. Exact defaults should be
chosen from the versioned A/B benchmark rather than hard-coded from intuition.

### 6. Optional semantic prompt compression

LLMLingua and LLMLingua-2 show that learned prompt compression can reduce prose-heavy prompts, but
it adds a model/runtime dependency and can alter exact content. It should therefore be an optional
adapter, never the default core path.

Safe scope:

- allow compression for prose documentation and repetitive natural-language logs;
- never compress source code, patches, stack-frame locations, commands, JSON, secrets, hashes, or
  final verification evidence;
- retain the original locally behind an evidence ID;
- reject compressed output when it is larger;
- benchmark task correctness and end-to-end latency, including compression overhead.

This feature should remain deferred until deterministic selection, cache layout, and observation
clearing are measured, because those mechanisms add no model dependency and preserve exact data.

## Recommended implementation order

1. Selective retrieval gate with explainable abstention and a conservative fallback.
2. Observation lifecycle with evidence-reference replacement for superseded tool results.
3. Cache-friendly stable-prefix manifest in the agent integration contract.
4. Exact/provider token accounting and per-content-class budgets.
5. Hierarchical retrieval refinement driven by failures and symbol references.
6. Optional semantic compression adapter behind an explicit feature flag.

## Sources

- [OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic prompt caching guide](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic context-window and compaction guidance](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793)
- [Repoformer: Selective Retrieval for Repository-Level Code Completion](https://arxiv.org/abs/2403.10059)
- [RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation](https://arxiv.org/abs/2303.12570)
- [Microsoft Research: LLMLingua](https://www.microsoft.com/en-us/research/project/llmlingua/llmlingua/)
- [LLMLingua-2](https://arxiv.org/abs/2403.12968)
