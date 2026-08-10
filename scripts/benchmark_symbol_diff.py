from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_dev_tools.git.symbol_diff import analyze_symbol_diff


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"baseline", "symbol"}:
        print("usage: benchmark_symbol_diff.py baseline|symbol", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="ai-dev-symbol-benchmark-") as temporary:
        root = Path(temporary)
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.email", "benchmark@example.com")
        _git(root, "config", "user.name", "Benchmark")
        source = root / "service.py"
        before = _source("value + 1")
        after = _source("value + 2")
        source.write_text(before, encoding="utf-8")
        _git(root, "add", "service.py")
        _git(root, "commit", "-m", "fixture")
        source.write_text(after, encoding="utf-8")

        if sys.argv[1] == "baseline":
            result = subprocess.run(
                ["git", "diff", "--unified=80", "--", "service.py"],
                cwd=root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                shell=False,
                check=True,
            )
            print(result.stdout, end="")
            return 0

        result = analyze_symbol_diff(root, ["service.py"])
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0


def _source(changed_expression: str) -> str:
    lines = ["def calculate(value):"]
    lines.extend(f"    step_{index} = value + {index}" for index in range(1, 160))
    lines.append(f"    result = {changed_expression}")
    lines.append("    return result")
    lines.extend(["", "def unchanged():", "    return 1", ""])
    return "\n".join(lines)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=False,
        check=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
