# Adding a Runner

1. Use `ai_dev_tools.utils.subprocess.run_command`.
2. Never use `shell=True` unless there is no safe alternative.
3. Respect `.ai-dev-tools.toml` before auto-detected commands.
4. Store full output in `.ai/logs/`.
5. Return a compact report with command, exit code, duration, first failure, and full log path.
