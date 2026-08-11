# Performance budgets and diagnostics

`ai-dev` records bounded local stage timings for the operations where regressions most directly
affect agent feedback loops:

- `scan` records configuration, project, workspace, runtime, and summary stages;
- `check --explain` records detection, changed selection, and scheduling;
- `context build --incremental` records repository mapping, Git inspection, validation planning,
  context selection, content collection, report generation, and output writing.

Each CLI invocation stores a schema-versioned JSON record under `.ai/performance/runs/` and updates
`.ai/performance/latest.json`. Records contain command and stage names, durations, tool and machine
versions, and budget results. They never contain repository source, command logs, environment
values, or secrets. Old run records are pruned to the configured retention limit.

## Inspect and compare

~~~bash
ai-dev performance latest --json
ai-dev performance compare .ai/performance/runs/<baseline>.json .ai/performance/runs/<candidate>.json --json
~~~

Comparison requires the same operation on both sides. It reports absolute and percentage changes
for total time and every stage shared by both records. A total regression over 10% is marked
`review_regression`; configured budget violations take precedence as `budget_exceeded`.

## Configure budgets

Budgets are opt-in and expressed in seconds. An operation-level key limits total time; a quoted
`operation.stage` key limits one stage. Exceeding a budget adds the stable
`PERFORMANCE_BUDGET_EXCEEDED` warning without discarding the functional command result.

~~~toml
[performance]
retention = 50

[performance.budgets]
scan = 1.5
"scan.workspace_detection" = 0.5
"check-explain.selection" = 0.4
"context-incremental.context_selection" = 1.0
~~~

Choose budgets from repeated runs on the same class of machine. A single cold run is not a stable
baseline, and records from different operations cannot be compared.