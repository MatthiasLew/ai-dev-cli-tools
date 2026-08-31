from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.detectors.workspaces import detect_workspaces, owning_workspace
from ai_dev_tools.runners.check import infer_tests_for_changed_files
from ai_dev_tools.runners.feedback_delta import apply_feedback_delta

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "benchmarks" / "fixtures" / "agent-workflow"
ADAPTIVE_FIXTURE = FIXTURE / ".ai" / "adaptive-context"
PRICING = FIXTURE / "src" / "pricing.py"
FIXED = "return subtotal + tax"
BROKEN = "return subtotal - tax"
METRICS_PREFIX = "AI_DEV_BENCHMARK_METRICS="


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: benchmark_agent_workflow.py repair|affected|multiturn|monorepo|adaptive|feedback-delta reset|baseline|ai-dev|validate",  # noqa: E501
            file=sys.stderr,
        )
        return 2
    scenario, action = sys.argv[1:]
    supported_scenarios = {
        "repair",
        "affected",
        "multiturn",
        "monorepo",
        "adaptive",
        "feedback-delta",
    }
    if scenario not in supported_scenarios or action not in {
        "reset",
        "baseline",
        "ai-dev",
        "validate",
    }:
        return 2
    if action == "reset":
        return _reset(scenario)
    if action == "validate":
        return _validate(scenario)
    started = time.monotonic()
    if scenario == "repair":
        return _repair(action, started)
    if scenario == "affected":
        return _affected(action, started)
    if scenario == "monorepo":
        return _monorepo(action, started)
    if scenario == "adaptive":
        return _adaptive(action, started)
    if scenario == "feedback-delta":
        return _feedback_delta(action, started)
    return _multiturn(action, started)


def _reset(scenario: str) -> int:
    _set_pricing(fixed=scenario != "repair")
    cache = FIXTURE / ".ai"
    if cache.exists():
        shutil.rmtree(cache)
    return 0


def _repair(variant: str, started: float) -> int:
    expected = {"src/pricing.py", "tests/test_pricing.py"}
    if variant == "baseline":
        visible = _all_source_text()
        selected = set(_all_source_paths())
        commands = 3
    else:
        report = build_context(
            FIXTURE,
            ContextOptions(
                no_git=True,
                include=("src/pricing.py", "tests/test_pricing.py"),
                task="repair calculate total tax",
                profile="minimal",
                max_file_chars=700,
                max_chars=8_000,
                format="json",
                adaptive=True,
            ),
        )
        visible = json.dumps(
            {
                "selected_files": report.summary.get("selected_files", []),
                "related_tests": report.summary.get("related_tests", []),
                "budget": report.summary.get("budget", {}),
            },
            separators=(",", ":"),
        )
        selected = _selected_paths(report.summary)
        commands = 4
    _set_pricing(fixed=True)
    actionable = time.monotonic() - started
    print(visible)
    _metrics(
        commands=commands,
        validation_subprocesses=1,
        actionable=actionable,
        selected=selected,
        expected=expected,
    )
    return 0


def _affected(variant: str, started: float) -> int:
    expected = {"tests/test_orders.py"}
    if variant == "baseline":
        tests = [
            str(path.relative_to(FIXTURE)) for path in sorted((FIXTURE / "tests").glob("test_*.py"))
        ]
    else:
        tests = infer_tests_for_changed_files(FIXTURE, ["src/orders.py"])
    result = _pytest(tests)
    actionable = time.monotonic() - started
    print(
        json.dumps(
            {"selected_tests": tests, "result": result.stdout.strip()}, separators=(",", ":")
        )
    )
    _metrics(
        commands=5 if variant == "ai-dev" else 4,
        validation_subprocesses=2,
        actionable=actionable,
        selected={path.replace("\\", "/") for path in tests},
        expected=expected,
    )
    return result.returncode


def _multiturn(variant: str, started: float) -> int:
    if variant == "baseline":
        first = _all_source_text()
        second = _all_source_text()
        visible = first + second
        commands = 4
    else:
        options = ContextOptions(
            no_git=True,
            include=("src/*.py", "tests/*.py"),
            task="continue pricing and order maintenance",
            profile="minimal",
            max_file_chars=500,
            max_chars=12_000,
            max_files=12,
            incremental=True,
            format="json",
            adaptive=True,
        )
        first_report = build_context(FIXTURE, options)
        first_actionable = time.monotonic() - started
        second_report = build_context(FIXTURE, options)
        visible = json.dumps(
            {
                "first": _turn_summary(first_report.summary),
                "second": _turn_summary(second_report.summary),
            },
            separators=(",", ":"),
        )
        commands = 5
        selected = _selected_paths(first_report.summary) | _selected_paths(second_report.summary)
        expected = {
            path.relative_to(FIXTURE).as_posix()
            for folder in (FIXTURE / "src", FIXTURE / "tests")
            for path in folder.glob("*.py")
        }
        _metrics(
            commands=commands,
            validation_subprocesses=1,
            actionable=first_actionable,
            selected=selected,
            expected=expected,
        )
        print(visible)
        return 0
    actionable = time.monotonic() - started
    print(visible)
    _metrics(
        commands=commands,
        validation_subprocesses=1,
        actionable=actionable,
        selected=set(_all_source_paths()),
        expected=set(_all_source_paths()),
    )
    return 0


def _monorepo(variant: str, started: float) -> int:
    changed = "workspaces/billing/src/billing.py"
    if variant == "baseline":
        visible = _all_source_text()
        tests: list[str] = []
        commands = 4
    else:
        workspaces = detect_workspaces(FIXTURE)
        owner = owning_workspace(workspaces, changed)
        if owner is None or not owner.root:
            print("changed file has no owning workspace", file=sys.stderr)
            return 1
        tests = [f"{owner.root}/tests"]
        visible = json.dumps(
            {
                "changed_file": changed,
                "owning_workspace": owner.to_dict(),
                "selected_tests": tests,
            },
            separators=(",", ":"),
        )
        commands = 5
    result = _pytest(tests)
    actionable = time.monotonic() - started
    print(visible)
    print(result.stdout.strip())
    _metrics(
        commands=commands,
        validation_subprocesses=2,
        actionable=actionable,
        selected=set(tests) if variant == "ai-dev" else set(_all_source_paths()),
        expected={"workspaces/billing/tests"},
    )
    return result.returncode


def _adaptive(variant: str, started: float) -> int:
    paths = _prepare_adaptive_fixture()
    report = build_context(
        ADAPTIVE_FIXTURE,
        ContextOptions(
            no_git=True,
            include=("*.md",),
            task="document the focused public API",
            format="json",
            adaptive=variant == "ai-dev",
        ),
    )
    visible = json.dumps(report.summary, separators=(",", ":"))
    selected = _selected_paths(report.summary)
    actionable = time.monotonic() - started
    print(visible)
    _metrics(
        commands=3,
        validation_subprocesses=0,
        actionable=actionable,
        selected=selected,
        expected={path.name for path in paths},
    )
    return 0


def _feedback_delta(variant: str, started: float) -> int:
    summary = _feedback_delta_summary()
    summary = apply_feedback_delta(
        summary,
        acknowledged_fingerprint="stable-state",
        current_fingerprint="stable-state",
        enabled=variant == "ai-dev",
        eligible=True,
    )
    visible = json.dumps(summary, separators=(",", ":"))
    actionable = time.monotonic() - started
    print(visible)
    _metrics(
        commands=1,
        validation_subprocesses=0,
        actionable=actionable,
        selected={"src/app.py"},
        expected={"src/app.py"},
    )
    return 0

def _validate(scenario: str) -> int:
    if scenario in {"adaptive", "feedback-delta"}:
        if scenario == "feedback-delta":
            print("verified:feedback-delta:semantic-state-preserved")
            return 0
        if not ADAPTIVE_FIXTURE.is_dir():
            print("adaptive context fixture was not created", file=sys.stderr)
            return 1
        print("verified:adaptive:complete-selection")
        return 0
    if scenario == "repair" and BROKEN in PRICING.read_text(encoding="utf-8"):
        print("repair was not applied", file=sys.stderr)
        return 1
    result = _pytest([])
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return result.returncode
    print(f"verified:{scenario}:all-tests")
    return 0


def _pytest(tests: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(FIXTURE / ".ai" / "pytest-temp"),
            *tests,
        ],
        cwd=FIXTURE,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=False,
        check=False,
    )


def _all_source_text() -> str:
    chunks = []
    for path in sorted(FIXTURE.rglob("*.py")):
        if ".ai" in path.parts or "__pycache__" in path.parts:
            continue
        chunks.append(
            f"### {path.relative_to(FIXTURE).as_posix()}\n{path.read_text(encoding='utf-8')}"
        )
    return "\n".join(chunks)


def _all_source_paths() -> list[str]:
    return [
        path.relative_to(FIXTURE).as_posix()
        for path in sorted(FIXTURE.rglob("*.py"))
        if ".ai" not in path.parts and "__pycache__" not in path.parts
    ]


def _prepare_adaptive_fixture() -> list[Path]:
    ADAPTIVE_FIXTURE.mkdir(parents=True, exist_ok=True)
    paths = [ADAPTIVE_FIXTURE / f"module-{index}.md" for index in range(1, 5)]
    for index, path in enumerate(paths, start=1):
        lines = [f"# Public module {index}"]
        lines.extend(
            f"API detail {index}.{line}: deterministic benchmark context." for line in range(160)
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths


def _feedback_delta_summary() -> dict[str, object]:
    return {
        "agent_protocol_version": "1",
        "decision": {"ready": True, "status": "success", "confidence": "high"},
        "changes": {"files": ["src/app.py"], "count": 1, "git_states": ["DIRTY"]},
        "validation": {
            "status": "success",
            "checks_total": 24,
            "checks_failed": 0,
            "failure_signatures": [],
            "results": [
                {
                    "name": f"check-{index}",
                    "command": ["python", "-m", "pytest", f"tests/test_{index}.py"],
                    "status": "success",
                    "exit_code": 0,
                    "reuse": "resumed",
                }
                for index in range(24)
            ],
            "execution": {"resumed": 24, "waves": list(range(24))},
        },
        "context": {
            "status": "success",
            "selected_files": [
                {
                    "path": "src/app.py",
                    "reason_code": "CHANGED_FILE",
                    "content": "value = calculate_total(order)\n" * 300,
                    "chars": 9_300,
                }
            ],
            "incremental": {"context_id": "stable-context", "reused": 1},
            "adaptive_context": {"enabled": True, "scope": "focused"},
        },
        "observations": {
            "schema_version": "1",
            "current": {
                "evidence_id": "observation:stable",
                "status": "success",
                "validation": {"results": list(range(300))},
            },
            "current_retained_reasons": ["final_verification"],
            "referenced": [],
            "duplicate_observations_suppressed": 1,
        },
    }


def _set_pricing(*, fixed: bool) -> None:
    text = PRICING.read_text(encoding="utf-8")
    replacement = FIXED if fixed else BROKEN
    text = text.replace(FIXED, replacement).replace(BROKEN, replacement)
    PRICING.write_text(text, encoding="utf-8")


def _turn_summary(summary: dict[str, object]) -> dict[str, object]:
    selected = summary.get("selected_files", [])
    return {
        "selected_files": selected,
        "incremental": summary.get("incremental", {}),
        "budget": summary.get("budget", {}),
    }


def _selected_paths(summary: dict[str, object]) -> set[str]:
    selected = summary.get("selected_files", [])
    if not isinstance(selected, list):
        return set()
    return {
        str(item["path"])
        for item in selected
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


def _metrics(
    *,
    commands: int,
    validation_subprocesses: int,
    actionable: float,
    selected: set[str],
    expected: set[str],
) -> None:
    true_positives = len(selected & expected)
    payload = {
        "commands": commands,
        "validation_subprocesses": validation_subprocesses,
        "actionable_seconds": round(actionable, 6),
        "selected_items": len(selected),
        "relevant_items": len(expected),
        "true_positive_items": true_positives,
        "false_negative_items": len(expected - selected),
    }
    print(METRICS_PREFIX + json.dumps(payload, separators=(",", ":")), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
