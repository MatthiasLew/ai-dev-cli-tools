from __future__ import annotations

import json
import sys
from pathlib import Path

from ai_dev_tools.cli import main
from ai_dev_tools.runners.benchmark import compare_benchmarks, run_benchmark


def _suite(root: Path) -> Path:
    path = root / "benchmark.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "name": "tiny-agent-workflow",
                "fixture_version": "fixture-1",
                "working_directory": ".",
                "reset_command": [sys.executable, "-c", "pass"],
                "validation_command": [sys.executable, "-c", "print('verified')"],
                "variants": {
                    "baseline": [sys.executable, "-c", "print('x' * 400)"],
                    "ai-dev": [sys.executable, "-c", "print('summary')"],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_benchmark_runs_and_compares_equivalent_variants(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    baseline = run_benchmark(tmp_path, suite, "baseline", trials=2)
    candidate = run_benchmark(tmp_path, suite, "ai-dev", trials=2)

    assert baseline.status == "success"
    assert baseline.summary["correct_trials"] == 2
    assert baseline.summary["statistics"]["median_agent_visible_bytes"] > (
        candidate.summary["statistics"]["median_agent_visible_bytes"]
    )
    baseline_path = Path(next(item.path for item in baseline.artifacts if item.kind == "json"))
    candidate_path = Path(next(item.path for item in candidate.artifacts if item.kind == "json"))

    compared = compare_benchmarks(tmp_path, baseline_path, candidate_path)

    assert compared.status == "success"
    assert compared.summary["valid"] is True
    assert compared.summary["metrics"]["median_estimated_tokens"]["percent_change"] < 0
    assert any(item.kind == "markdown" for item in compared.artifacts)


def test_benchmark_rejects_invalid_suite_variant_and_trial_count(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    assert run_benchmark(tmp_path, invalid, "baseline").status == "invalid_configuration"

    suite = _suite(tmp_path)
    unknown = run_benchmark(tmp_path, suite, "missing")
    bad_trials = run_benchmark(tmp_path, suite, "baseline", trials=0)

    assert unknown.summary["reason_code"] == "UNKNOWN_BENCHMARK_VARIANT"
    assert bad_trials.summary["reason_code"] == "INVALID_TRIAL_COUNT"


def test_benchmark_cli_is_wired(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    suite = _suite(tmp_path)

    exit_code = main(
        [
            "--project",
            str(tmp_path),
            "--json",
            "benchmark",
            "run",
            "--suite",
            str(suite),
            "--variant",
            "ai-dev",
            "--trials",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["summary"]["suite"] == "tiny-agent-workflow"
    assert payload["summary"]["token_estimation"] == "masked_utf8_bytes_divided_by_4"


def test_compare_requires_different_variants_and_matching_cache_state(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    first = run_benchmark(tmp_path, suite, "baseline", trials=1, cache_state="cold")
    second = run_benchmark(tmp_path, suite, "baseline", trials=1, cache_state="warm")
    first_path = Path(next(item.path for item in first.artifacts if item.kind == "json"))
    second_path = Path(next(item.path for item in second.artifacts if item.kind == "json"))

    compared = compare_benchmarks(tmp_path, first_path, second_path)

    assert compared.status == "invalid_configuration"
    assert compared.summary["reason_code"] == "INCOMPARABLE_BENCHMARK_RUNS"