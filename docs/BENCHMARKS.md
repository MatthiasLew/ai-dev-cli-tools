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
~~~

Cold and warm results are deliberately separate and cannot be compared with each other. A
comparison is valid only when the suite name, fixture version, cache state, and validated outcome
signatures match and every trial succeeds.

Each run records median end-to-end time, time to an actionable result, standard deviation,
commands, validation subprocesses, masked agent-visible bytes, estimated tokens, timeouts,
correctness, fixture identity, and a local machine profile. Token estimates use
masked_utf8_bytes_divided_by_4; they are a stable approximation, not a model tokenizer claim.
Raw JSON and compact Markdown reports stay under .ai/benchmarks/.
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
