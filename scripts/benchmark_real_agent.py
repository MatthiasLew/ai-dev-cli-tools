"""Run a user-configured agent driver against a disposable pricing fixture."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / ".ai" / "tmp" / "real-agent-repair"
SOURCE = Path("src/pricing.py")
REFERENCE = ROOT / "examples" / "benchmarks" / "fixtures" / "agent-workflow" / SOURCE
MARKER = "ai-dev real agent fixture v1\n"
PROMPT = (
    "Correct calculate_total so it adds the normalized subtotal and tax. "
    "Preserve normalization and preserve unrelated behavior. Edit only src/pricing.py."
)
ORACLE = """\
import runpy
module = runpy.run_path('src/pricing.py')
total = module['calculate_total']
for subtotal, tax, expected in ((1000, 230, 1230), (-10, 20, 20), (30, -5, 30), (0, 0, 0)):
    assert total(subtotal, tax) == expected, (subtotal, tax, expected)
assert module['format_total'](1230) == '12.30'
print('Verified pricing and normalization')
"""


def run_trial(variant: str) -> int:
    config = Path(os.environ["AI_DEV_BENCHMARK_AGENT_CONFIG"]).read_text(encoding="utf-8")
    argv = json.loads(config)[variant]
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
        raise ValueError(f"Configure {variant} as a non-empty JSON array of strings")
    env = {
        **os.environ,
        "AI_DEV_BENCHMARK_VARIANT": variant,
        "AI_DEV_BENCHMARK_PROMPT": PROMPT,
    }
    return subprocess.run(argv, cwd=FIXTURE, env=env, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("reset", "baseline", "ai-dev", "validate"))
    action = parser.parse_args().action
    if action == "reset":
        if FIXTURE.resolve() != FIXTURE or (FIXTURE.exists() and not FIXTURE.is_dir()):
            raise ValueError(f"Unexpected fixture path: {FIXTURE}")
        marker = FIXTURE / ".fixture-marker"
        if FIXTURE.exists():
            if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER:
                raise ValueError(f"Refusing to replace unrecognized fixture directory: {FIXTURE}")
            shutil.rmtree(FIXTURE)
        (FIXTURE / SOURCE).parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(MARKER, encoding="utf-8")
        source = REFERENCE.read_text(encoding="utf-8").replace(
            "return subtotal + tax", "return subtotal - tax", 1
        )
        (FIXTURE / SOURCE).write_text(source, encoding="utf-8", newline="\n")
        (FIXTURE / "pyproject.toml").write_text(
            '[project]\nname = "pricing-fixture"\nversion = "0"\n', encoding="utf-8"
        )
        return 0
    if action == "validate":
        return subprocess.run(
            [sys.executable, "-I", "-S", "-c", ORACLE],
            cwd=FIXTURE,
            check=False,
        ).returncode
    return run_trial(action)


if __name__ == "__main__":
    raise SystemExit(main())
