# Bootstrap

`ai-dev bootstrap` prepares a detected project for local development with conservative, project-local commands. It never installs runtimes globally, changes PATH, runs with elevated privileges, publishes packages, deploys, removes user files, or overwrites `.env`.

## Commands

```bash
ai-dev bootstrap
ai-dev bootstrap --dry-run
ai-dev bootstrap --explain
ai-dev bootstrap --create-env
```

`--explain` detects the project and prints the plan without installing dependencies, creating `.venv`, or creating `.env`.

`--dry-run` performs planning and validation, but executes no modifying commands. Reports include `dry_run: true`, `planned_commands`, and `executed_commands: 0`.

`--create-env` allows copying `.env.example` to `.env` only when `.env.example` exists and `.env` does not. Existing `.env` is never overwritten, and `.env` contents are never written to reports.

## Strategies

Python:

- `uv.lock` plus `pyproject.toml`: `uv sync`
- Poetry project metadata: `poetry install`
- installable `pyproject.toml`: local `.venv`, pip upgrade, optional editable install
- `requirements.txt`: local `.venv`, pip upgrade, `pip install -r requirements.txt`

Node.js:

- `pnpm-lock.yaml`: `pnpm install --frozen-lockfile`
- `yarn.lock`: `yarn install --immutable`
- `package-lock.json`: `npm ci`
- no lockfile: conservative package-manager install fallback

Java:

- Maven prefers `mvnw`/`mvnw.cmd`, otherwise requires system Maven from doctor.
- Gradle prefers `gradlew`/`gradlew.bat`, otherwise requires system Gradle from doctor.

Rust uses `cargo fetch`. PHP uses `composer install --no-interaction`.

## Configuration

```toml
[bootstrap]
create_env = false
run_smoke_check = true
timeout_seconds = 900

[bootstrap.commands]
before = []
after = []

[bootstrap.python]
venv = ".venv"

[bootstrap.node]
frozen_lockfile = true
```

Configured `before` and `after` commands must be lists of argument lists, for example:

```toml
[bootstrap.commands]
before = [["python", "--version"]]
```

Shell strings are rejected by configuration warnings instead of being executed.

## Reports

Bootstrap writes:

- `.ai/reports/bootstrap-latest.md`
- `.ai/reports/bootstrap-latest.json`
- full command logs under `.ai/logs/`

The JSON summary includes project type, package manager, dry-run/explain mode, planned and executed commands, `.venv` and `.env` creation status, smoke check status, missing tools, and the full plan.

## Limits

- Monorepo/workspace detection and per-subproject command routing: implemented.
- Per-subproject check and bootstrap working directories: implemented.
- Runtime version validation: partial.
- Integration tests for package managers are conditional on tools available locally.
