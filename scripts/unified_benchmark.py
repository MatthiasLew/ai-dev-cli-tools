"""Unified Performance Benchmark Harness.

Measures median and p95 across process startup overhead and internal execution
for key commands:
- git status
- git inspect
- index update (cold vs warm)
- semantic index (cold vs warm)
- context build (cold vs warm)
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import platform
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from ai_dev_tools.cache.repository import read_repository_index
from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.runners.index import run_index
from ai_dev_tools.semantic import run_semantic


def calc_stats(samples_ms: list[float]) -> dict[str, float]:
    if not samples_ms:
        return {"median_ms": 0.0, "p95_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0, "count": 0.0}
    sorted_s = sorted(samples_ms)
    n = len(sorted_s)
    k = (n - 1) * 0.95
    f = math.floor(k)
    c = math.ceil(k)
    p95 = sorted_s[int(k)] if f == c else sorted_s[f] * (c - k) + sorted_s[c] * (k - f)
    return {
        "median_ms": round(statistics.median(samples_ms), 2),
        "p95_ms": round(p95, 2),
        "min_ms": round(min(samples_ms), 2),
        "max_ms": round(max(samples_ms), 2),
        "count": float(n),
    }


def measure_cli(cmd_args: list[str], root: Path, iterations: int) -> list[float]:
    samples: list[float] = []
    base_cmd = [sys.executable, "-m", "ai_dev_tools.cli", "--project", str(root)] + cmd_args
    for _ in range(iterations):
        t0 = time.perf_counter()
        proc = subprocess.run(
            base_cmd,
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        t1 = time.perf_counter()
        if proc.returncode in (0, 1):
            samples.append((t1 - t0) * 1000)
    return samples


def measure_internal(fn: Callable[[], object], iterations: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        samples.append((t1 - t0) * 1000)
    return samples


def _measure_python_baseline_startup(iterations: int = 5) -> float:
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        subprocess.run(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        samples.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(samples), 2)


def _reset_context_cold(root: Path) -> None:
    shutil.rmtree(root / ".ai" / "context", ignore_errors=True)
    shutil.rmtree(root / ".ai" / "cache" / "context-manifests", ignore_errors=True)
    manifest = root / ".ai" / "cache" / "context-manifest.json"
    if manifest.exists():
        manifest.unlink()
    idx = root / ".ai" / "cache" / "repository-index.json"
    if idx.exists():
        idx.unlink()


def run_benchmarks(project_root: Path, iterations: int = 10) -> dict[str, object]:
    resolved_root = project_root.resolve()
    results: list[dict[str, object]] = []

    # Pre-warm repository index
    idx = read_repository_index(resolved_root)
    file_count = len(idx.get("entries", [])) if idx else 0
    python_baseline_ms = _measure_python_baseline_startup(5)

    # 1. git status
    cli_git_status = measure_cli(["git", "status"], resolved_root, iterations)
    int_git_status = measure_internal(
        lambda: inspect_git(resolved_root, detailed=False), iterations
    )
    p_stat = calc_stats(cli_git_status)
    i_stat = calc_stats(int_git_status)
    results.append({
        "command": "git status",
        "mode": "status",
        "process": p_stat,
        "internal": i_stat,
        "cli_process_overhead_ms": round(p_stat["median_ms"] - i_stat["median_ms"], 2),
    })

    # 2. git inspect
    cli_git_inspect = measure_cli(["git", "inspect"], resolved_root, iterations)
    int_git_inspect = measure_internal(
        lambda: inspect_git(resolved_root, detailed=True), iterations
    )
    p_insp = calc_stats(cli_git_inspect)
    i_insp = calc_stats(int_git_inspect)
    results.append({
        "command": "git inspect",
        "mode": "inspect",
        "process": p_insp,
        "internal": i_insp,
        "cli_process_overhead_ms": round(p_insp["median_ms"] - i_insp["median_ms"], 2),
    })

    # 3. index update (cold vs warm)
    cli_idx_cold = measure_cli(["index", "rebuild"], resolved_root, iterations)
    int_idx_cold = measure_internal(lambda: run_index(resolved_root, "rebuild"), iterations)
    p_ic = calc_stats(cli_idx_cold)
    i_ic = calc_stats(int_idx_cold)
    results.append({
        "command": "index update",
        "mode": "cold (rebuild)",
        "process": p_ic,
        "internal": i_ic,
        "cli_process_overhead_ms": round(p_ic["median_ms"] - i_ic["median_ms"], 2),
    })

    cli_idx_warm = measure_cli(["index", "update"], resolved_root, iterations)
    int_idx_warm = measure_internal(lambda: run_index(resolved_root, "update"), iterations)
    p_iw = calc_stats(cli_idx_warm)
    i_iw = calc_stats(int_idx_warm)
    results.append({
        "command": "index update",
        "mode": "warm (cached)",
        "process": p_iw,
        "internal": i_iw,
        "cli_process_overhead_ms": round(p_iw["median_ms"] - i_iw["median_ms"], 2),
    })

    # 4. semantic index (cold vs warm)
    cli_sem_cold = measure_cli(["semantic", "index", "--rebuild"], resolved_root, iterations)
    int_sem_cold = measure_internal(
        lambda: run_semantic(resolved_root, "index", rebuild=True), iterations
    )
    p_sc = calc_stats(cli_sem_cold)
    i_sc = calc_stats(int_sem_cold)
    results.append({
        "command": "semantic index",
        "mode": "cold (rebuild)",
        "process": p_sc,
        "internal": i_sc,
        "cli_process_overhead_ms": round(p_sc["median_ms"] - i_sc["median_ms"], 2),
    })

    cli_sem_warm = measure_cli(["semantic", "index"], resolved_root, iterations)
    int_sem_warm = measure_internal(
        lambda: run_semantic(resolved_root, "index", rebuild=False), iterations
    )
    p_sw = calc_stats(cli_sem_warm)
    i_sw = calc_stats(int_sem_warm)
    results.append({
        "command": "semantic index",
        "mode": "warm (cached)",
        "process": p_sw,
        "internal": i_sw,
        "cli_process_overhead_ms": round(p_sw["median_ms"] - i_sw["median_ms"], 2),
    })

    # 5. context build (cold, warm, incremental)
    opts = ContextOptions(task="benchmark", profile="default")

    # 5a. Cold: reset repository index, manifests, and generated context
    def run_ctx_cold() -> object:
        _reset_context_cold(resolved_root)
        return build_context(resolved_root, opts)

    int_ctx_cold = measure_internal(run_ctx_cold, iterations)
    cli_ctx_cold: list[float] = []
    for _ in range(iterations):
        _reset_context_cold(resolved_root)
        t0 = time.perf_counter()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "ai_dev_tools.cli",
                "--project",
                str(resolved_root),
                "context",
                "build",
            ],
            cwd=str(resolved_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        cli_ctx_cold.append((time.perf_counter() - t0) * 1000)

    p_cc = calc_stats(cli_ctx_cold)
    i_cc = calc_stats(int_ctx_cold)
    results.append({
        "command": "context build",
        "mode": "cold (no cache/manifests)",
        "process": p_cc,
        "internal": i_cc,
        "cli_process_overhead_ms": round(p_cc["median_ms"] - i_cc["median_ms"], 2),
    })

    # 5b. Warm: all caches and manifests present, repo unchanged
    build_context(resolved_root, opts)
    cli_ctx_warm = measure_cli(["context", "build"], resolved_root, iterations)
    int_ctx_warm = measure_internal(lambda: build_context(resolved_root, opts), iterations)
    p_cw = calc_stats(cli_ctx_warm)
    i_cw = calc_stats(int_ctx_warm)
    results.append({
        "command": "context build",
        "mode": "warm (cached, 0 changes)",
        "process": p_cw,
        "internal": i_cw,
        "cli_process_overhead_ms": round(p_cw["median_ms"] - i_cw["median_ms"], 2),
    })

    # 5c. Incremental: 1 file modified with incremental selection
    scratch_file = resolved_root / "tests" / "unit" / "_benchmark_scratch.py"
    opts_inc = ContextOptions(task="benchmark", profile="default", incremental=True)

    def run_ctx_inc() -> object:
        scratch_content = f"# scratch {time.perf_counter()}\ndef b(): pass\n"
        scratch_file.write_text(scratch_content, encoding="utf-8")
        try:
            return build_context(resolved_root, opts_inc)
        finally:
            if scratch_file.exists():
                scratch_file.unlink()

    int_ctx_inc = measure_internal(run_ctx_inc, iterations)
    cli_ctx_inc: list[float] = []
    for _ in range(iterations):
        scratch_content = f"# scratch {time.perf_counter()}\ndef b(): pass\n"
        scratch_file.write_text(scratch_content, encoding="utf-8")
        t0 = time.perf_counter()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "ai_dev_tools.cli",
                "--project",
                str(resolved_root),
                "context",
                "build",
                "--incremental",
            ],
            cwd=str(resolved_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        cli_ctx_inc.append((time.perf_counter() - t0) * 1000)
        if scratch_file.exists():
            scratch_file.unlink()

    p_ci = calc_stats(cli_ctx_inc)
    i_ci = calc_stats(int_ctx_inc)
    results.append({
        "command": "context build",
        "mode": "incremental (1-file mod)",
        "process": p_ci,
        "internal": i_ci,
        "cli_process_overhead_ms": round(p_ci["median_ms"] - i_ci["median_ms"], 2),
    })

    report = {
        "metadata": {
            "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "architecture": platform.machine(),
            "python_version": sys.version.split()[0],
            "python_baseline_startup_ms": python_baseline_ms,
            "repo_files": file_count,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "samples_per_command": iterations,
            "context_benchmark_modes_documentation": {
                "cold": "Resets repository-index.json, context-manifest.json, and .ai/context/",
                "warm": "All caches and manifests exist, repository is unchanged",
                "incremental": (
                    "Warm state with exactly 1 scratch file modified and --incremental flag"
                ),
            },
        },
        "benchmarks": results,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Performance Benchmark Harness")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = run_benchmarks(args.project, args.iterations)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report written to {args.output}")

    print("=" * 115)
    meta = report["metadata"]  # type: ignore[index]
    baseline_str = f"pure startup baseline: {meta['python_baseline_startup_ms']} ms"
    print(
        f"Platform: {meta['platform']} | Python: {meta['python_version']} ({baseline_str}) | "
        f"Repo files: {meta['repo_files']} | N={meta['samples_per_command']}"
    )
    print("=" * 115)
    print(
        f"{'Command':<16} | {'Mode':<26} | {'Internal Med':>12} | "
        f"{'Internal p95':>12} | {'Proc Med':>10} | {'Proc p95':>10} | {'CLI Overhead':>12}"
    )
    print("-" * 115)
    for b in report["benchmarks"]:  # type: ignore[union-attr]
        im = b["internal"]["median_ms"]
        ip = b["internal"]["p95_ms"]
        pm = b["process"]["median_ms"]
        pp = b["process"]["p95_ms"]
        oh = b["cli_process_overhead_ms"]
        print(
            f"{b['command']: <16} | {b['mode']: <26} | {im:>10.2f} ms | "
            f"{ip:>10.2f} ms | {pm:>8.2f} ms | {pp:>8.2f} ms | {oh:>10.2f} ms"
        )
    print("=" * 115)


if __name__ == "__main__":
    main()
