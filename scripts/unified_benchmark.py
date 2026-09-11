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
        return {"median_ms": 0.0, "p95_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
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
        if proc.returncode == 0:
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


def run_benchmarks(root: Path, iterations: int = 10) -> dict[str, object]:
    resolved_root = root.resolve()
    idx = read_repository_index(resolved_root)
    file_count = (
        len(idx.get("entries", []))  # type: ignore[arg-type]
        if idx
        else sum(1 for _ in resolved_root.rglob("*") if _.is_file())
    )

    results: list[dict[str, object]] = []

    # 1. git status
    cli_git_status = measure_cli(["git", "status"], resolved_root, iterations)
    int_git_status = measure_internal(
        lambda: inspect_git(resolved_root, detailed=False), iterations
    )
    results.append({
        "command": "git status",
        "mode": "status",
        "process": calc_stats(cli_git_status),
        "internal": calc_stats(int_git_status),
    })

    # 2. git inspect
    cli_git_inspect = measure_cli(["git", "inspect"], resolved_root, iterations)
    int_git_inspect = measure_internal(
        lambda: inspect_git(resolved_root, detailed=True), iterations
    )
    results.append({
        "command": "git inspect",
        "mode": "inspect",
        "process": calc_stats(cli_git_inspect),
        "internal": calc_stats(int_git_inspect),
    })

    # 3. index update (cold vs warm)
    cli_idx_cold = measure_cli(["index", "rebuild"], resolved_root, iterations)
    int_idx_cold = measure_internal(lambda: run_index(resolved_root, "rebuild"), iterations)
    results.append({
        "command": "index update",
        "mode": "cold (rebuild)",
        "process": calc_stats(cli_idx_cold),
        "internal": calc_stats(int_idx_cold),
    })

    cli_idx_warm = measure_cli(["index", "update"], resolved_root, iterations)
    int_idx_warm = measure_internal(lambda: run_index(resolved_root, "update"), iterations)
    results.append({
        "command": "index update",
        "mode": "warm (cached)",
        "process": calc_stats(cli_idx_warm),
        "internal": calc_stats(int_idx_warm),
    })

    # 4. semantic index (cold vs warm)
    cli_sem_cold = measure_cli(["semantic", "index", "--rebuild"], resolved_root, iterations)
    int_sem_cold = measure_internal(
        lambda: run_semantic(resolved_root, "index", rebuild=True), iterations
    )
    results.append({
        "command": "semantic index",
        "mode": "cold (rebuild)",
        "process": calc_stats(cli_sem_cold),
        "internal": calc_stats(int_sem_cold),
    })

    cli_sem_warm = measure_cli(["semantic", "index"], resolved_root, iterations)
    int_sem_warm = measure_internal(
        lambda: run_semantic(resolved_root, "index", rebuild=False), iterations
    )
    results.append({
        "command": "semantic index",
        "mode": "warm (cached)",
        "process": calc_stats(cli_sem_warm),
        "internal": calc_stats(int_sem_warm),
    })

    # 5. context build (cold vs warm)
    opts = ContextOptions(task="benchmark", profile="default")
    ctx_cache = resolved_root / ".ai" / "cache" / "context-default.json"

    def run_ctx_cold() -> object:
        if ctx_cache.exists():
            ctx_cache.unlink()
        return build_context(resolved_root, opts)

    int_ctx_cold = measure_internal(run_ctx_cold, iterations)
    cli_ctx_cold: list[float] = []
    for _ in range(iterations):
        if ctx_cache.exists():
            ctx_cache.unlink()
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

    results.append({
        "command": "context build",
        "mode": "cold (no cache)",
        "process": calc_stats(cli_ctx_cold),
        "internal": calc_stats(int_ctx_cold),
    })

    cli_ctx_warm = measure_cli(["context", "build"], resolved_root, iterations)
    int_ctx_warm = measure_internal(lambda: build_context(resolved_root, opts), iterations)
    results.append({
        "command": "context build",
        "mode": "warm (cached)",
        "process": calc_stats(cli_ctx_warm),
        "internal": calc_stats(int_ctx_warm),
    })

    report = {
        "metadata": {
            "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python_version": sys.version.split()[0],
            "repo_files": file_count,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "samples_per_command": iterations,
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

    print("=" * 95)
    meta = report["metadata"]  # type: ignore[index]
    print(
        f"Platform: {meta['platform']} | Python: {meta['python_version']} | "
        f"Repo files: {meta['repo_files']} | N={meta['samples_per_command']}"
    )
    print("=" * 95)
    print(
        f"{'Command':<18} | {'Mode':<18} | {'Internal Med':>12} | "
        f"{'Internal p95':>12} | {'Proc Med':>10} | {'Proc p95':>10}"
    )
    print("-" * 95)
    for b in report["benchmarks"]:  # type: ignore[union-attr]
        im = b["internal"]["median_ms"]
        ip = b["internal"]["p95_ms"]
        pm = b["process"]["median_ms"]
        pp = b["process"]["p95_ms"]
        print(
            f"{b['command']: <18} | {b['mode']: <18} | {im:>10.2f} ms | "
            f"{ip:>10.2f} ms | {pm:>8.2f} ms | {pp:>8.2f} ms"
        )
    print("=" * 95)


if __name__ == "__main__":
    main()
