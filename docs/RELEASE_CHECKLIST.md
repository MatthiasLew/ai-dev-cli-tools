# Release Checklist

Use this checklist for every tagged release. A release is not complete until the built wheel,
rather than an editable source checkout, passes the smoke tests.

## Prepare

- [ ] Confirm the intended scope and remove stale version promises from documentation.
- [ ] Update the version in `pyproject.toml` and `src/ai_dev_tools/__init__.py`.
- [ ] Update `CHANGELOG.md` with user-visible behavior, report-schema changes, migrations,
  limitations, and deprecations.
- [ ] Confirm that JSON changes are backward compatible or deliberately increment the report
  schema version and document the migration.
- [ ] Confirm `README.md`, command help, capability output, and files under `docs/` agree.

## Validate locally

Run from a clean supported Python environment:

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

Then verify:

- [ ] The wheel and source distribution contain the expected package and documentation files.
- [ ] The installed `ai-dev` entrypoint works without editable install or `PYTHONPATH`.
- [ ] JSON and Markdown reports contain their own artifact paths.
- [ ] No generated `.ai/` state, caches, logs, reports, credentials, or local environments are
  included in the distribution.
- [ ] The working tree contains only intentional release changes.

## Validate CI

- [ ] The complete Linux, Windows, and macOS matrix passes on every supported Python version.
- [ ] Packaging and installed-wheel smoke jobs pass.
- [ ] Uploaded diagnostic artifacts contain no unmasked secrets.
- [ ] Required checks are attached to the release commit rather than an earlier commit.

## Publish

Publishing is an explicit maintainer action. The project must not publish automatically from a
local development command.

- [ ] Create and inspect the release tag.
- [ ] Build artifacts from the tagged commit in a clean environment.
- [ ] If PyPI distribution is enabled, publish through trusted publishing or another documented,
  least-privilege mechanism.
- [ ] Create release notes from the changelog.
- [ ] Install the published artifact into a new environment and run the entrypoint smoke test.
- [ ] Record known limitations and rollback or yanking instructions.

## Latest cross-platform evidence

- GitHub Actions CI run 31382168325 passed on 2026-08-10 for Linux, Windows, and macOS across the configured Python 3.11-3.13 matrix.
- Docs run 31382168329 passed for the same commit (11e372).
