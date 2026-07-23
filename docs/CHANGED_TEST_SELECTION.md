# Changed Test Selection

`check --mode changed` inspects Git changes and selects the smallest safe validation plan it can justify.

Strategies:

- `changed_test_direct`: a changed file is already a test.
- `direct_test_match`: a source file maps to an existing test file.
- `configured_mapping`: `.ai-dev-tools.toml` supplied a `[changed_tests]` mapping.
- `configuration_change`: a project, test, workspace, or fixture config changed, so the plan broadens.
- `broad_fallback`: changed files exist but no reliable map is available.
- `no_changes`: Git reports no changes.

Low confidence selections intentionally broaden to normal checks instead of pretending precision.

Example:

```bash
ai-dev check --mode changed --explain
ai-dev check --mode changed
```