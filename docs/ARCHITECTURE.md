# Architecture

`ai-dev` is a single Python application. PowerShell and Bash files are thin wrappers that invoke the same CLI.

## Layers

- Detectors inspect environment and project structure without changing files.
- Runners execute existing project commands with `subprocess.run(shell=False)`, timeouts, UTF-8 output, and full log capture.
- Parsers reduce raw command output into first failure, project frame, repeated warning groups, and issue lists.
- Reporters write stable Markdown and JSON reports.
- Git helpers inspect repository state without destructive operations.
- Security helpers scan changed files for masked secret findings.

## Data Flow

Command -> detector/runner -> full log -> parser -> `Report` model -> Markdown/JSON artifacts.

## Extending

Add small modules under `detectors/`, `runners/`, or `parsers/`. Keep runtime dependencies optional and prefer existing project configuration over global assumptions.
