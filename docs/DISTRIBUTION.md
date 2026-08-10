# Distribution and Upgrade Policy

Version 0.4.x is not published to PyPI. Supported installation paths are a wheel produced by a
GitHub release or a pinned Git checkout:

```bash
python -m pip install ./dist/ai_dev_cli_tools-0.4.0-py3-none-any.whl
python -m pip install "git+https://github.com/MatthiasLew/ai-dev-cli-tools.git@<commit>"
```

Upgrades must pin a release tag or commit, review `CHANGELOG.md`, and rerun `ai-dev doctor` plus
an installed-wheel smoke test. Editable installs are development-only.

PyPI publication is deferred until the project has a stable 1.0 CLI/schema policy, protected
release workflow, trusted publishing, signed provenance, and confirmed ownership of the package
name. This is a deliberate distribution decision, not an unresolved packaging task.