# Agent workflow

The recommended loop gives an AI agent enough evidence to act without granting broad execution
or forcing it to reread the repository.

## 1. Plan before editing

```bash
ai-dev plan --task "fix authentication timeout" --mode changed --json
```

The plan is preview-only and caps scope at 30 files, 20 symbols, and 50 evidence rows. It reports
intended scope, changed symbols, file risk, dependent actions,
selected validation commands, command-policy decisions, and stable evidence references. It writes
`.ai/reports/agent-plan.json` and `.ai/reports/agent-plan.md`. MCP clients should call
`plan_work` for the same contract.

## 2. Retrieve bounded context

Use `context build --profile implement` for code changes and `--profile docs` for documentation.
Prefer `--incremental`, task text, or explicit evidence IDs. Expand one uncertainty with
`ai-dev explain <evidence-id>` instead of requesting a full tree or log.

The optional semantic index is local and deterministic:

```bash
ai-dev semantic status
ai-dev semantic index --backend auto
```

`auto` uses the built-in structural parser unless an explicitly supported provider is selected.
Third-party providers register the `ai_dev_tools.semantic_backends` entry-point group and expose
an `index(project_root, paths)` method returning bounded symbol objects. Provider code runs in the
local process and therefore must be trusted like any development dependency.

## 3. Assess commands before execution

```bash
ai-dev policy assess -- python -m pytest tests/unit -q --json
```

Configure `[execution]` in `.ai-dev-tools.toml`. `audit` reports decisions without blocking;
`enforce` applies allow/deny prefixes and `maximum_impact` to checks, bootstrap, and application
startup. Argument arrays are always executed without a shell. Policy does not turn an untrusted
repository into a trusted one; review project configuration before running it.

## 4. Validate narrowly, then completely

```bash
ai-dev check --mode changed --policy feedback-first --retry-infra 1 --json
ai-dev check --mode full --jobs 4 --json
```

Only failures classified as transient infrastructure are retried automatically. Code,
environment, policy, cancellation, and timeout failures are not hidden by retry. Recovered runs
retain their initial output and attempt count. Flaky-test retry remains separate and opt-in through
`--retry-flaky`.

## 5. Publish compact evidence

```bash
ai-dev sarif --input .ai/reports/check-latest.json --output .ai/reports/ai-dev.sarif
```

SARIF conversion is project-scoped, secret-masked, capped at 10 MB input and 5,000 results, and
does not contact GitHub. CI may upload the result to code scanning and place the readable plan in
the job summary. Full logs remain local artifacts and should be opened only for a failed evidence
reference.

## Recommended agent defaults

- Start with `project_status` or `plan_work`, not an unbounded repository read.
- Keep execution preview-only until the user or client policy allows it.
- Use `implement` or `docs` context profiles and stable evidence IDs.
- Treat low confidence, truncation, and recall regressions as reasons to broaden validation.
- Run a full validation pass before claiming completion.
- Never infer permission to commit, push, merge, publish, deploy, or delete from these tools.
