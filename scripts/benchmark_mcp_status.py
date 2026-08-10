from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "from ai_dev_tools.cli import main; raise SystemExit(main())"


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"baseline", "mcp"}:
        print("usage: benchmark_mcp_status.py baseline|mcp", file=sys.stderr)
        return 2
    if sys.argv[1] == "baseline":
        payloads = [
            _run_cli(["--json", "scan"]),
            _run_cli(["--json", "git", "status"]),
            _run_cli(["--json", "diagnostics"]),
        ]
        if any(item.get("status") not in {"success", "partial"} for item in payloads):
            return 1
        print(json.dumps(payloads, separators=(",", ":"), sort_keys=True))
        return 0

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"},
    }
    status_call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "project_status", "arguments": {}},
    }
    request = "\n".join(
        json.dumps(item, separators=(",", ":")) for item in (initialize, status_call)
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ENTRY,
            "--project",
            str(ROOT),
            "mcp",
            "serve",
        ],
        cwd=ROOT,
        input=request + "\n",
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=False,
        timeout=60,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode
    responses: list[dict[str, Any]] = [
        json.loads(line) for line in result.stdout.splitlines() if line.strip()
    ]
    if len(responses) != 2:
        print("MCP server returned an unexpected response count.", file=sys.stderr)
        return 1
    tool_result = responses[1].get("result", {})
    structured = tool_result.get("structuredContent", {})
    if structured.get("status") not in {"success", "partial"}:
        print("MCP project_status did not return a usable result.", file=sys.stderr)
        return 1
    print(json.dumps(tool_result, separators=(",", ":"), sort_keys=True))
    return 0


def _run_cli(arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", ENTRY, "--project", str(ROOT), *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or f"CLI failed with exit code {result.returncode}")
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
