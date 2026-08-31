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
~~~

Cold and warm results are deliberately separate and cannot be compared with each other. A
comparison is valid only when the suite name, fixture version, cache state, and validated outcome
signatures match and every trial succeeds.

Each run records median end-to-end time, time to an actionable result, standard deviation,
commands, validation subprocesses, masked agent-visible bytes, estimated tokens, timeouts,
correctness, fixture identity, and a local machine profile. Token estimates use
masked_utf8_bytes_divided_by_4; they are a stable approximation, not a model tokenizer claim.
Raw JSON and compact Markdown reports stay under `.ai/benchmarks/`.

`benchmark gate` fails when correctness differs, candidate time or token regressions exceed their
bounds, precision/recall fall below their floors, or false negatives exceed the allowance. The
versioned corpus runs all four representative agent tasks and applies the shared thresholds from
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
