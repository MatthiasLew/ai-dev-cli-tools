# Token-efficiency research for coding agents

This document records how external research and provider guidance informed implemented `ai-dev`
features. It distinguishes fewer model input tokens from lower billed input through provider
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

**Status: implemented.** Use `ai-dev context build --retrieval auto|always|never --explain`.
Reports expose the decision, confidence, reason code, signals, omitted candidates, expansion
evidence, and a related-test false-negative proxy.

### 2. Cache-friendly stable prefixes

Provider prompt caches require exact reusable prefixes. OpenAI and Anthropic both recommend putting
stable tool definitions, instructions, and shared context before variable user/task content.
Therefore agent integrations should emit deterministic sections in this order:

1. protocol and tool schema version;
2. stable project identity and capabilities;
3. content-addressed repository facts and symbol references;
4. variable Git state, failures, task, and latest tool observations.

**Status: implemented.** `ai-dev cache layout` emits the `cache_layout` contract with a stable
prefix fingerprint and recommended breakpoint positions. The stable prefix excludes timestamps,
absolute paths, random evidence IDs, and volatile ordering. Provider-reported cached-token usage is
recorded only when supplied by an integration.

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

**Status: implemented.** The observation lifecycle retains live failures, warnings, and final
verification while replacing superseded results with expandable content-addressed references. This
makes provider guidance on compaction and tool-result clearing provider-neutral and auditable.

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

**Status: implemented.** `context build --refine`, `--refinement-rounds`, and
`--refinement-max-files` provide bounded deterministic refinement.

### 5. Exact token accounting and class budgets

Keep raw UTF-8 bytes as the provider-neutral baseline, but optionally use the tokenizer selected by
an integration. Record input, tool-result, cached-input, cache-write, and output tokens separately.
Apply independent budgets to source, diffs, tests, logs, repository maps, and history so one noisy
class cannot consume the entire pack.

**Status: implemented.** Optional exact local tokenizers, provider usage normalization, and
per-category budgets cover source, diffs, tests, logs, maps, history, cached input, and output.
Defaults remain explicit and benchmarkable rather than inferred from provider claims.

### 6. Optional semantic prompt compression

LLMLingua and LLMLingua-2 show that learned prompt compression can reduce prose-heavy prompts, but
it adds a model/runtime dependency and can alter exact content. It is not part of the supported core
path.

Safe scope:

- allow compression for prose documentation and repetitive natural-language logs;
- never compress source code, patches, stack-frame locations, commands, JSON, secrets, hashes, or
  final verification evidence;
- retain the original locally behind an evidence ID;
- reject compressed output when it is larger;
- benchmark task correctness and end-to-end latency, including compression overhead.

The supported implementation is deliberately limited to deterministic prose and repetitive-log
deduplication. Learned/model-based compression remains deferred because it adds a model dependency
and cannot guarantee preservation of the exact evidence contract.

## Implementation outcome

1. Selective retrieval with explainable abstention and conservative fallback is implemented.
2. Observation lifecycle replacement uses expandable content-addressed evidence.
3. `cache layout` emits a deterministic stable-prefix manifest and breakpoint recommendations.
4. Exact optional tokenizer/provider accounting and per-category budgets are implemented.
5. Bounded hierarchical refinement uses failures, changed symbols, dependencies, and evidence IDs.
6. `--compression conservative` provides deterministic, fail-closed prose/log deduplication.
   Learned/model-based paraphrasing remains disabled after evaluation because it cannot yet preserve
   the required exact evidence contract.

## Sources

- [OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic prompt caching guide](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic context-window and compaction guidance](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793)
- [Repoformer: Selective Retrieval for Repository-Level Code Completion](https://arxiv.org/abs/2403.10059)
- [RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation](https://arxiv.org/abs/2303.12570)
- [Microsoft Research: LLMLingua](https://www.microsoft.com/en-us/research/project/llmlingua/llmlingua/)
- [LLMLingua-2](https://arxiv.org/abs/2403.12968)
