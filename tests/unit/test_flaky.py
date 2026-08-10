from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_dev_tools.cli import main
from ai_dev_tools.runners import check
from ai_dev_tools.runners.flaky import run_flaky_report
from ai_dev_tools.utils.subprocess import CommandResult


def _configured_test(root: Path) -> None:
    (root / ".ai-dev-tools.toml").write_text(
        "[commands]" + chr(10) + "test='pytest'" + chr(10),
        encoding="utf-8",
    )


def test_bounded_retry_preserves_initial_failure_and_marks_flaky(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configured_test(tmp_path)
    results = iter(
        [
            CommandResult(["pytest"], 1, "FAILED test_x - intermittent", "", 0.2),
            CommandResult(["pytest"], 0, "1 passed in 0.1s", "", 0.1),
        ]
    )
    calls = 0

    def fake_run(command: list[str], cwd: Path) -> CommandResult:
        nonlocal calls
        calls += 1
        return next(results)

    monkeypatch.setattr(check, "run_command", fake_run)

    report = check.run_check(
        tmp_path,
        mode="full",
        use_cache=False,
        retry_flaky=1,
    )

    row = report.summary["results"][0]
    assert report.status == "warning"
    assert calls == 2
    assert row["exit_code"] == 0
    assert row["flaky"] is True
    assert row["attempts"] == 2
    assert row["initial_exit_code"] == 1
    assert row["initial_failure"]["test"] == "test_x"
    assert row["initial_failure"]["message"] == "intermittent"
    assert report.summary["checks_flaky"] == 1
    assert report.summary["execution"]["retry_attempts"] == 1
    assert report.issues[0].code == "FLAKY_PASS"

    history = run_flaky_report(tmp_path)
    assert history.status == "warning"
    assert history.summary["known_flaky"] == 1


def test_retry_excludes_deterministic_and_timeout_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configured_test(tmp_path)
    calls = 0

    def syntax_failure(command: list[str], cwd: Path) -> CommandResult:
        nonlocal calls
        calls += 1
        return CommandResult(command, 1, "SyntaxError: invalid syntax", "", 0.1)

    monkeypatch.setattr(check, "run_command", syntax_failure)
    report = check.run_check(
        tmp_path,
        mode="full",
        use_cache=False,
        retry_flaky=3,
    )

    assert report.status == "failed"
    assert calls == 1
    assert report.summary["results"][0]["attempts"] == 1


def test_retry_limit_is_capped_and_cli_lists_history(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = check.run_check(tmp_path, retry_flaky=4)
    assert invalid.status == "invalid_configuration"
    assert invalid.summary["reason_code"] == "INVALID_FLAKY_RETRY_LIMIT"

    exit_code = main(["--project", str(tmp_path), "--json", "test", "flaky"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["command"] == "test flaky"
    assert payload["summary"]["known_flaky"] == 0