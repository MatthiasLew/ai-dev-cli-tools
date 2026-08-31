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
METRICS_PREFIX = "AI_DEV_BENCHMARK_METRICS="


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
        "median_iterations",
        "median_files_read",
        "median_selection_precision",
        "median_selection_recall",
    )
    metrics = {
        key: _comparison(_stat_value(left_stats, key), _stat_value(right_stats, key))
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


def gate_benchmarks(
    project_root: Path,
    baseline: Path,
    candidate: Path,
    *,
    max_time_regression: float = 20.0,
    max_token_regression: float = 5.0,
    min_token_reduction: float = 0.0,
    min_precision: float = 0.8,
    min_recall: float = 0.9,
    max_false_negatives: int = 0,
) -> Report:
    report = Report(command="benchmark gate", project_root=project_root)
    if (
        max_time_regression < 0
        or max_token_regression < 0
        or not 0 <= min_token_reduction <= 100
        or not 0 <= min_precision <= 1
        or not 0 <= min_recall <= 1
        or max_false_negatives < 0
    ):
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_BENCHMARK_THRESHOLDS"}
        return report
    comparison = compare_benchmarks(project_root, baseline, candidate)
    if comparison.status != "success":
        report.status = "failed"
        report.summary = {
            "passed": False,
            "reason_code": "BENCHMARK_EQUIVALENCE_FAILED",
            "comparison": comparison.summary,
        }
        report.issues.extend(comparison.issues)
        return report
    try:
        candidate_run = _load_run(project_root, candidate)
        stats = candidate_run["summary"]["statistics"]
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_BENCHMARK_RUN", "message": str(exc)}
        return report

    metrics = comparison.summary["metrics"]
    checks = {
        "time_regression": _percent_within(metrics["median_seconds"], max_time_regression),
        "token_regression": _percent_within(
            metrics["median_estimated_tokens"], max_token_regression
        ),
        "token_reduction": _minimum_reduction(
            metrics["median_estimated_tokens"], min_token_reduction
        ),
        "precision": _stat_value(stats, "median_selection_precision") >= min_precision,
        "recall": _stat_value(stats, "median_selection_recall") >= min_recall,
        "false_negatives": (
            _stat_value(stats, "total_false_negative_items") <= max_false_negatives
        ),
    }
    passed = all(checks.values())
    report.status = "success" if passed else "failed"
    report.summary = {
        "passed": passed,
        "checks": checks,
        "thresholds": {
            "max_time_regression_percent": max_time_regression,
            "max_token_regression_percent": max_token_regression,
            "min_token_reduction_percent": min_token_reduction,
            "min_precision": min_precision,
            "min_recall": min_recall,
            "max_false_negatives": max_false_negatives,
        },
        "candidate_statistics": stats,
        "comparison": comparison.summary,
    }
    for name, passed_check in checks.items():
        if not passed_check:
            report.issues.append(
                Issue("error", f"Benchmark gate failed: {name}", code="BENCHMARK_REGRESSION")
            )
    return report


def run_benchmark_corpus(
    project_root: Path, manifest: Path, *, trials: int = 3, timeout_seconds: int = 300
) -> Report:
    report = Report(command="benchmark corpus", project_root=project_root)
    path = manifest if manifest.is_absolute() else project_root / manifest
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        suites = spec["suites"]
        thresholds = spec["thresholds"]
        if (
            spec.get("schema_version") != "1.0"
            or not isinstance(suites, list)
            or not isinstance(thresholds, dict)
            or not 1 <= trials <= 50
        ):
            raise ValueError("Unsupported corpus manifest")
        gate_options: dict[str, Any] = {
            "max_time_regression": float(thresholds.get("max_time_regression_percent", 20)),
            "max_token_regression": float(thresholds.get("max_token_regression_percent", 5)),
            "min_token_reduction": float(thresholds.get("min_token_reduction_percent", 0)),
            "min_precision": float(thresholds.get("min_precision", 0.8)),
            "min_recall": float(thresholds.get("min_recall", 0.9)),
            "max_false_negatives": int(thresholds.get("max_false_negatives", 0)),
        }
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_BENCHMARK_CORPUS", "message": str(exc)}
        return report
    results: list[dict[str, Any]] = []
    for suite in suites:
        if not isinstance(suite, str):
            report.status = "invalid_configuration"
            report.summary = {"reason_code": "INVALID_BENCHMARK_CORPUS_SUITE"}
            return report
        baseline = run_benchmark(
            project_root, Path(suite), "baseline", trials=trials, timeout_seconds=timeout_seconds
        )
        candidate = run_benchmark(
            project_root, Path(suite), "ai-dev", trials=trials, timeout_seconds=timeout_seconds
        )
        baseline_path = _json_artifact(baseline)
        candidate_path = _json_artifact(candidate)
        if baseline_path is None or candidate_path is None:
            gate = Report(command="benchmark gate", project_root=project_root, status="failed")
            gate.summary = {"passed": False, "reason_code": "BENCHMARK_RUN_FAILED"}
        else:
            gate = gate_benchmarks(
                project_root,
                baseline_path,
                candidate_path,
                **gate_options,
            )
        results.append(
            {
                "suite": suite,
                "baseline_status": baseline.status,
                "candidate_status": candidate.status,
                "gate_status": gate.status,
                "checks": gate.summary.get("checks", {}),
            }
        )
    passed = bool(results) and all(row["gate_status"] == "success" for row in results)
    report.status = "success" if passed else "failed"
    report.summary = {
        "passed": passed,
        "manifest": str(path.resolve()),
        "suite_count": len(results),
        "results": results,
        "thresholds": thresholds,
    }
    if not passed:
        report.issues.append(
            Issue("error", "At least one corpus regression gate failed", code="CORPUS_REGRESSION")
        )
    output = project_root / ".ai" / "benchmarks" / f"corpus-{_timestamp()}.json"
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
        str(name): _command(value, f"variants.{name}") for name, value in variants_raw.items()
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
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a non-empty list of strings")
    return list(value)


def _trial_row(
    number: int,
    reset: CommandResult,
    execution: CommandResult,
    validation: CommandResult,
) -> dict[str, Any]:
    metrics, execution_visible = _execution_metrics(execution)
    visible = mask_text(execution_visible + validation.combined_output).encode("utf-8")
    actionable = metrics.get("actionable_seconds", execution.duration_seconds)
    commands = metrics.get("commands", 3)
    validation_subprocesses = metrics.get("validation_subprocesses", 1)
    selected_items = int(metrics.get("selected_items", 0))
    relevant_items = int(metrics.get("relevant_items", 0))
    true_positive_items = int(metrics.get("true_positive_items", 0))
    precision_reported = "selected_items" in metrics and "true_positive_items" in metrics
    recall_reported = "relevant_items" in metrics and "true_positive_items" in metrics
    false_negative_items = int(
        metrics.get(
            "false_negative_items",
            max(0, relevant_items - min(true_positive_items, relevant_items))
            if recall_reported
            else 0,
        )
    )
    return {
        "trial": number,
        "correct": reset.exit_code == execution.exit_code == validation.exit_code == 0,
        "duration_seconds": round(
            reset.duration_seconds + execution.duration_seconds + validation.duration_seconds,
            3,
        ),
        "time_to_actionable_result_seconds": round(reset.duration_seconds + float(actionable), 3),
        "commands": int(commands),
        "validation_subprocesses": int(validation_subprocesses),
        "agent_visible_bytes": len(visible),
        "estimated_tokens": math.ceil(len(visible) / 4),
        "reported_input_tokens": int(metrics.get("input_tokens", 0)),
        "reported_output_tokens": int(metrics.get("output_tokens", 0)),
        "iterations": int(metrics.get("iterations", 1)),
        "files_read": int(metrics.get("files_read", 0)),
        "selection_precision": (
            round(min(true_positive_items, selected_items) / selected_items, 4)
            if precision_reported and selected_items
            else 1.0
            if precision_reported
            else 0.0
        ),
        "selection_recall": (
            round(min(true_positive_items, relevant_items) / relevant_items, 4)
            if recall_reported and relevant_items
            else 1.0
            if recall_reported
            else 0.0
        ),
        "selection_metrics_reported": precision_reported and recall_reported,
        "false_negative_items": false_negative_items,
        "exit_codes": {
            "reset": reset.exit_code,
            "variant": execution.exit_code,
            "validation": validation.exit_code,
        },
        "outcome_signature": hashlib.sha256(validation.stdout.strip().encode("utf-8")).hexdigest(),
        "timed_out": reset.timed_out or execution.timed_out or validation.timed_out,
    }


def _execution_metrics(execution: CommandResult) -> tuple[dict[str, float | int], str]:
    metrics: dict[str, float | int] = {}
    visible_stderr: list[str] = []
    for line in execution.stderr.splitlines():
        if not line.startswith(METRICS_PREFIX):
            visible_stderr.append(line)
            continue
        try:
            payload = json.loads(line[len(METRICS_PREFIX) :])
        except json.JSONDecodeError:
            visible_stderr.append(line)
            continue
        if not isinstance(payload, dict):
            visible_stderr.append(line)
            continue
        parsed: dict[str, float | int] = {}
        for key in (
            "commands",
            "validation_subprocesses",
            "iterations",
            "files_read",
            "selected_items",
            "relevant_items",
            "true_positive_items",
            "false_negative_items",
            "input_tokens",
            "output_tokens",
        ):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                parsed[key] = value
        actionable = payload.get("actionable_seconds")
        if (
            isinstance(actionable, (int, float))
            and not isinstance(actionable, bool)
            and math.isfinite(actionable)
            and 0 <= actionable <= execution.duration_seconds
        ):
            parsed["actionable_seconds"] = float(actionable)
        if not parsed:
            visible_stderr.append(line)
            continue
        metrics.update(parsed)
    visible = execution.stdout
    if visible_stderr:
        stderr_text = "\n".join(visible_stderr)
        visible = f"{visible}\n{stderr_text}".strip()
    return metrics, visible


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
        "median_agent_visible_bytes": round(statistics.median(values("agent_visible_bytes")), 3),
        "median_estimated_tokens": round(statistics.median(values("estimated_tokens")), 3),
        "median_commands": round(statistics.median(values("commands")), 3),
        "median_iterations": round(statistics.median(values("iterations")), 3),
        "median_files_read": round(statistics.median(values("files_read")), 3),
        "median_selection_precision": round(statistics.median(values("selection_precision")), 4),
        "median_selection_recall": round(statistics.median(values("selection_recall")), 4),
        "total_false_negative_items": round(sum(values("false_negative_items")), 3),
        "selection_metric_trials": round(sum(values("selection_metrics_reported")), 3),
        "median_reported_input_tokens": round(
            statistics.median(values("reported_input_tokens")), 3
        ),
        "median_reported_output_tokens": round(
            statistics.median(values("reported_output_tokens")), 3
        ),
    }


def _stat_value(stats: dict[str, Any], key: str) -> float:
    value = stats.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _comparison(baseline: float, candidate: float) -> dict[str, float | None]:
    change = candidate - baseline
    return {
        "baseline": baseline,
        "candidate": candidate,
        "absolute_change": round(change, 3),
        "percent_change": round(change / baseline * 100, 2) if baseline else None,
    }


def _percent_within(metric: dict[str, Any], maximum: float) -> bool:
    change = metric.get("percent_change")
    return change is None or (isinstance(change, (int, float)) and change <= maximum)


def _minimum_reduction(metric: dict[str, Any], minimum: float) -> bool:
    if minimum == 0:
        return True
    change = metric.get("percent_change")
    return isinstance(change, (int, float)) and change <= -minimum


def _recommendation(metrics: dict[str, dict[str, float | None]], valid: bool) -> str:
    if not valid:
        return "reject_incorrect_candidate"
    recall_change = metrics["median_selection_recall"]["percent_change"]
    if isinstance(recall_change, float) and recall_change < 0:
        return "reject_selection_recall_regression"
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
    if not isinstance(data, dict) or not str(data.get("command", "")).startswith("benchmark run"):
        raise ValueError(f"Not a benchmark run: {resolved}")
    return data


def _json_artifact(report: Report) -> Path | None:
    for artifact in report.artifacts:
        if artifact.kind == "json":
            return Path(artifact.path)
    return None


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
