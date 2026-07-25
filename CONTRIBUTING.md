# Contributing

Keep changes small, typed, tested, and conservative. Runtime code should avoid platform-specific assumptions and prefer `pathlib` for paths.

Before pushing a larger stage, run:

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

The installed package smoke test must use a built wheel, a clean virtual environment, and the installed `ai-dev` entrypoint. Do not replace it with editable install or `PYTHONPATH` smoke tests.
