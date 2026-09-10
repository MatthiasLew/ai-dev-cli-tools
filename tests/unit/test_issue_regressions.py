from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from threading import Event

import pytest

from ai_dev_tools.context.builder import build_context
from ai_dev_tools.context.models import ContextOptions
from ai_dev_tools.models.report import Report, Status
from ai_dev_tools.parsers.logs import parse_tool_output
from ai_dev_tools.runners.check import _tasks_for_mode, run_check
from ai_dev_tools.runners.check_models import ChangedSelection, CheckTask
from ai_dev_tools.runners.check_selection import _commands_for_selected_tests
from ai_dev_tools.runners.finish import _blocking_reasons
from ai_dev_tools.utils.subprocess import run_command


@pytest.mark.parametrize("prefix", ["ℹ", "#"])
@pytest.mark.parametrize("failed", [0, 1])
def test_node_summaries(prefix: str, failed: int) -> None:
    output = "✔ content deletion is recoverable (1ms)\n" + "\n".join(
        f"{prefix} {key} {value}"
        for key, value in {
            "tests": 18,
            "pass": 18 - failed,
            "fail": failed,
            "skipped": 0,
            "duration_ms": 123,
        }.items()
    )
    parsed = parse_tool_output("npm test", output, failed)
    assert parsed["parser"] == "node-test"
    assert parsed["tests_total"] == 18
    assert parsed["passed"] == 18 - failed
    assert parsed["failed"] == failed
    assert parsed["status"] == ("failed" if failed else "success")
    assert parse_tool_output("npm test", output, 2)["status"] == "failed"


def test_numeric_error_counts_survive_summary() -> None:
    parsed = parse_tool_output("pytest", "1 passed, 2 errors", 0)
    assert parsed["errors"] == 2
    assert parsed["tests_total"] == 3
    assert parsed["status"] == "failed"


@pytest.mark.parametrize("extension", ["mjs", "cjs", "js", "unknown"])
def test_selected_tests_keep_broad_command(extension: str) -> None:
    plan = [CheckTask("npm test", "unit_tests", ["npm", "test"], "medium", "detected")]
    tests = [f"tests/example.test.{extension}"]
    commands = _commands_for_selected_tests(plan, tests)
    selection = ChangedSelection("changed_test_direct", "high", tests, tests, commands)
    assert [task.command for task in _tasks_for_mode(plan, "changed", selection)] == [
        ["npm", "test"]
    ]
    assert (
        _tasks_for_mode(
            plan, "changed", ChangedSelection("changed_test_direct", "high", tests, tests, [])
        )
        == plan
    )


def test_mixed_test_selection_does_not_send_javascript_to_pytest() -> None:
    commands = _commands_for_selected_tests([], ["tests/test_a.py", "tests/a.test.mjs"])
    assert commands[0][-1] == "tests/test_a.py"
    assert "tests/a.test.mjs" not in commands[0]
    assert commands[1] == ["npm", "test"]


def test_unrunnable_selected_tests_cannot_pass(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.unknown").write_text("test", encoding="utf-8")
    run_command(["git", "init"], tmp_path)
    report = run_check(tmp_path, mode="changed", use_cache=False)
    assert report.status == "failed"
    assert report.exit_code != 0
    assert report.summary["reason_code"] == "SELECTED_TESTS_NOT_RUNNABLE"


@pytest.mark.skipif(not shutil.which("node") or not shutil.which("npm"), reason="Node required")
@pytest.mark.parametrize("extension", ["mjs", "cjs"])
def test_changed_node_failure_is_executed(tmp_path: Path, extension: str) -> None:
    (tmp_path / "tests").mkdir()
    source = tmp_path / "tests" / f"example.test.{extension}"
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": f"node --test tests/example.test.{extension}"}}),
        encoding="utf-8",
    )
    source.write_text("", encoding="utf-8")
    for command in (
        ["git", "init"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "fixture",
        ],
    ):
        assert run_command(command, tmp_path).exit_code == 0
    source.write_text("throw new Error('recoverable test failure');\n", encoding="utf-8")
    report = run_check(tmp_path, mode="changed", use_cache=False, retry_infra=0)
    assert report.status == "failed"
    assert report.exit_code != 0
    assert report.summary["changed_analysis"]["strategy"] == "changed_test_direct"
    assert report.summary["changed_analysis"]["selected_commands"] == [["npm", "test"]]


@pytest.mark.parametrize("git", [False, True])
@pytest.mark.parametrize("limit", [0, 100, 5000])
def test_context_keeps_source_and_measures_artifacts(tmp_path: Path, git: bool, limit: int) -> None:
    source = tmp_path / "scripts" / "main" / "main.gd"
    source.parent.mkdir(parents=True)
    source.write_text("extends Node\n" + "# Polish controls help\n" * 800, encoding="utf-8")
    if git:
        assert run_command(["git", "init"], tmp_path).exit_code == 0
    report = build_context(
        tmp_path,
        ContextOptions(
            task="Add Polish controls help to room menu",
            include=("scripts/main/main.gd",),
            retrieval="never",
            max_files=1,
            max_chars=limit,
        ),
    )
    selected = report.summary["selected_files"][0]
    assert selected["content"] == source.read_text(encoding="utf-8")[:limit]
    assert selected["truncated"] is True
    assert report.summary["budget"]["used_chars"] == limit
    assert report.summary["budget"]["scope"] == "source_and_diff_content"
    receipt = report.summary["token_accounting"]["savings_receipt"]["selection"]
    assert receipt["truncated"] is True
    assert receipt["content_truncated"] is True
    assert receipt["list_truncated"] is False
    md = (tmp_path / ".ai/context/context-latest.md").read_text(encoding="utf-8")
    text = (tmp_path / ".ai/context/context-latest.json").read_text(encoding="utf-8")
    assert report.summary["budget"]["markdown_chars"] == len(md)
    assert report.summary["budget"]["json_chars"] == len(text)
    assert json.loads(text)["summary"]["selected_files"][0]["content"] == selected["content"]
    if limit:
        assert "extends Node" in md
        assert md.index("extends Node") < md.index("## Token Accounting")
    else:
        assert selected["evidence_id"] in selected["expansion_command"]


def test_cancellable_command_drains_large_output(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 300000)"],
        tmp_path,
        timeout_seconds=5,
        cancel_event=Event(),
    )
    assert result.exit_code == 0
    assert len(result.stdout) == 300000


def test_timeout_preserves_partial_output(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; print('before timeout', flush=True); time.sleep(5)"],
        tmp_path,
        timeout_seconds=1,
    )
    assert result.timed_out
    assert "before timeout" in result.stdout


def test_explicit_include_keeps_priority_over_detected_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("wanted documentation", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('entrypoint')", encoding="utf-8")
    report = build_context(
        tmp_path,
        ContextOptions(
            include=("README.md",),
            no_git=True,
            max_files=1,
            max_chars=100,
        ),
    )
    selected = report.summary["selected_files"]
    assert selected[0]["path"] == "README.md"
    assert selected[0]["reason"].startswith("included")


@pytest.mark.parametrize(
    "status", ["partial", "blocked", "environment_error", "invalid_configuration"]
)
def test_finish_rejects_incomplete_validation(tmp_path: Path, status: Status) -> None:
    git_report = Report(command="git inspect", project_root=tmp_path).finish()
    check_report = Report(command="check", project_root=tmp_path, status=status).finish()
    assert "required checks incomplete" in _blocking_reasons(
        git_report, check_report, [], ["app.py"]
    )


@pytest.mark.parametrize("cancelled", [False, True])
def test_cancellable_process_timeout_and_cancel(tmp_path: Path, cancelled: bool) -> None:
    event = Event()
    if cancelled:
        event.set()
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        tmp_path,
        timeout_seconds=1,
        cancel_event=event,
    )
    assert result.exit_code == (130 if cancelled else 124)
    assert result.cancelled is cancelled
    assert result.timed_out is (not cancelled)


def test_cancellable_missing_command(tmp_path: Path) -> None:
    result = run_command([str(tmp_path / "missing-command")], tmp_path, cancel_event=Event())
    assert result.exit_code == 127
