"""Exercise CLI and MCP against a generated Git repository with known outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".ai" / "tmp" / "repository-benchmark-v1"
SOURCE = "packages/service/pricing.py"
TEST = "tests/test_pricing.py"
SIZES = {"small": (1, 4), "monorepo": (40, 25)}
MARKER = "ai-dev repository benchmark fixture v1\n"


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def read_json(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


def run(root: Path, command: list[str], request: str | None = None) -> str:
    return subprocess.run(
        command,
        cwd=root,
        input=request,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    ).stdout


def git(root: Path, *args: str) -> None:
    run(root, ["git", *args])


def cli(root: Path, *args: str, request: str | None = None) -> str:
    return run(root, [sys.executable, "-m", "ai_dev_tools", "--json", *args], request)


def remove_git_fixture(root: Path) -> None:
    def retry_readonly(
        operation: Callable[..., object],
        path: str,
        error: tuple[type[BaseException], BaseException, TracebackType | None],
    ) -> None:
        target = Path(path)
        if (
            os.name != "nt"
            or operation is not os.unlink
            or not isinstance(error[1], PermissionError)
            or root not in target.resolve().parents
        ):
            raise error[1]
        target.chmod(stat.S_IWRITE)
        target.unlink()

    shutil.rmtree(root, onerror=retry_readonly)


def reset(root: Path, size: str) -> None:
    marker = SCRATCH / f"{size}.marker"
    if root.resolve() != root:
        raise ValueError(f"Unexpected fixture path: {root}")
    if root.exists():
        if not marker.is_file():
            raise ValueError(f"Refusing to replace unrecognized fixture directory: {root}")
        if marker.read_text(encoding="utf-8") != MARKER:
            raise ValueError(f"Unrecognized fixture marker: {marker}")
        remove_git_fixture(root)
    write(marker, MARKER)
    write(root / ".gitignore", ".ai/\n__pycache__/\n.pytest_cache/\n")
    write(root / "pyproject.toml", '[project]\nname = "repo-benchmark"\nversion = "0.0.0"\n')
    write(root / SOURCE, "def calculate_total():\n    return 1\n")
    write(root / TEST, "def test_pricing():\n    assert True\n")
    write(root / "tests/test_unrelated.py", "def test_unrelated():\n    assert True\n")
    workspaces, modules = SIZES[size]
    for workspace in range(workspaces):
        path = root / "workspaces" / f"service_{workspace:02d}"
        write(path / "pyproject.toml", f'[project]\nname = "service-{workspace}"\nversion = "0"\n')
        for module in range(modules):
            write(path / f"module_{module:02d}.py", f"def operation_{module}():\n    return 0\n")
    git(root, "init", "-b", "main", "--template=")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Benchmark",
        "-c",
        "user.email=benchmark@example.invalid",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "-m",
        "Fixture",
    )


def measure(root: Path, mode: str) -> None:
    index_mode = "rebuild" if mode == "baseline" else "update"
    semantic_flags = ("--rebuild",) if mode == "baseline" else ()
    reports: dict[str, Any] = {
        "mode": mode,
        "primed": (root / ".ai" / "cache" / "semantic-index.json").is_file(),
        "version": cli(root, "--version").strip(),
        "scan": json.loads(cli(root, "scan")),
        "initial_index": json.loads(cli(root, "index", index_mode)),
        "repeat_index": json.loads(cli(root, "index", index_mode)),
        "initial_semantic": json.loads(cli(root, "semantic", "index", "--backend", "structural")),
    }
    write(root / SOURCE, "def calculate_adjusted_total():\n    return 123\n")
    reports.update(
        git=json.loads(cli(root, "git", "inspect")),
        changed_index=json.loads(cli(root, "index", index_mode)),
        changed_semantic=json.loads(
            cli(root, "semantic", "index", "--backend", "structural", *semantic_flags)
        ),
        symbol=json.loads(cli(root, "explain", "--symbol", f"{SOURCE}#calculate_adjusted_total")),
        context=json.loads(
            cli(
                root,
                "context",
                "build",
                "--profile",
                "implement",
                "--max-files",
                "8",
                "--task",
                "Review calculate_adjusted_total in packages/service/pricing.py",
            )
        ),
        selection=json.loads(cli(root, "check", "--mode", "changed", "--explain")),
    )
    messages = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "project_status",
                "_meta": {"progressToken": "fixture"},
            },
        },
    ]
    requests = "".join(json.dumps({"jsonrpc": "2.0", **message}) + "\n" for message in messages)
    reports["mcp"] = [
        json.loads(line)
        for line in cli(
            root,
            "mcp",
            "serve",
            request=requests,
        ).splitlines()
    ]
    write(root / ".ai" / "benchmark-evidence.json", json.dumps(reports))
    print("Collected repository workflow evidence")
    selected = _selected_tests(reports)
    metrics = {
        "commands": 12,
        "selected_items": len(selected),
        "relevant_items": 1,
        "true_positive_items": int(TEST in selected),
    }
    print(f"AI_DEV_BENCHMARK_METRICS={json.dumps(metrics)}", file=sys.stderr)


def _selected_tests(reports: dict[str, Any]) -> set[str]:
    return {
        path.replace("\\", "/")
        for path in reports["selection"]["summary"]["changed_analysis"]["selected_tests"]
    }


def validate(root: Path, size: str) -> None:
    reports = read_json(root / ".ai" / "benchmark-evidence.json")
    expected_hash = hashlib.sha256(b"def calculate_adjusted_total():\n    return 123\n").hexdigest()
    index = read_json(root / ".ai" / "cache" / "repository-index.json")
    semantic = read_json(root / ".ai" / "cache" / "semantic-index.json")
    hashes = {row["path"]: row["sha256"] for row in index["entries"]}
    symbols = {row["name"] for row in semantic["symbols"] if row["path"] == SOURCE}
    workspaces, modules = SIZES[size]
    expected_modules = {
        f"workspaces/service_{workspace:02d}/module_{module:02d}.py"
        for workspace in range(workspaces)
        for module in range(modules)
    }
    assert reports["version"].startswith("ai-dev ")
    assert "python" in reports["scan"]["summary"]["languages"]
    assert expected_modules <= hashes.keys()
    assert hashes[SOURCE] == expected_hash
    assert symbols == {"calculate_adjusted_total"}
    symbol = reports["symbol"]["summary"]
    assert (symbol["path"], symbol["symbol"], symbol["start_line"]) == (
        SOURCE,
        "calculate_adjusted_total",
        1,
    )
    assert reports["git"]["summary"]["changed_files"] == [SOURCE]
    assert SOURCE in {row["path"] for row in reports["context"]["summary"]["selected_files"]}
    assert _selected_tests(reports) == {TEST}
    if reports["mode"] == "ai-dev":
        assert (reports["initial_index"]["summary"]["hashed"] == 0) == reports["primed"]
        assert reports["repeat_index"]["summary"]["hashed"] == 0
        assert reports["changed_index"]["summary"]["hashed"] == 1
    assert reports["mcp"][0]["result"]["protocolVersion"] == "2025-06-18"
    assert reports["mcp"][1]["result"]["isError"] is False
    print(f"Verified {size} fixture and expected edited symbol")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("size", choices=SIZES)
    parser.add_argument("action", choices=("reset", "warmup", "baseline", "ai-dev", "validate"))
    args = parser.parse_args()
    root = SCRATCH / args.size
    if args.action == "reset":
        reset(root, args.size)
    elif args.action == "warmup":
        cli(root, "index", "update")
        cli(root, "semantic", "index", "--backend", "structural")
    elif args.action == "validate":
        validate(root, args.size)
    else:
        measure(root, args.action)


if __name__ == "__main__":
    main()
