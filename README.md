# AI Dev CLI Tools

Cross-platform Python CLI helpers for AI coding agents and humans who want concise, deterministic development reports instead of huge logs.

`ai-dev` runs repeatable project checks locally, stores full logs under `.ai/logs/`, and returns compact Markdown/JSON summaries under `.ai/reports/`.

## Problem

AI coding agents often spend tokens reading full test output, repository trees, dependency noise, repeated warnings, and raw Git diffs. This project follows one rule:

```text
Scripts do the work and collect data.
AI reads a short report and decides what to do next.
Full logs stay on disk until needed.
```

## Install

```bash
python -m pip install pipx
pipx install .
ai-dev --help
```

For development:

```bash
python -m pip install -e ".[dev]"
```

## Windows

```powershell
.\ai.ps1 doctor
ai-dev scan --project "C:\path with spaces\project"
```

## Linux and macOS

```bash
./ai.sh doctor
ai-dev check --mode fast --project "/path/with spaces/project"
```

## Commands

```bash
ai-dev doctor
ai-dev scan
ai-dev map --max-files 500 --max-depth 6
ai-dev check --mode fast
ai-dev check --mode changed  # reports changed files and falls back safely when test mapping is uncertain
ai-dev check --mode full
ai-dev test affected
ai-dev logs summarize
ai-dev context build
ai-dev git status
ai-dev git inspect
ai-dev finish
```

All commands support `--project`, `--json`, `--quiet`, `--help`, and `--version` at the top level.

## Reports and Logs

Short reports are written to `.ai/reports/` as Markdown and JSON. Full command output is written to `.ai/logs/` and ignored by Git. Check summaries include exit codes, durations, first failure hints, grouped repeated messages, test counts, and full log paths.

JSON reports use schema `1.1` with `schema_version`, `tool_version`, `command`, `status`, `exit_code`, timestamps, `project_root`, `summary`, `issues`, `artifacts`, and `metadata`.

## Auto Detection

`scan` detects Python, Node.js, Java, Rust, PHP, Docker, Make, CI workflows, package managers, scripts, entrypoints, tests, lint, formatters, type checkers, and `.env.example` variables.

Supported examples:

- Python: `pyproject.toml`, `requirements.txt`, `pytest`, `ruff`, `black`, `mypy`, `coverage`.
- Node.js: `package.json`, npm, pnpm, yarn, Jest, Vitest, ESLint, Prettier, TypeScript.
- Java: Maven, Gradle, tests, Checkstyle, SpotBugs, JaCoCo when configured.
- Rust: Cargo test, fmt, clippy.
- PHP: Composer, PHPUnit, PHPStan, PHP-CS-Fixer when configured.

## Configuration

Optional `.ai-dev-tools.toml`:

```toml
[project]
name = "example-project"

[commands]
test = "pytest"
lint = "ruff check ."
typecheck = "mypy src"

[ignore]
paths = ["node_modules", ".venv", "dist", "build"]

[reports]
directory = ".ai/reports"
logs_directory = ".ai/logs"
```

Configuration takes precedence over auto detection. Invalid or unknown configuration is reported through `config_warnings` instead of crashing normal scans.

## Command Status

| Command | Status |
| --- | --- |
| doctor | implemented |
| scan | implemented |
| map | implemented |
| check | implemented |
| check --explain | implemented |
| test affected | implemented |
| logs summarize | implemented |
| capabilities | implemented |
| git status | implemented |
| git inspect | implemented |
| finish | implemented |
| bootstrap | planned |
| run | planned |
| stop | planned |
| context build | planned |

Planned commands return `NOT_IMPLEMENTED` with a non-zero exit code.

## v0.2 Scope Notes

- Monorepo/workspace detection: experimental.
- Per-subproject runner isolation: planned for v0.3.0.
- Runtime version validation: partial.
- `context build`, `bootstrap`, `run`, `stop`, auto-commit, auto-push, and GUI remain planned or `NOT_IMPLEMENTED`.
## Intentional Limits

Version 0.2.0 does not reset, clean, commit, push, merge, clone organizations, synchronize repositories, delete containers, publish releases, or remove user files.
