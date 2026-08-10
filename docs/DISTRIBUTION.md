# Distribution and Upgrade Policy

Version 0.5.0a1 is the first public alpha prepared for Trusted Publishing to TestPyPI and PyPI.
The recommended isolated installation is:

```bash
python -m pip install --upgrade pipx
pipx install ai-dev-cli-tools==0.5.0a1
ai-dev --version
ai-dev doctor
```

Until the release appears on PyPI, install the exact wheel from the matching GitHub release or a
pinned Git commit:

```bash
python -m pip install ./dist/ai_dev_cli_tools-0.5.0a1-py3-none-any.whl
pipx install "git+https://github.com/MatthiasLew/ai-dev-cli-tools.git@v0.5.0a1"
```

Upgrades must pin a release tag or version, review `CHANGELOG.md`, and rerun `ai-dev doctor`.
Editable installs are development-only.

## Trusted Publishing configuration

The dedicated `.github/workflows/release.yml` workflow builds one artifact, publishes it to
TestPyPI, verifies a clean installation, and only then makes the same artifact eligible for PyPI.
It does not use long-lived API-token secrets. Configure pending Trusted Publishers with exactly:

| Registry | Owner | Repository | Workflow | GitHub environment |
| --- | --- | --- | --- | --- |
| TestPyPI | `MatthiasLew` | `ai-dev-cli-tools` | `release.yml` | `testpypi` |
| PyPI | `MatthiasLew` | `ai-dev-cli-tools` | `release.yml` | `pypi` |

Create both GitHub environments and require manual approval for `pypi`. Protect `main`, restrict
release-tag creation to maintainers, and review changes to `release.yml` as credential-equivalent
changes. The publishing jobs alone receive `id-token: write`; build and verification jobs do not.

## Release sequence

1. Complete `docs/RELEASE_CHECKLIST.md` on a clean commit already present on `main`.
2. Confirm the TestPyPI and PyPI Trusted Publisher records and GitHub environments above.
3. Create and push the signed tag `v0.5.0a1` from that exact commit.
4. Approve the `testpypi` environment if configured to require review.
5. Confirm the TestPyPI installation smoke job passes.
6. Review and approve the protected `pypi` environment.
7. Confirm the PyPI `pipx` installation smoke job passes before announcing the release.

If production verification fails, do not reuse the version. Fix forward with a new PEP 440
pre-release version. Yank a broken release in PyPI when installation is unsafe or materially
misleading; yanking does not delete release history.
