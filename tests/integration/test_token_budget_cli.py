import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "budgets",
    [
        ["6000"],
        ["unknown=1"],
        ["source=abc"],
        ["source=-1"],
        ["source=1", "source=2"],
    ],
)
@pytest.mark.parametrize("json_output", [False, True])
def test_invalid_token_budget_is_usage_error(
    tmp_path: Path, budgets: list[str], json_output: bool
) -> None:
    command = [
        sys.executable, "-m", "ai_dev_tools.cli",
        "--project", str(tmp_path), "context", "build",
    ]
    for budget in budgets:
        command.extend(["--token-budget", budget])
    if json_output:
        command.append("--json")
    result = subprocess.run(
        command, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    assert result.returncode == 2
    assert "--token-budget" in result.stderr
    assert "category=N" in result.stderr
    assert "allowed categories: source, diffs, tests, logs, maps, history" in result.stderr
    assert "Traceback" not in result.stderr
    assert not result.stdout
    assert not (tmp_path / ".ai").exists()
