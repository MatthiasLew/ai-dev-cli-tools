from pathlib import Path

from ai_dev_tools.parsers.failures import classify_failure
from ai_dev_tools.runners.check import CheckTask, _run_logged
from ai_dev_tools.utils.subprocess import CommandResult


def test_failure_classifier_distinguishes_infrastructure_code_and_environment() -> None:
    dns = CommandResult(["pip"], 1, "", "Failed to resolve files.pythonhosted.org", 0.1)
    assertion = CommandResult(["pytest"], 1, "", "AssertionError: expected 1", 0.1)
    missing = CommandResult(["tool"], 127, "", "missing", 0.1)

    assert classify_failure(dns).retryable is True
    assert classify_failure(dns).category == "infrastructure"
    assert classify_failure(assertion).category == "code"
    assert classify_failure(missing).category == "environment"


def test_failure_classifier_covers_non_retryable_terminal_states() -> None:
    assert classify_failure(CommandResult(["x"], 0, "ok", "", 0.1)).category == "success"
    assert classify_failure(
        CommandResult(["x"], 130, "", "", 0.1, cancelled=True)
    ).category == "cancelled"
    assert classify_failure(
        CommandResult(["x"], 124, "", "", 0.1, timed_out=True)
    ).category == "timeout"
    assert classify_failure(
        CommandResult(["x"], 1, "", "permission denied", 0.1)
    ).category == "environment"
    assert classify_failure(CommandResult(["x"], 1, "", "mystery", 0.1)).category == "unknown"
    assert classify_failure(
        CommandResult(["x"], 126, "", "blocked", 0.1, failure_class="policy")
    ).category == "policy"


def test_check_retries_only_transient_infrastructure(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import check

    calls = 0

    def fake_run(*args, **kwargs) -> CommandResult:  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            return CommandResult(["tool"], 1, "", "Temporary failure in name resolution", 0.1)
        return CommandResult(["tool"], 0, "ok", "", 0.1)

    monkeypatch.setattr(check, "run_command", fake_run)
    result = _run_logged(
        CheckTask("tool", "lint", ["tool"], "fast", "detected"),
        tmp_path,
        tmp_path / ".ai" / "logs",
        [],
        False,
        retry_infra=1,
    )

    assert calls == 2
    assert result.infrastructure_recovered is True
    assert result.failure_class == "success"
