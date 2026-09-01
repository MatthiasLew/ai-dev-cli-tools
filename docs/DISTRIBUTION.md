# Distribution and Upgrade Policy

Version 1.2.1 is the dashboard stability patch prepared for Trusted Publishing to TestPyPI and
PyPI. The planned product capability set remains complete as of 1.2.0.
The recommended isolated installation is:

```bash
python -m pip install --upgrade pipx
pipx install ai-dev-cli-tools==1.2.1
ai-dev --version
ai-dev doctor
```

Until the release appears on PyPI, install the exact wheel from the matching GitHub release or a
pinned Git commit:

```bash
python -m pip install ./dist/ai_dev_cli_tools-1.2.1-py3-none-any.whl
pipx install "git+https://github.com/MatthiasLew/ai-dev-cli-tools.git@v1.2.1"
```

Upgrades must pin a release tag or version, review `CHANGELOG.md`, and rerun `ai-dev doctor`.
Editable installs are development-only.

## Trusted Publishing configuration

The dedicated `.github/workflows/release.yml` workflow builds one artifact, publishes it to
TestPyPI, verifies a clean installation, and attaches that exact artifact to a draft GitHub
release. Publishing the draft is the explicit promotion decision that triggers the separate
`.github/workflows/publish-pypi.yml` production workflow. Neither workflow uses long-lived API
secrets. Configure pending Trusted Publishers with exactly:

| Registry | Owner | Repository | Workflow | GitHub environment |
| --- | --- | --- | --- | --- |
| TestPyPI | `MatthiasLew` | `ai-dev-cli-tools` | `release.yml` | `testpypi` |
| PyPI | `MatthiasLew` | `ai-dev-cli-tools` | `publish-pypi.yml` | `pypi` |

Create both GitHub environments, restrict them to release tags matching `v*`, and require manual
approval for `pypi`. On a private GitHub Free repository, required environment reviewers and
branch protection are unavailable; do not treat an unprotected production environment as
approved. Make the repository public or enable a GitHub plan that supports those protections
before production publication. Manual publication of the generated draft release remains an
additional promotion gate, not a replacement for environment protection.

Review changes to both publishing workflows as credential-equivalent changes. Only their small
publishing jobs receive `id-token: write`; build, artifact validation, and installation jobs do
not.

## Release sequence

1. Complete `docs/RELEASE_CHECKLIST.md` on a clean commit already present on `main`.
2. Confirm the TestPyPI and PyPI Trusted Publisher records and GitHub environments above.
3. Create and push the signed tag `v1.2.1` from that exact commit.
4. Approve the `testpypi` environment if configured to require review.
5. Confirm the TestPyPI installation smoke job passes and inspect the generated draft release.
6. Review the attached wheel/sdist, release notes, and protected `pypi` environment.
7. Manually publish the draft release to trigger `.github/workflows/publish-pypi.yml`.
8. Confirm the PyPI `pipx` installation smoke job passes before announcing the release.

If production verification fails, do not reuse the version. Fix forward with a new PEP 440 patch
version. Yank a broken release in PyPI when installation is unsafe or materially
misleading; yanking does not delete release history.
