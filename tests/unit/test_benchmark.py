from __future__ import annotations

import json
import sys
from pathlib import Path

from ai_dev_tools.cli import main
from ai_dev_tools.runners.benchmark import (
    METRICS_PREFIX,
    _execution_metrics,
    _load_spec,
    _trial_row,
    compare_benchmarks,
    gate_benchmarks,
    run_benchmark,
)
from ai_dev_tools.utils.subprocess import CommandResult


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


def test_benchmark_labels_client_and_can_require_provider_reported_tokens(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    baseline = run_benchmark(tmp_path, suite, "baseline", trials=1, client="codex")
    candidate = run_benchmark(tmp_path, suite, "ai-dev", trials=1, client="codex")
    baseline_path = Path(next(item.path for item in baseline.artifacts if item.kind == "json"))
    candidate_path = Path(next(item.path for item in candidate.artifacts if item.kind == "json"))

    gated = gate_benchmarks(
        tmp_path, baseline_path, candidate_path, require_reported_tokens=True
    )

    assert candidate.summary["client"] == "codex"
    assert candidate.summary["statistics"]["reported_token_trials"] == 0
    assert gated.status == "failed"
    assert gated.summary["checks"]["reported_tokens"] is False


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
    assert payload["summary"]["statistics"]["median_iterations"] >= 1
    assert "median_selection_recall" in payload["summary"]["statistics"]


def test_compare_requires_different_variants_and_matching_cache_state(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    first = run_benchmark(tmp_path, suite, "baseline", trials=1, cache_state="cold")
    second = run_benchmark(tmp_path, suite, "baseline", trials=1, cache_state="warm")
    first_path = Path(next(item.path for item in first.artifacts if item.kind == "json"))
    second_path = Path(next(item.path for item in second.artifacts if item.kind == "json"))

    compared = compare_benchmarks(tmp_path, first_path, second_path)

    assert compared.status == "invalid_configuration"
    assert compared.summary["reason_code"] == "INCOMPARABLE_BENCHMARK_RUNS"


def test_trial_uses_private_execution_metrics_without_counting_them_as_visible_output() -> None:
    reset = CommandResult(["reset"], 0, "", "", 0.1, False)
    execution = CommandResult(
        ["agent"],
        0,
        "concise result",
        f'{METRICS_PREFIX}{{"commands": 7, "validation_subprocesses": 2, '
        '"actionable_seconds": 0.25}\n',
        0.5,
        False,
    )
    validation = CommandResult(["validate"], 0, "verified\n", "", 0.2, False)

    row = _trial_row(1, reset, execution, validation)

    assert row["commands"] == 7
    assert row["validation_subprocesses"] == 2
    assert row["time_to_actionable_result_seconds"] == 0.35
    assert row["agent_visible_bytes"] == len(b"concise resultverified")


def test_invalid_execution_metrics_remain_visible_and_do_not_override_defaults() -> None:
    execution = CommandResult(
        ["agent"],
        0,
        "result",
        f"{METRICS_PREFIX}not-json\n{METRICS_PREFIX}[1, 2]\nwarning",
        0.5,
        False,
    )

    metrics, visible = _execution_metrics(execution)

    assert metrics == {}
    assert f"{METRICS_PREFIX}not-json" in visible
    assert f"{METRICS_PREFIX}[1, 2]" in visible
    assert "warning" in visible

def test_versioned_agent_workflow_manifests_share_the_final_fixture() -> None:
    root = Path(__file__).resolve().parents[2]
    scenarios = ("repair", "affected", "multiturn", "monorepo")

    for scenario in scenarios:
        manifest = root / "examples" / "benchmarks" / f"agent-{scenario}-workflow.json"
        spec = _load_spec(root, manifest)

        assert spec["fixture_version"] == "1"
        assert spec["working_directory"].name == "agent-workflow"
        assert set(spec["variants"]) == {"baseline", "ai-dev"}
        assert spec["validation_command"][-2:] == [scenario, "validate"]
