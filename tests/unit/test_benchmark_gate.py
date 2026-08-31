from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.models.report import Artifact, Report
from ai_dev_tools.runners import benchmark
from ai_dev_tools.runners.benchmark import gate_benchmarks, run_benchmark_corpus


def _run(path: Path, variant: str, *, seconds: float, tokens: float) -> None:
    statistics = {
        "median_seconds": seconds,
        "median_time_to_actionable_result_seconds": seconds,
        "median_agent_visible_bytes": tokens * 4,
        "median_estimated_tokens": tokens,
        "median_commands": 1,
        "median_iterations": 1,
        "median_files_read": 2,
        "median_selection_precision": 1.0,
        "median_selection_recall": 1.0,
        "total_false_negative_items": 0,
    }
    payload = {
        "command": f"benchmark run --variant {variant}",
        "status": "success",
        "summary": {
            "suite": "fixture",
            "fixture_version": "1",
            "cache_state": "cold",
            "variant": variant,
            "correct_trials": 1,
            "trials": [{"outcome_signature": "same"}],
            "statistics": statistics,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_benchmark_gate_enforces_efficiency_and_quality_thresholds(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _run(baseline, "baseline", seconds=10, tokens=100)
    _run(candidate, "ai-dev", seconds=11, tokens=100)

    passed = gate_benchmarks(tmp_path, baseline, candidate)
    assert passed.status == "success"
    assert passed.summary["passed"] is True

    _run(candidate, "ai-dev", seconds=11, tokens=120)
    failed = gate_benchmarks(tmp_path, baseline, candidate)
    assert failed.status == "failed"
    assert failed.summary["checks"]["token_regression"] is False

    _run(candidate, "ai-dev", seconds=11, tokens=90)
    reduced = gate_benchmarks(
        tmp_path, baseline, candidate, min_token_reduction=15
    )
    assert reduced.status == "failed"
    assert reduced.summary["checks"]["token_reduction"] is False

    _run(candidate, "ai-dev", seconds=11, tokens=80)
    reduced = gate_benchmarks(
        tmp_path, baseline, candidate, min_token_reduction=15
    )
    assert reduced.status == "success"


def test_corpus_runs_every_suite_and_aggregates_gates(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "corpus.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "suites": ["one.json", "two.json"],
                "thresholds": {"min_recall": 0.9},
            }
        ),
        encoding="utf-8",
    )

    def fake_run(root: Path, suite: Path, variant: str, **kwargs: object) -> Report:
        report = Report(command=f"benchmark run --variant {variant}", project_root=root)
        report.artifacts.append(Artifact(str(root / f"{suite.stem}-{variant}.json"), "json", "run"))
        return report

    def fake_gate(root: Path, baseline: Path, candidate: Path, **kwargs: object) -> Report:
        report = Report(command="benchmark gate", project_root=root)
        report.summary = {"passed": True, "checks": {"recall": True}}
        return report

    monkeypatch.setattr(benchmark, "run_benchmark", fake_run)
    monkeypatch.setattr(benchmark, "gate_benchmarks", fake_gate)
    report = run_benchmark_corpus(tmp_path, manifest, trials=1)

    assert report.status == "success"
    assert report.summary["suite_count"] == 2


def test_corpus_rejects_invalid_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "corpus.json"
    manifest.write_text('{"schema_version":"2"}', encoding="utf-8")
    report = run_benchmark_corpus(tmp_path, manifest)
    assert report.status == "invalid_configuration"


def test_gate_rejects_invalid_thresholds_and_incomparable_runs(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    invalid = gate_benchmarks(tmp_path, missing, missing, min_recall=2)
    assert invalid.status == "invalid_configuration"

    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _run(baseline, "baseline", seconds=1, tokens=1)
    _run(candidate, "ai-dev", seconds=1, tokens=1)
    payload = json.loads(candidate.read_text())
    payload["summary"]["trials"][0]["outcome_signature"] = "different"
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    failed = gate_benchmarks(tmp_path, baseline, candidate)
    assert failed.status == "failed"
    assert failed.summary["reason_code"] == "BENCHMARK_EQUIVALENCE_FAILED"


def test_corpus_reports_failed_suite_gate(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "corpus.json"
    manifest.write_text(
        json.dumps({"schema_version": "1.0", "suites": ["one.json"], "thresholds": {}}),
        encoding="utf-8",
    )

    def fake_run(root: Path, suite: Path, variant: str, **kwargs: object) -> Report:
        report = Report(command=f"benchmark run --variant {variant}", project_root=root)
        report.artifacts.append(Artifact(str(root / f"{variant}.json"), "json", "run"))
        return report

    def fake_gate(root: Path, baseline: Path, candidate: Path, **kwargs: object) -> Report:
        report = Report(command="benchmark gate", project_root=root, status="failed")
        report.summary = {"passed": False, "checks": {"time_regression": False}}
        return report

    monkeypatch.setattr(benchmark, "run_benchmark", fake_run)
    monkeypatch.setattr(benchmark, "gate_benchmarks", fake_gate)
    report = run_benchmark_corpus(tmp_path, manifest, trials=1)
    assert report.status == "failed"
    assert report.issues[0].code == "CORPUS_REGRESSION"
