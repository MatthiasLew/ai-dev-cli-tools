# AI Dev CLI Tools

Cross-platform Python CLI helpers for AI coding agents and humans who want concise, deterministic development reports instead of huge logs.

`ai-dev` runs repeatable project checks locally, stores full logs under `.ai/logs/`, and returns compact Markdown/JSON summaries under `.ai/reports/`.

## Problem

AI coding agents often spend tokens reading full test output, repository trees, dependency noise, repeated warnings, and raw Git diffs. This project follows one rule:

```text
Scripts do the work and collect data.
AI reads a short report and decides what to do next.
Full logs stay on disk until needed.

Generated state under `.ai/logs/`, `.ai/reports/`, `.ai/context/`, `.ai/cache/`,
`.ai/runtime/`, and `.ai/tmp/` is local and ignored by Git. Logs, reports, and context
artifacts may be removed when no longer needed; cache, runtime, and temporary state must always
be safe for `ai-dev` to recreate.
```

## Install

```bash
python -m pip install --upgrade pipx
pipx install ai-dev-cli-tools==1.0.0
ai-dev --help
```

For a source checkout, use `pipx install .`. See `docs/DISTRIBUTION.md` for the Trusted Publishing
and upgrade policy.

For development:

```bash
python -m pip install -c requirements-dev.lock -e ".[dev]"
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
ai-dev check --mode full --jobs 4
ai-dev check --mode changed --policy feedback-first --resume
ai-dev check --mode changed --compare main
ai-dev check --mode changed --retry-flaky 1
ai-dev check --mode changed --retry-infra 1
ai-dev plan --task "implement rate limiting" --mode changed
ai-dev index update
ai-dev index daemon --poll 500 --idle-timeout 300
ai-dev semantic status
ai-dev semantic index --backend auto
ai-dev policy assess -- python -m pytest
ai-dev sarif --input .ai/reports/agent-plan.json
ai-dev cache status
ai-dev cache layout
ai-dev baseline create main
ai-dev baseline compare main
ai-dev benchmark run --suite examples/benchmarks/output-budget-smoke.json --variant baseline
ai-dev explain issue:<id> --tail 100
ai-dev explain --symbol "src/app.py#Application.run" --tail 100
ai-dev feedback --task "fix authentication timeout"
ai-dev watch --mode changed --debounce 500
ai-dev session status
ai-dev bootstrap --if-needed
ai-dev environment explain
ai-dev diagnostics
ai-dev completion bash
ai-dev mcp serve
ai-dev test affected
ai-dev test flaky
ai-dev logs summarize
ai-dev context build
ai-dev git status
ai-dev git inspect
ai-dev finish
```

All commands support `--project`, `--json`, `--quiet`, `--help`, and `--version` at the top level.


## Local MCP server

`ai-dev mcp serve` exposes project status, implementation planning, compact feedback, bounded context, validation,
and progressive evidence as local structured tools for Codex-compatible MCP clients. The STDIO
server is dependency-free, has no network listener, fixes all calls to one project root, and
defaults validation to preview-only.

```bash
codex mcp add ai-dev -- ai-dev --project "/absolute/path/to/project" mcp serve
```

See `docs/MCP_SERVER.md` for tool schemas, approvals, project-scoped configuration, and
security boundaries.

For the recommended agent loop—plan, retrieve, implement, validate, and expand only failed
evidence—see `docs/AGENT_WORKFLOW.md`.

For agents sharing a repository, `ai-dev agents add|claim|heartbeat|release|complete|status`
maintains an atomic local task board with expiring leases and declared-path conflict detection.
See `docs/AGENT_COORDINATION.md` for the workflow and safety limits.

## Bootstrap

`ai-dev bootstrap` prepares a detected project with conservative, project-local commands. Use `--explain` to see the plan without modifications, `--dry-run` to validate planning without executing modifying commands, and `--create-env` to allow copying `.env.example` to `.env` only when `.env` is missing.

Supported strategies include Python uv, Poetry, pip with `pyproject.toml`, pip with `requirements.txt`, Node npm/pnpm/Yarn, Maven wrapper or system Maven, Gradle wrapper or system Gradle, Cargo, and Composer.

See `docs/BOOTSTRAP.md` for safety rules and configuration.

## Managed application runtime

`ai-dev run` supports explain, dry-run, foreground, and supervised background modes.
`ai-dev stop` sends a token-authenticated request to the matching local supervisor and never
kills an arbitrary PID read from stale state. See `docs/RUNTIME.md`.

## Context Builder

`ai-dev context build` creates a bounded local context package for coding agents without calling any LLM, embedding API, or cloud service.

```bash
ai-dev context build --task "fix auth tests"
ai-dev context build --changed-only --max-chars 50000
ai-dev context build --incremental  # emits only candidates changed since the last pack
ai-dev context build --incremental --since <context-id>
ai-dev context build --compare main
ai-dev context build --profile review
ai-dev context build --profile implement
ai-dev context build --profile docs
ai-dev context build --retrieval auto --explain  # explains retrieval or abstention
ai-dev context build --tokenizer o200k_base --token-budget source=8000 --token-budget diffs=2000
ai-dev context build --refine issue:<id> --refinement-rounds 2 --refinement-max-files 5
ai-dev context build --compression conservative
ai-dev context build --include "src/**/*.py" --exclude "tests/fixtures/**"
ai-dev context build --explain --json
```

Artifacts are written to `.ai/context/context-latest.md` and `.ai/context/context-latest.json` by default. The builder includes detected technologies, git state, changed files, related tests, validation plan, recent commits, selected snippets, limited diffs, latest check errors, masked secret findings, and budget/truncation metadata. Large Python files use AST-aware symbol snippets, while large JavaScript and TypeScript files use conservative top-level symbol selection instead of blindly returning only the beginning of the file.

Selective retrieval defaults to `auto`: focused includes or changed files can abstain from broad cross-file retrieval, while missing focus, broad configuration changes, and broad task scopes fall back to the full candidate set. Use `--retrieval always` to expand or `--retrieval never` to keep only focused roots and inferred related tests. The JSON and Markdown reports explain the decision and expose a related-test false-negative proxy.

Install `ai-dev-cli-tools[tokenizers]` to enable exact local `cl100k_base` or `o200k_base` counting. Without that optional extra, accounting uses the explicit UTF-8-bytes/4 estimate and reports a fallback if an exact tokenizer was requested. Repeated `--token-budget category=N` limits source, diffs, tests, logs, maps, history, cached input, or output independently. `--provider-usage <json>` normalizes OpenAI or Anthropic usage fields from a project-local file without network access.

Incremental mode stores the latest schema-versioned manifest plus up to 50 content-addressed
historical manifests under `.ai/cache/`, and reports changed versus reused files. Pass
`--since <context-id>` to compare against an explicitly retained context. Default limits are
`--max-chars 50000`, `--max-files 30`, `--max-file-chars 8000`, and `--max-diff-chars 15000`.
Secret-bearing and generated paths such as `.env`, private keys, caches, build output, `.ai/logs`,
and `.ai/reports` are excluded from snippets.
## Reports and Logs

Validation results are cached by default using repository, command, workspace, runtime, and platform fingerprints; use `check --no-cache` to force execution. `check --resume` reuses only exact successful checkpoint fingerprints. `--policy feedback-first` runs cheaper waves first and cancels later expensive waves after a required failure; `complete` retains comprehensive execution. `index status/update/rebuild` manages the reusable repository index, while `cache status/prune/clear` provides bounded local cache maintenance; `cache layout` emits a deterministic stable-prefix manifest and provider breakpoint recommendations. See `docs/CACHE_AND_INDEX.md`.

Short reports are written to `.ai/reports/` as Markdown and JSON. Full command output is written to `.ai/logs/` and ignored by Git. Check summaries include exit codes, durations, first failure hints, grouped repeated messages, test counts, and full log paths.

JSON reports use schema `1.1` with `schema_version`, `tool_version`, `command`, `status`, `exit_code`, timestamps, `project_root`, `summary`, `issues`, `artifacts`, and `metadata`.

`ai-dev feedback` combines Git changes, changed validation, incremental context, focused rerun hints, stage timings, and local session state into one compact agent protocol report. Its observation lifecycle keeps the current failure, unresolved warnings, or final verification inline while replacing superseded results with content-addressed IDs expandable through `ai-dev explain`; see `docs/OBSERVATION_LIFECYCLE.md`.

Every expandable issue, check, file, snippet, diff, workspace, and artifact receives a stable local `evidence_id`. The report metadata lists references; `ai-dev explain <evidence-id> --tail 100` retrieves only that evidence. `ai-dev baseline create <name>` stores a compact local snapshot under `.ai/cache/baselines/`, and `baseline compare <name>` leads with new/resolved failures, issue codes, and status regressions. Pass `--compare <name>` to `check` or `context build` to apply that regression contract directly to the current report. Reproducible local A/B suites use benchmark run and benchmark compare; see docs/BENCHMARKS.md.
Research-backed context and token-efficiency recommendations are documented in `docs/TOKEN_EFFICIENCY_RESEARCH.md`.

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

[execution]
mode = "enforce"
maximum_impact = "high"
allow_prefixes = ["python -m pytest", "python -m ruff", "python -m mypy"]
deny_prefixes = ["git reset", "git clean"]
```

Configuration takes precedence over auto detection. Invalid or unknown configuration is reported through `config_warnings` instead of crashing normal scans.
## Local Validation

Before pushing a larger stage, run:

```bash
python -m ruff check .
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=90
python -m build
python scripts/validate_ci.py
python scripts/test_installed_package.py
git diff --check
```

`python scripts/test_installed_package.py` rebuilds the wheel, installs only that wheel into a clean virtual environment in a path containing spaces, and verifies the installed `ai-dev` entrypoint without editable install or `PYTHONPATH`.

## Command Status

| Command | Status |
| --- | --- |
| doctor | implemented |
| scan | implemented |
| map | implemented |
| check | implemented |
| check --explain | implemented |
| test affected | implemented |
| test flaky / check --retry-flaky | implemented |
| index status/update/rebuild | implemented |
| index daemon | implemented |
| plan / MCP plan_work | implemented |
| semantic status/index | implemented with optional provider plugins |
| policy assess / execution enforcement | implemented |
| sarif | implemented |
| cache status/prune/clear/layout | implemented |
| logs summarize | implemented |
| context build | implemented |
| diagnostics | implemented |
| mcp serve | implemented |
| watch | implemented |
| benchmark run/compare | implemented |
| performance latest/compare | implemented |
| capabilities | implemented |
| git status | implemented |
| git inspect | implemented |
| finish | implemented |
| bootstrap | implemented |
| environment explain | implemented |
| run | implemented |
| stop | implemented |

## Scope Notes

- Monorepo/workspace detection and per-subproject command routing: implemented.
- Per-subproject check and bootstrap working directories: implemented.
- Runtime requirement detection and version validation: implemented.
- `context build` is implemented as a bounded local context pack builder.
- `bootstrap` is implemented as a conservative local setup planner/executor.
- Auto-commit, auto-push, destructive cleanup, remote source transmission, and GUI are intentionally out of scope.

## Intentional Limits
Version 1.0.0 does not reset, clean, commit, push, merge, clone organizations, synchronize repositories, delete containers, publish releases, or remove user files.

Shell completion scripts are generated with `ai-dev completion bash|zsh|fish|powershell` and can be sourced or installed using the normal mechanism for the selected shell.
