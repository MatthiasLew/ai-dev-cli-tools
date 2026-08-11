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

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "benchmarks" / "fixtures" / "agent-workflow"
PRICING = FIXTURE / "src" / "pricing.py"
FIXED = "return subtotal + tax"
BROKEN = "return subtotal - tax"
METRICS_PREFIX = "AI_DEV_BENCHMARK_METRICS="


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: benchmark_agent_workflow.py repair|affected|multiturn|monorepo reset|baseline|ai-dev|validate",  # noqa: E501
            file=sys.stderr,
        )
        return 2
    scenario, action = sys.argv[1:]
    if scenario not in {"repair", "affected", "multiturn", "monorepo"} or action not in {
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
    return _multiturn(action, started)


def _reset(scenario: str) -> int:
    _set_pricing(fixed=scenario != "repair")
    cache = FIXTURE / ".ai"
    if cache.exists():
        shutil.rmtree(cache)
    return 0


def _repair(variant: str, started: float) -> int:
    if variant == "baseline":
        visible = _all_source_text()
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
        commands = 4
    _set_pricing(fixed=True)
    actionable = time.monotonic() - started
    print(visible)
    _metrics(commands=commands, validation_subprocesses=1, actionable=actionable)
    return 0


def _affected(variant: str, started: float) -> int:
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
            incremental=True,
            format="json",
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
        _metrics(commands=commands, validation_subprocesses=1, actionable=first_actionable)
        print(visible)
        return 0
    actionable = time.monotonic() - started
    print(visible)
    _metrics(commands=commands, validation_subprocesses=1, actionable=actionable)
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
    _metrics(commands=commands, validation_subprocesses=2, actionable=actionable)
    return result.returncode

def _validate(scenario: str) -> int:
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


def _metrics(*, commands: int, validation_subprocesses: int, actionable: float) -> None:
    payload = {
        "commands": commands,
        "validation_subprocesses": validation_subprocesses,
        "actionable_seconds": round(actionable, 6),
    }
    print(METRICS_PREFIX + json.dumps(payload, separators=(",", ":")), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
