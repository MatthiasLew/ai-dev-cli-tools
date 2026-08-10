from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from ai_dev_tools.utils.subprocess import run_command

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_TOOLCHAIN_E2E") != "1",
    reason="real toolchain E2E is enabled explicitly in CI",
)

FIXTURES = Path("tests/fixtures")


@pytest.mark.parametrize(
    ("family", "tool", "command", "cwd"),
    [
        (
            "python",
            Path(sys.executable).name,
            [sys.executable, "-m", "pytest", "-q"],
            FIXTURES / "monorepo-mixed" / "packages" / "api",
        ),
        ("node", "node", ["node", "test.js"], FIXTURES / "monorepo-mixed" / "packages" / "web"),
        (
            "rust",
            "cargo",
            ["cargo", "test", "--quiet"],
            FIXTURES / "monorepo-mixed" / "services" / "worker",
        ),
        ("maven", "mvn", ["mvn", "-q", "validate"], FIXTURES / "projects" / "maven"),
        ("gradle", "gradle", ["gradle", "-q", "tasks"], FIXTURES / "projects" / "gradle"),
        (
            "php",
            "composer",
            ["composer", "validate", "--no-check-publish"],
            FIXTURES / "projects" / "php-composer",
        ),
    ],
)
def test_real_fixture_toolchain(family: str, tool: str, command: list[str], cwd: Path) -> None:
    requested = set(
        os.environ.get("E2E_TOOLCHAINS", "python,node,rust,maven,gradle,php").split(",")
    )
    if family not in requested:
        pytest.skip(f"toolchain not requested in this environment: {family}")
    if command[0] != sys.executable:
        assert shutil.which(tool), f"required CI toolchain is missing: {tool}"
    result = run_command(command, cwd.resolve(), timeout_seconds=180)
    assert result.exit_code == 0, result.combined_output
