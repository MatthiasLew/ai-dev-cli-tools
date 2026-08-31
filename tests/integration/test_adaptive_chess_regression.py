from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from ai_dev_tools.cli import main


def test_full_check_ignores_venv_preserves_failure_and_prints_on_cp1250(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='application'\n", encoding="utf-8")
    dependency = tmp_path / "venv" / "Lib" / "site-packages" / "pandas"
    dependency.mkdir(parents=True)
    (dependency / "pyproject.toml").write_text(
        "[project]\nname='pandas'\n", encoding="utf-8"
    )
    (tmp_path / "fail.py").write_text(
        "import sys\nsys.stdout.buffer.write(b'\\xff')\nraise SystemExit(2)\n",
        encoding="utf-8",
    )
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[commands]\ntest='python fail.py'\n", encoding="utf-8"
    )
    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1250", errors="strict")
    original = sys.stdout
    try:
        sys.stdout = console
        exit_code = main(
            ["--project", str(tmp_path), "check", "--mode", "full", "--no-cache"]
        )
        console.flush()
    finally:
        sys.stdout = original

    payload = json.loads(
        (tmp_path / ".ai" / "reports" / "check-full-latest.json").read_text(encoding="utf-8")
    )
    assert exit_code == 1
    assert payload["status"] == "failed"
    assert len(payload["summary"]["results"]) == 1
    assert payload["summary"]["results"][0]["exit_code"] == 2
    assert payload["summary"]["results"][0]["status"] == "failed"
    assert "pandas" not in output.getvalue().decode("cp1250")
