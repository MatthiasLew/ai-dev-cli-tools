# Managed Run and Stop

`ai-dev run` starts a project command detected from a Node package script or explicitly
configured as `[commands].run`. It never guesses how to start a generic Python, Java, Rust, or
PHP application.

```toml
[commands]
run = "python -m my_application"
```

## Modes

```bash
ai-dev run --explain
ai-dev run --dry-run
ai-dev run --foreground --timeout 300
ai-dev run --ready-http http://127.0.0.1:8000/health --startup-timeout 20
ai-dev run --ready-tcp 127.0.0.1:5432 --startup-log-lines 100
ai-dev run
ai-dev stop --explain
ai-dev stop --timeout 10
```

Background mode starts a project-local supervisor and writes state to
`.ai/runtime/process.json`. Application output is stored in `.ai/logs/run-latest.log`.

## Readiness and startup evidence

Background mode can require an HTTP endpoint, a TCP endpoint, or both. At least one probe is
performed even when the timeout is zero. A failed readiness check produces
`READINESS_TIMEOUT`, records a masked error and bounded startup-log tail, then asks the matching
supervisor to stop its own child. `--startup-log-lines` controls the report tail without
changing the full masked log artifact. Stale metadata is reported as recovered and never used
to kill a PID.
## Stop safety

`stop` does not send a signal to a PID read from a stale file. It writes a token-authenticated
request under `.ai/runtime/`; only the matching live supervisor terminates its own child.
If the supervisor does not acknowledge the request, the command reports `STOP_TIMEOUT` and
does not kill an arbitrary process.

Runtime state is local, ignored by Git, safe to recreate, and must not be treated as durable
application configuration.
