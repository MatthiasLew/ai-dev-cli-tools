from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Issue, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.security.secrets import mask_text
from ai_dev_tools.utils.subprocess import CommandResult, run_command

SCHEMA_VERSION = "1.0"
TOKEN_ESTIMATION = "masked_utf8_bytes_divided_by_4"


def run_benchmark(
    project_root: Path,
    suite: Path,
    variant: str,
    *,
    trials: int = 3,
    cache_state: str = "cold",
    timeout_seconds: int = 300,
) -> Report:
    report = Report(command=f"benchmark run --variant {variant}", project_root=project_root)
    manifest_path = suite if suite.is_absolute() else project_root / suite
    try:
        spec = _load_spec(project_root, manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_BENCHMARK_SUITE", "message": str(exc)}
        return report.finish()
    variants = spec["variants"]
    if variant not in variants:
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "UNKNOWN_BENCHMARK_VARIANT",
            "variant": variant,
            "available_variants": sorted(variants),
        }
        return report.finish()
    if not 1 <= trials <= 50:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_TRIAL_COUNT", "trials": trials}
        return report.finish()

    rows: list[dict[str, Any]] = []
    working = Path(spec["working_directory"])
    for number in range(1, trials + 1):
        reset = run_command(spec["reset_command"], working, timeout_seconds)
        execution = (
            run_command(variants[variant], working, timeout_seconds)
            if reset.exit_code == 0
            else _skipped(variants[variant])
        )
        validation = (
            run_command(spec["validation_command"], working, timeout_seconds)
            if reset.exit_code == 0 and execution.exit_code == 0
            else _skipped(spec["validation_command"])
        )
        rows.append(_trial_row(number, reset, execution, validation))

    correct = sum(bool(row["correct"]) for row in rows)
    report.status = "success" if correct == len(rows) else "failed"
    report.summary = {
        "benchmark_schema_version": SCHEMA_VERSION,
        "suite": spec["name"],
        "fixture_version": spec["fixture_version"],
        "manifest": str(manifest_path.resolve()),
        "variant": variant,
        "cache_state": cache_state,
        "trials": rows,
        "statistics": _statistics(rows),
        "correct_trials": correct,
        "token_estimation": TOKEN_ESTIMATION,
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "implementation": sys.implementation.name,
        },
    }
    if correct != len(rows):
        report.issues.append(
            Issue(
                "error",
                "At least one trial did not pass required validation",
                code="BENCHMARK_INCORRECT",
            )
        )
    report.finish()
    output = _run_path(project_root, str(spec["name"]), variant, cache_state)
    write_json(report, output)
    write_markdown(report, output.with_suffix(".md"))
    return report


def compare_benchmarks(project_root: Path, baseline: Path, candidate: Path) -> Report:
    report = Report(command="benchmark compare", project_root=project_root)
    try:
        left = _load_run(project_root, baseline)
        right = _load_run(project_root, candidate)
        _validate_comparable(left, right)
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "INCOMPARABLE_BENCHMARK_RUNS",
            "message": str(exc),
        }
        return report.finish()

    left_summary = left["summary"]
    right_summary = right["summary"]
    left_stats = left_summary["statistics"]
    right_stats = right_summary["statistics"]
    valid = (
        left.get("status") == "success"
        and right.get("status") == "success"
        and left_summary["correct_trials"] == len(left_summary["trials"])
        and right_summary["correct_trials"] == len(right_summary["trials"])
        and _outcomes(left_summary) == _outcomes(right_summary)
    )
    metric_names = (
        "median_seconds",
        "median_time_to_actionable_result_seconds",
        "median_agent_visible_bytes",
        "median_estimated_tokens",
        "median_commands",
    )
    metrics = {
        key: _comparison(float(left_stats[key]), float(right_stats[key]))
        for key in metric_names
    }
    report.status = "success" if valid else "failed"
    report.summary = {
        "valid": valid,
        "suite": left_summary["suite"],
        "fixture_version": left_summary["fixture_version"],
        "cache_state": left_summary["cache_state"],
        "baseline_variant": left_summary["variant"],
        "candidate_variant": right_summary["variant"],
        "metrics": metrics,
        "recommendation": _recommendation(metrics, valid),
    }
    if not valid:
        report.issues.append(
            Issue(
                "error",
                "Both variants must produce the same validated outcome",
                code="BENCHMARK_NOT_EQUIVALENT",
            )
        )
    report.finish()
    output = (
        project_root
        / ".ai"
        / "benchmarks"
        / "comparisons"
        / f"{_safe_name(str(left_summary['suite']))}-{_timestamp()}.json"
    )
    write_json(report, output)
    write_markdown(report, output.with_suffix(".md"))
    return report


def _load_spec(project_root: Path, path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported benchmark schema: {data.get('schema_version')!r}")
    variants_raw = data.get("variants")
    if not isinstance(variants_raw, dict) or len(variants_raw) < 2:
        raise ValueError("Benchmark suite requires at least two variants")
    variants = {
        str(name): _command(value, f"variants.{name}")
        for name, value in variants_raw.items()
    }
    working = (project_root / str(data.get("working_directory", "."))).resolve()
    root = project_root.resolve()
    if working != root and root not in working.parents:
        raise ValueError("working_directory must stay inside the project")
    if not working.is_dir():
        raise ValueError("working_directory does not exist")
    return {
        "name": str(data.get("name") or path.stem),
        "fixture_version": str(data.get("fixture_version") or "1"),
        "working_directory": working,
        "variants": variants,
        "reset_command": _command(data.get("reset_command"), "reset_command"),
        "validation_command": _command(data.get("validation_command"), "validation_command"),
    }


def _command(value: object, key: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
    ):
        raise ValueError(f"{key} must be a non-empty list of strings")
    return list(value)


def _trial_row(
    number: int,
    reset: CommandResult,
    execution: CommandResult,
    validation: CommandResult,
) -> dict[str, Any]:
    visible = mask_text(execution.combined_output + validation.combined_output).encode("utf-8")
    return {
        "trial": number,
        "correct": reset.exit_code == execution.exit_code == validation.exit_code == 0,
        "duration_seconds": round(
            reset.duration_seconds + execution.duration_seconds + validation.duration_seconds,
            3,
        ),
        "time_to_actionable_result_seconds": round(
            reset.duration_seconds + execution.duration_seconds, 3
        ),
        "commands": 3,
        "validation_subprocesses": 1,
        "agent_visible_bytes": len(visible),
        "estimated_tokens": math.ceil(len(visible) / 4),
        "exit_codes": {
            "reset": reset.exit_code,
            "variant": execution.exit_code,
            "validation": validation.exit_code,
        },
        "outcome_signature": hashlib.sha256(
            validation.stdout.strip().encode("utf-8")
        ).hexdigest(),
        "timed_out": reset.timed_out or execution.timed_out or validation.timed_out,
    }


def _statistics(rows: list[dict[str, Any]]) -> dict[str, float]:
    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows]

    durations = values("duration_seconds")
    return {
        "median_seconds": round(statistics.median(durations), 3),
        "duration_stdev_seconds": (
            round(statistics.stdev(durations), 3) if len(durations) > 1 else 0.0
        ),
        "median_time_to_actionable_result_seconds": round(
            statistics.median(values("time_to_actionable_result_seconds")), 3
        ),
        "median_agent_visible_bytes": round(
            statistics.median(values("agent_visible_bytes")), 3
        ),
        "median_estimated_tokens": round(
            statistics.median(values("estimated_tokens")), 3
        ),
        "median_commands": round(statistics.median(values("commands")), 3),
    }


def _comparison(baseline: float, candidate: float) -> dict[str, float | None]:
    change = candidate - baseline
    return {
        "baseline": baseline,
        "candidate": candidate,
        "absolute_change": round(change, 3),
        "percent_change": round(change / baseline * 100, 2) if baseline else None,
    }


def _recommendation(
    metrics: dict[str, dict[str, float | None]], valid: bool
) -> str:
    if not valid:
        return "reject_incorrect_candidate"
    time_change = metrics["median_seconds"]["percent_change"]
    token_change = metrics["median_estimated_tokens"]["percent_change"]
    if (
        isinstance(time_change, float)
        and isinstance(token_change, float)
        and time_change < 0
        and token_change < 0
    ):
        return "adopt_candidate"
    return "investigate_tradeoffs"


def _validate_comparable(left: dict[str, Any], right: dict[str, Any]) -> None:
    for key in ("suite", "fixture_version", "cache_state"):
        if left["summary"][key] != right["summary"][key]:
            raise ValueError(f"Benchmark {key} differs")
    if left["summary"]["variant"] == right["summary"]["variant"]:
        raise ValueError("Benchmark variants must differ")


def _outcomes(summary: dict[str, Any]) -> list[str]:
    return [str(row["outcome_signature"]) for row in summary["trials"]]


def _load_run(project_root: Path, path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else project_root / path
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not str(data.get("command", "")).startswith(
        "benchmark run"
    ):
        raise ValueError(f"Not a benchmark run: {resolved}")
    return data


def _skipped(command: list[str]) -> CommandResult:
    return CommandResult(command, 125, "", "Skipped after prior failure", 0.0)


def _run_path(project_root: Path, suite: str, variant: str, cache_state: str) -> Path:
    return (
        project_root
        / ".ai"
        / "benchmarks"
        / "runs"
        / f"{_safe_name(suite)}-{_safe_name(variant)}-{cache_state}-{_timestamp()}.json"
    )


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in value)
    return safe.strip("-") or "benchmark"


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")