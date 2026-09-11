from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest

from ai_dev_tools.community.config import save_community_config
from ai_dev_tools.community.service import record_command_event
from ai_dev_tools.models.report import Report


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_NO_AUTO_FLUSH", "1")


def _p95(samples: list[float]) -> float:
    sorted_samples = sorted(samples)
    idx = int(0.95 * len(sorted_samples))
    return sorted_samples[min(idx, len(sorted_samples) - 1)]


def test_measure_telemetry_overhead(tmp_path: Path) -> None:
    report = Report(command="scan", project_root=tmp_path)
    report.status = "success"
    report.summary = {
        "client": "cursor",
        "model": "claude-3-5-sonnet",
        "task_kind": "feature",
        "selected_files": [{"path": "foo.py", "reason_code": "IMPORT"}],
    }

    iterations = 50

    # 1. OFF
    save_community_config("off")
    off_times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        record_command_event(report, 0.05, tmp_path)
        off_times.append(time.perf_counter() - t0)

    # 2. BASIC
    save_community_config("basic")
    basic_times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        record_command_event(report, 0.05, tmp_path)
        basic_times.append(time.perf_counter() - t0)

    # 3. RESEARCH
    save_community_config("research")
    research_times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        record_command_event(report, 0.05, tmp_path)
        research_times.append(time.perf_counter() - t0)

    off_median_ms = statistics.median(off_times) * 1000.0
    off_p95_ms = _p95(off_times) * 1000.0

    basic_median_ms = statistics.median(basic_times) * 1000.0
    basic_p95_ms = _p95(basic_times) * 1000.0

    research_median_ms = statistics.median(research_times) * 1000.0
    research_p95_ms = _p95(research_times) * 1000.0

    print(
        f"\n[Community Telemetry Overhead Benchmark ({iterations} iterations)]\n"
        f"  OFF:      median = {off_median_ms:.3f} ms, p95 = {off_p95_ms:.3f} ms\n"
        f"  BASIC:    median = {basic_median_ms:.3f} ms, p95 = {basic_p95_ms:.3f} ms\n"
        f"  RESEARCH: median = {research_median_ms:.3f} ms, p95 = {research_p95_ms:.3f} ms\n"
    )

    # OFF must have virtually zero overhead (< 1.0 ms)
    assert off_median_ms < 1.0, f"OFF median overhead was {off_median_ms:.3f} ms"
