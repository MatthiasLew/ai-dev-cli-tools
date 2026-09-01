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

- [ ] Confirm release changes reached `main` through the repository's supported squash-merge
  strategy; merge commits are disabled.
- [ ] Verify the CI run attached to the resulting squash commit on `main`, not only the pull
  request head.
- [ ] Create and inspect the release tag.
- [ ] Confirm TestPyPI publication and clean-install verification pass.
- [ ] Inspect the automatically generated draft GitHub release and its attached wheel/sdist.
- [ ] Manually publish the draft only after the protected `pypi` environment is ready.
- [ ] Build artifacts from the tagged commit in a clean environment.
- [ ] If PyPI distribution is enabled, publish through trusted publishing or another documented,
  least-privilege mechanism.
- [ ] Create release notes from the changelog.
- [ ] Install the published artifact into a new environment and run the entrypoint smoke test.
- [ ] Record known limitations and rollback or yanking instructions.

## Latest cross-platform evidence

- GitHub Actions CI run 33323925088 passed on 2026-08-30 for Linux, Windows, and macOS across
  Python 3.11-3.13, including real Python, Node, Rust, Maven, Gradle, and Composer fixture
  toolchains, for commit `a86da2c`.
- Docs run 33323925074 passed for the same commit.

## Local 1.0.0 candidate evidence

- On 2026-08-31, the clean pinned environment passed 327 tests with 7 toolchain-dependent skips
  and exactly 90% branch coverage.
- Ruff, strict mypy across 131 source/test/script files, CI workflow validation, release metadata
  validation, wheel installation smoke, and `git diff --check` passed.
- The wheel and sdist were rebuilt as `1.0.0`; archive validation rejects `.ai`, environments,
  caches, coverage state, build output, and other generated/private paths.
- Cross-platform CI for the final release commit remains required before tagging `v1.0.0`.
