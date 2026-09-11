"""Synthetic benchmark measuring semantic-cache scalability.

Tests 10k, 50k, 100k, and 250k symbols.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import tracemalloc
from pathlib import Path

from ai_dev_tools.semantic import run_semantic


def run_benchmark_for_scale(n_symbols: int, symbols_per_file: int = 50) -> dict[str, object]:
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"bench_semantic_{n_symbols}_"))
    try:
        n_files = n_symbols // symbols_per_file
        # Generate files
        file_content = (
            "\n".join(f"def func_{j}():\n    return {j}" for j in range(symbols_per_file))
            + "\n"
        )
        for i in range(n_files):
            (tmp_dir / f"module_{i:04d}.py").write_text(file_content, encoding="utf-8")

        # 1. Measure Cold Build
        tracemalloc.start()
        t0 = time.perf_counter()
        rep_cold = run_semantic(tmp_dir, "index", backend="structural")
        cold_time = time.perf_counter() - t0
        _, peak_mem_cold = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert rep_cold.status in ("success", "partial")

        cache_path = tmp_dir / ".ai" / "cache" / "semantic-cache.json"
        assert cache_path.exists()
        cache_size_bytes = cache_path.stat().st_size
        cache_size_mb = cache_size_bytes / (1024 * 1024)

        # 2. Pure JSON load and serialize time
        cache_text = cache_path.read_text(encoding="utf-8")
        tracemalloc.start()
        t_load_0 = time.perf_counter()
        data = json.loads(cache_text)
        load_time = time.perf_counter() - t_load_0

        t_dump_0 = time.perf_counter()
        _ = json.dumps(data)
        dump_time = time.perf_counter() - t_dump_0
        _, peak_mem_json = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # 3. Measure Warm Build (no files changed)
        tracemalloc.start()
        t0 = time.perf_counter()
        rep_warm = run_semantic(tmp_dir, "index", backend="structural")
        warm_time = time.perf_counter() - t0
        _, peak_mem_warm = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert rep_warm.status in ("success", "partial")

        # 4. Measure 1-file modification (incremental update)
        extra_content = file_content + "\ndef extra_func(): pass\n"
        (tmp_dir / "module_0000.py").write_text(extra_content, encoding="utf-8")
        tracemalloc.start()
        t0 = time.perf_counter()
        rep_inc = run_semantic(tmp_dir, "index", backend="structural")
        inc_time = time.perf_counter() - t0
        _, peak_mem_inc = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert rep_inc.status in ("success", "partial")

        peak_bytes = max(peak_mem_cold, peak_mem_warm, peak_mem_inc, peak_mem_json)
        return {
            "symbols": n_symbols,
            "files": n_files,
            "cold_build_ms": round(cold_time * 1000, 2),
            "warm_build_ms": round(warm_time * 1000, 2),
            "one_file_mod_ms": round(inc_time * 1000, 2),
            "cache_size_mb": round(cache_size_mb, 2),
            "json_load_ms": round(load_time * 1000, 2),
            "json_dump_ms": round(dump_time * 1000, 2),
            "peak_mem_mb": round(peak_bytes / (1024 * 1024), 2),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    scales = [10_000, 50_000, 100_000, 250_000]
    results = []
    header = (
        f"{'Symbols':>8} | {'Files':>6} | {'Cold (ms)':>10} | {'Warm (ms)':>10} | "
        f"{'1-Mod (ms)':>10} | {'Size (MB)':>10} | {'Load (ms)':>10} | "
        f"{'Dump (ms)':>10} | {'Peak RAM':>10}"
    )
    print(header)
    print("-" * 95)
    for scale in scales:
        res = run_benchmark_for_scale(scale)
        results.append(res)
        print(
            f"{res['symbols']:>8} | {res['files']:>6} | {res['cold_build_ms']:>10.2f} | "
            f"{res['warm_build_ms']:>10.2f} | {res['one_file_mod_ms']:>10.2f} | "
            f"{res['cache_size_mb']:>10.2f} | {res['json_load_ms']:>10.2f} | "
            f"{res['json_dump_ms']:>10.2f} | {res['peak_mem_mb']:>8.2f} MB"
        )

    print("\nJSON Results:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
