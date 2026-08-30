# `ai-dev check --mode full` failure for AdaptiveChessAI

## Summary

`ai-dev check --mode full --no-cache` returned a failed report for
`AdaptiveChessAI` even though the root project checks completed successfully.
The tool incorrectly detected the ignored virtual-environment copy of pandas as
a second workspace and then crashed while printing its report on a CP1250
console.

## Environment

- Date: 2026-08-30
- OS: Windows
- Console encoding: CP1250
- Python selected by ai-dev: 3.14
- ai-dev-cli-tools: 0.5.0a1
- Project: `C:\Users\Praca\fork\MatthiasLew\AdaptiveChessAI`

## Command

```powershell
ai-dev --project "C:\Users\Praca\fork\MatthiasLew\AdaptiveChessAI" `
  check --mode full --no-cache
```

## Observed problems

### 1. Ignored virtual environment detected as a workspace

The plan contained two workspaces:

```text
<project root>
venv/Lib/site-packages/pandas
```

The second path is an installed dependency inside the project's ignored
`venv/` directory and must not be treated as a project workspace.

This caused irrelevant checks to run against pandas, including Black, Ruff,
mypy and pytest. The pandas pytest run failed because the virtual environment
contains CPython 3.13 native NumPy extensions while ai-dev selected Python 3.14.

### 2. Text reporter crashed on CP1250

After creating the Markdown and JSON reports, the CLI crashed while printing a
message containing the Unicode replacement character:

```text
UnicodeEncodeError: 'charmap' codec can't encode character '\ufffd'
```

The exception originated in `ai_dev_tools.cli._print_text`.

### 3. Misleading aggregate result

The root-project pytest check passed 271 tests and the root mypy check passed,
but failures from the incorrectly detected pandas workspace made the aggregate
command fail. Some structured result entries also contained a non-zero
`exit_code` together with `status: success`, which makes the report harder to
interpret reliably.

## Expected behavior

- Directories ignored as virtual environments (`venv`, `.venv`, `env`) should
  be excluded from workspace discovery.
- Output should be encoded safely on Windows consoles, for example by replacing
  unsupported characters or explicitly using UTF-8.
- A subprocess with a non-zero exit code should not be represented as a
  successful check result.

## Artifacts

The failing run created local evidence under the inspected repository:

```text
.ai/reports/check-full-latest.json
.ai/reports/check-full-latest.md
.ai/logs/check-20260830-1844*.log
```

The `.ai/` directory is ignored by Git.
