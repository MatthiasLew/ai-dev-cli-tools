from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_dev_tools.cli import main
from ai_dev_tools.runners.baseline import run_baseline


def _write_check_report(root: Path, status: str, signature: str) -> None:
    path = root / ".ai" / "reports" / "check-full-latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "command": "check --mode full",
                "status": status,
                "summary": {"results": [{"failure_signature": signature}]},
                "issues": [],
            }
        ),
        encoding="utf-8",
    )


def test_baseline_create_list_and_compare_new_and_resolved_failures(tmp_path: Path) -> None:
    _write_check_report(tmp_path, "failed", "old-failure")
    created = run_baseline(tmp_path, "create", "main")

    assert created.status == "success"
    assert created.summary["failures"] == 1
    assert created.artifacts[0].kind == "baseline"
    assert run_baseline(tmp_path, "list").summary["baselines"] == ["main"]

    _write_check_report(tmp_path, "failed", "new-failure")
    compared = run_baseline(tmp_path, "compare", "main")

    assert compared.status == "failed"
    assert compared.summary["new_failures"] == ["check --mode full:new-failure"]
    assert compared.summary["resolved_failures"] == ["check --mode full:old-failure"]
    assert compared.summary["ready"] is False


def test_baseline_compare_succeeds_without_regression(tmp_path: Path) -> None:
    _write_check_report(tmp_path, "failed", "known")
    run_baseline(tmp_path, "create", "review")

    compared = run_baseline(tmp_path, "compare", "review")

    assert compared.status == "success"
    assert compared.summary["new_failures"] == []
    assert compared.summary["unchanged_reports"] == 1


def test_baseline_rejects_invalid_or_missing_name(tmp_path: Path) -> None:
    invalid = run_baseline(tmp_path, "create", "../unsafe")
    missing = run_baseline(tmp_path, "compare", "missing")

    assert invalid.summary["reason_code"] == "INVALID_BASELINE_NAME"
    assert missing.summary["reason_code"] == "BASELINE_NOT_FOUND"


def test_baseline_and_explain_commands_are_wired_through_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--project", str(tmp_path), "--json", "baseline", "create", "cli"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["summary"]["name"] == "cli"

    exit_code = main(
        ["--project", str(tmp_path), "--json", "explain", "issue:missing", "--tail", "5"]
    )
    missing = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert missing["summary"]["reason_code"] == "EVIDENCE_NOT_FOUND"
