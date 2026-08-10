# Warm environment state

A successful bootstrap records a local environment snapshot at
.ai/cache/environment-state.json. The snapshot contains only safe machine facts: bootstrap plan,
hashes of dependency/configuration inputs, resolved executable paths and masked versions, virtual
environment location, and dependency-directory presence. It does not store environment variable
values, source contents, credentials, or repository data outside those hashes.

~~~bash
ai-dev bootstrap --if-needed
ai-dev environment explain
~~~

bootstrap --if-needed skips every installation command only when all checks pass:

- state schema is supported;
- the exact bootstrap plan fingerprint still matches;
- every tracked manifest, lockfile, and runtime configuration hash still matches;
- recorded executable paths still exist and resolve to the same command;
- the recorded virtual environment still exists.

A stale or missing state falls back to the normal doctor, scan, bootstrap, and smoke-check path.
Only a fully successful bootstrap replaces the state; failed and partial runs cannot make a future
bootstrap skip work. Explain and dry-run modes never reuse state to hide their current plan.

environment explain reports each reason code, tool path, dependency marker, capture time, and
fingerprint match without executing installers. The file is cache data, ignored by Git, safe to
delete, and rebuilt after the next successful bootstrap.