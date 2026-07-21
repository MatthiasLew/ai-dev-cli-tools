# Contributing

Keep changes small, typed, tested, and conservative. Runtime code should avoid
platform-specific assumptions and prefer `pathlib` for paths.

Before opening a pull request, run:

```bash
python -m pytest
ruff check .
mypy src tests
```
