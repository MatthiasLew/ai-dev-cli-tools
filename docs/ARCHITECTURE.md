# Architecture

`ai-dev` is a single Python application. PowerShell and Bash files are thin wrappers that invoke the same CLI.

## Layers

- Detectors inspect environment and project structure without changing files.
- Runners execute existing project commands with `subprocess.run(shell=False)`, timeouts, UTF-8 output, and full log capture.
- Parsers reduce raw command output into first failure, project frame, repeated warning groups, and issue lists.
- Reporters write stable Markdown and JSON reports.
- Git helpers inspect repository state without destructive operations.
- Security helpers scan changed files for masked secret findings.
- Context builders compose detector, git, runner-plan, parser, and security outputs into bounded AI context packages.
- The MCP adapter exposes bounded local reports as strict STDIO JSON-RPC tools without duplicating detector or runner logic.
- Packaging smoke tests build a wheel, install it into a clean virtual environment, and verify the installed `ai-dev` entrypoint.

## Data Flow

CLI or MCP tool -> detector/runner/context builder -> full log or bounded source selection -> parser/security masking -> `Report` model -> Markdown/JSON artifacts or concise MCP `structuredContent`.

## Extending

Add small modules under `detectors/`, `runners/`, or `parsers/`. Keep runtime dependencies optional and prefer existing project configuration over global assumptions.

## Validation plans

`check` builds deterministic `CheckTask` entries with name, category, command, cost, source, and required fields. Modes filter by semantics rather than slicing command lists.

The scheduler additionally models explicit task dependencies and conservative local resource
classes. CPU tasks consume one slot, memory-heavy tasks consume two, and exclusive build tasks run
alone. Results are always restored to deterministic plan order. Watch cancellation propagates an
in-memory token only to subprocesses created by the active validation.

The stable `runners.check` facade orchestrates execution and re-exports its public models and selection functions. `check_models` owns report contracts, while `check_selection` owns changed-file and affected-test strategy.

## Context Builders

`context build` is an orchestration layer. It calls project scan, repository map, git inspect, and changed-check selection, then applies local file selection, static dependency hints, snippet limits, diff limits, and secret masking. It does not execute tests, install dependencies, call external AI services, or isolate runners per subproject.

`context.models` owns budgets and file contracts. `context.selection` owns candidate ranking inputs, security exclusions, file reading, and bounded language dependency hints. The stable builder facade coordinates these strategies and report rendering.

Current context status:

- Monorepo/workspace detection and per-subproject command routing: implemented.
- Per-subproject check and bootstrap working directories: implemented.
- Runtime requirement detection and version validation: implemented.
- Dependency analysis remains intentionally bounded and static.

## Packaging Smoke

`scripts/test_installed_package.py` validates the packaged CLI rather than the source-tree module path. It removes stale build artifacts, builds a wheel, creates a temporary virtual environment in a path with spaces, installs only the wheel, locates the platform-specific `ai-dev` entrypoint, and runs smoke commands without editable install or `PYTHONPATH`.

## Bootstrap Runners

`bootstrap` builds a deterministic `BootstrapPlan` from project signals and configuration. Explain and dry-run modes do not execute modifying commands. Real execution uses `run_command(shell=False)`, project-local paths, timeouts, full log capture, and guarded `.env.example` copying only when explicitly enabled.

`bootstrap_models` contains the stable plan contracts, `bootstrap_strategies` contains project and workspace planning, and the `bootstrap` facade only orchestrates safety checks, execution, logs, and reports.
