# Bounded flaky retries

Flaky retries are disabled by default. Enable a strictly bounded policy for test checks only:

~~~bash
ai-dev check --mode changed --retry-flaky 1
ai-dev test flaky
~~~

The accepted retry count is 0 through 3. ai-dev never retries lint, format, typecheck, build,
missing-executable, timeout, collection, import, syntax, compiler, or configuration failures.
The policy applies only to unit and integration test tasks after their first real failure.

A retry that passes produces a partial/warning report, not a clean success. The result retains:

- the first exit code, parsed actionable failure, and stable failure signature;
- total attempts and aggregate duration;
- the final passing result;
- a FLAKY_PASS issue and checks_flaky count;
- both first and final attempt output in the full local log.

Flaky passes are not added to the validation success cache or resume checkpoint. This prevents an
intermittent pass from silently becoming reusable proof.

Local history is stored under .ai/cache/flaky-tests.json, guarded for parallel check workers,
bounded to 200 exact command/workspace/input fingerprints, ignored by Git, and never transmitted.
ai-dev test flaky lists entries that passed on retry or alternated for the same input fingerprint.
Changing relevant repository inputs creates a distinct history entry instead of blaming a changed
test on old evidence.