# Reproducible A/B benchmarks

ai-dev benchmark measures two local workflow variants against the same versioned fixture and
validation policy. It never downloads code or sends results anywhere.

## Suite manifest

A suite is a JSON file with schema 1.0:

~~~json
{
  "schema_version": "1.0",
  "name": "agent-workflows",
  "fixture_version": "1",
  "working_directory": ".",
  "reset_command": ["python", "scripts/reset_fixture.py"],
  "validation_command": ["python", "-m", "pytest", "tests/fixture", "-q"],
  "variants": {
    "baseline": ["python", "scripts/run_baseline_workflow.py"],
    "ai-dev": ["ai-dev", "feedback", "--task", "repair fixture"]
  }
}
~~~

Commands are argument arrays and run with shell=False. The manifest is executable local
configuration: review it before running an untrusted repository. The working directory must stay
inside the selected project. Reset and validation commands are mandatory so every trial starts
from the same declared state and ends with independently checked correctness.

## Run and compare

~~~bash
ai-dev benchmark run --suite benchmarks/agent-workflows.json --variant baseline --trials 5 --cache-state cold
ai-dev benchmark run --suite benchmarks/agent-workflows.json --variant ai-dev --trials 5 --cache-state cold
ai-dev benchmark compare .ai/benchmarks/runs/<baseline>.json .ai/benchmarks/runs/<candidate>.json
ai-dev benchmark gate .ai/benchmarks/runs/<baseline>.json .ai/benchmarks/runs/<candidate>.json
ai-dev benchmark corpus --manifest examples/benchmarks/agent-corpus.json --trials 3
ai-dev benchmark run --suite benchmarks/real-codex.json --variant ai-dev --client codex --trials 5
ai-dev benchmark gate <baseline.json> <candidate.json> --require-reported-tokens
~~~

The corpus includes a repeated MCP `build_context` task that compares a forced full refresh with
an explicitly acknowledged unchanged receipt. Both variants must retain the same outcome,
precision, and recall while the receipt satisfies the configured token-reduction threshold.

Cold and warm results are compared within the same cache state. Give a suite an optional
`warmup_command` array to prime the cache after each reset and before each measured warm trial.
The warmup must succeed. Its time is recorded separately. Existing suites without a warmup
report `cache_preparation: reset_only`; use their reset semantics when interpreting the label.
A comparison requires the same suite, fixture version, cache preparation, and outcome signatures.

Each run records median and nearest-rank p95 for end-to-end and measured execution time,
time to an actionable result, standard deviation,
commands, validation subprocesses, masked agent-visible bytes, estimated tokens, timeouts,
correctness, fixture identity, and a local machine profile. Token estimates use
masked_utf8_bytes_divided_by_4; they are a stable approximation, not a model tokenizer claim.
Raw JSON and compact Markdown reports stay under `.ai/benchmarks/`.

`benchmark gate` fails when correctness differs, candidate time or token regressions exceed their
bounds, required token reduction is not achieved, precision/recall fall below their floors, or false negatives exceed the allowance. Use
`--min-token-reduction PERCENT` to require a measured improvement rather than merely permitting no
regression. The
versioned corpus runs seven scripted agent tasks, including adaptive-off versus adaptive-on
context selection and full versus session-delta feedback, and applies the shared thresholds from
`examples/benchmarks/agent-corpus.json`; it is suitable as a CI release gate.

A suite variant may emit one private `AI_DEV_BENCHMARK_METRICS=` JSON line on stderr to
report its real command count, validation subprocess count, and time to its first actionable
result. It may additionally report `iterations`, `files_read`, `selected_items`,
`relevant_items`, `true_positive_items`, `false_negative_items`, `input_tokens`, and
`output_tokens`. The runner derives selection precision and recall, preserves false-negative
counts, and compares their medians. A candidate with a recall regression is rejected even when it
is faster or smaller. The runner validates and removes the private line before counting
agent-visible bytes. Missing or invalid metrics safely fall back to generic measurements and are
never presented as exact model-token counts. `selection_metric_trials` is zero when precision and
recall were not reported; their zero medians must not be interpreted as measured selection quality.

Use `--client codex|claude|cursor|gemini|generic` to label runs from a real client adapter. A real adapter
should emit `input_tokens` or `output_tokens` in its private metrics line. The
`--require-reported-tokens` gate requires provider-reported usage in every trial of both variants.
Use the same instrumentation in both variants. The gate checks input and output token medians
separately from the estimate gate.

Every comparison and gate is advisory and requires human approval. A passing candidate that is
both faster and smaller returns `adopt_candidate`; a passing tradeoff returns `keep_baseline`; any
correctness, recall, token, time, or reported-usage gate failure returns `rollback_candidate`.
Reports always set `automatic_rollback: false`, so an agent cannot reinterpret the evidence as
permission to change model or client configuration.

## Included suites

`examples/benchmarks/mcp-recurring-status.json` compares recurring project status collection.
`examples/benchmarks/symbol-diff-context.json` compares a broad raw unified diff with the compact,
structured symbol-level summary for the same deterministic source change. Both suites require
successful validation on every trial before their efficiency results may be compared.

A five-trial cold run of `symbol-diff-context` on the Windows development fixture produced a valid
`adopt_candidate` comparison: median agent-visible bytes fell from 2,451 to 566 (-76.91%),
estimated tokens from 613 to 142 (-76.84%), and median duration from 1.052 s to 0.953 s
(-9.41%). These are fixture measurements, not universal performance claims; rerun the suite on
the target repository and machine before making product decisions.
## Versioned agent-workflow fixture

The `examples/benchmarks/fixtures/agent-workflow` fixture and its four manifests exercise the
representative workflows required by the roadmap:

- `agent-repair-workflow.json`: diagnose and repair a tax-calculation defect;
- `agent-affected-workflow.json`: select affected tests from a larger unrelated test set;
- `agent-multiturn-workflow.json`: avoid rereading unchanged context on a second turn;
- `agent-monorepo-workflow.json`: route a changed file to its owning workspace and focused tests.

Every candidate and baseline trial is followed by a separate full-fixture pytest run. Thus a
focused candidate cannot pass merely by omitting a failing unrelated test.

A three-trial cold run on Windows 11 with CPython 3.14 produced the following medians:

| Suite | Baseline tokens | ai-dev tokens | Token change | Time change | Correct trials |
| --- | ---: | ---: | ---: | ---: | ---: |
| repair | 2,221 | 954 | -57.05% | -0.36% | 3/3 + 3/3 |
| affected tests | 140 | 46 | -67.14% | +10.92% | 3/3 + 3/3 |
| multi-turn | 4,435 | 1,897 | -57.23% | +20.01% | 3/3 + 3/3 |
| monorepo | 2,246 | 143 | -93.63% | -6.53% | 3/3 + 3/3 |

The candidate used one additional command in every suite. These measurements therefore support a
large context reduction, but do not claim a universal latency or command-count improvement. They
are a small local sample and should be rerun on each target environment. The sanitized raw trial
rows, comparison metrics, machine profile, fixture version, and estimation method are stored in
[`docs/benchmarks/agent-workflows-windows-py314-2026-08-11.json`](benchmarks/agent-workflows-windows-py314-2026-08-11.json).

To reproduce a suite, run both variants and compare the generated JSON reports:

~~~bash
ai-dev benchmark run --suite examples/benchmarks/agent-repair-workflow.json --variant baseline --trials 3 --cache-state cold
ai-dev benchmark run --suite examples/benchmarks/agent-repair-workflow.json --variant ai-dev --trials 3 --cache-state cold
ai-dev benchmark compare .ai/benchmarks/runs/<baseline>.json .ai/benchmarks/runs/<candidate>.json
~~~

## Repository and real-agent trials

`repository-small.json` and `repository-monorepo.json` use generated Git fixtures. The larger
fixture has 40 Python workspaces and 1,000 workload modules. Each trial measures CLI startup,
scan, index and semantic index, a repeated index invocation, Git inspection after editing a file,
symbol lookup, context building, affected-test planning, and MCP startup plus `project_status`.
The validator independently checks fixture coverage, the edited file hash, old/new symbols,
cache reuse, the expected test selection, and the MCP result. Baseline forces repository index
rebuilds, while the candidate updates incrementally. The optional warmup builds both indexes.

Run both variants for each cache state and size, serially in a given checkout. Use 20 or more
trials for tail analysis. A nearest-rank p95 from three trials is the maximum of those three.

~~~bash
ai-dev benchmark run --suite examples/benchmarks/repository-small.json --variant baseline --cache-state cold --trials 3 --timeout 120
ai-dev benchmark run --suite examples/benchmarks/repository-small.json --variant ai-dev --cache-state cold --trials 3 --timeout 120
ai-dev benchmark compare <baseline-run.json> <ai-dev-run.json>
ai-dev benchmark gate <baseline-run.json> <ai-dev-run.json>
~~~

`real-agent-repair.json` runs a disposable synthetic repair through a locally configured agent
driver. Set `AI_DEV_BENCHMARK_AGENT_CONFIG` to an absolute JSON file with `baseline` and `ai-dev`
argument arrays for that driver. The process starts in the disposable fixture and receives
`AI_DEV_BENCHMARK_PROMPT` and `AI_DEV_BENCHMARK_VARIANT`. Keep the same prompt, model version,
permissions and instrumentation on both sides. Enable ai-dev only for the candidate. Configure
the requested client and any provider access outside the harness. The separate validator checks
the edited function with held-out pricing and normalization cases.

Run both variants with `--client <client> --cache-state cold` and pass the resulting reports to
`benchmark gate --require-reported-tokens`. The driver should record per-tool elapsed time and
source reads from local client events in its own sanitized trial log, and emit counts and actual
provider input/output usage through `AI_DEV_BENCHMARK_METRICS`. Derive selection metrics from
fixture ground truth. Keep missing measurements unavailable and record pricing version, cached
input and provider-specific usage separately if calculating cost. The supplied real-agent fixture
resets to a cold local state. A real-agent warm protocol and matched cost study are tracked in #133.
