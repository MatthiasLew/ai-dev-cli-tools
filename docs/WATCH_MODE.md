# Watch mode

ai-dev watch is an opt-in foreground validation loop. It watches project files without adding a
background service and runs the smallest changed validation after writes settle.

~~~bash
ai-dev watch
ai-dev watch --mode changed --debounce 500 --jobs 4
ai-dev watch --initial
~~~

The default debounce is 500 ms and the polling interval is 100 ms. Rapid editor writes are
coalesced. Changes made while validation is running cancel only subprocesses owned by that
obsolete validation, preserve their logs, and queue the newest state for the next pass. Watch
never terminates a PID obtained from stale or external state. Generated and local state roots
such as .git, .ai, virtual environments, caches, build output, and node_modules are ignored.

Use Ctrl+C to stop. The final foreground summary and only the latest useful result are written to
.ai/reports/watch-latest.json and .md. Full check logs keep the normal check retention behavior.

For deterministic automation and tests, --max-runs limits validations and --initial requests one
validation before the first file change. A value of zero keeps watching until interrupted. Reports
include `queued_during_validation` and `cancelled_obsolete` counters.
Watch mode never installs dependencies, changes global configuration, or starts a hidden service.
