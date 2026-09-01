# Contributing

Keep changes small, typed, tested, and conservative. Runtime code should avoid platform-specific assumptions and prefer `pathlib` for paths.

Before pushing a larger stage, run:

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
