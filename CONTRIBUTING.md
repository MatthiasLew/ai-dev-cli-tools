# Contributing

Keep changes small, typed, tested, and conservative. Runtime code should avoid platform-specific assumptions and prefer `pathlib` for paths.

From a fresh checkout, one cross-platform command creates or refreshes the locked `.venv` and runs
every required gate without loading user-site packages:

```bash
python scripts/dev.py --check
```

Use `python scripts/dev.py --diagnose` to classify Python, workspace-temp, Git-metadata, and proxy
problems without installing anything. `DEV_GIT_METADATA` means the host or sandbox must grant write
access to `.git`; it is distinct from an existing-ref collision. `DEV_WORKSPACE_TEMP` means process
tests cannot safely use the project-local temp directory in the current execution environment.

The equivalent individual commands, when already inside the locked `.venv`, are:

```bash
python -m pip install -c requirements-dev.lock -e ".[dev]"
python -m ruff check .
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=90
python -m build
python scripts/validate_ci.py
python scripts/test_installed_package.py
git diff --check
```

The installed package smoke test must use a built wheel, a clean virtual environment, and the installed `ai-dev` entrypoint. Do not replace it with editable install or `PYTHONPATH` smoke tests.

## Pull requests

Keep each pull request focused and wait for the complete Linux, Windows, and macOS CI matrix.
The repository does not allow merge commits. After required checks pass, maintainers should use a
squash merge so `main` receives one descriptive commit, then delete the merged topic branch:

```bash
gh pr merge <number> --squash --delete-branch
```

Do not retry a rejected `--merge` operation or force-push `main`. Refresh the pull request state
before merging and verify the resulting squash commit's `main` CI run.
