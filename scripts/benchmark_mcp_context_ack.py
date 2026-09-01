from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from ai_dev_tools.mcp_server import LocalMcpServer
from ai_dev_tools.runners.benchmark import METRICS_PREFIX


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"baseline", "ai-dev"}:
        print("usage: benchmark_mcp_context_ack.py baseline|ai-dev", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="ai-dev-context-ack-") as temporary:
        root = Path(temporary)
        (root / "pyproject.toml").write_text(
            "[project]\nname='context-ack-benchmark'\nversion='0.0.0'\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text("bounded project context\n" * 200, encoding="utf-8")
        server = LocalMcpServer(root)
        arguments: dict[str, object] = {
            "task": "inspect project documentation",
            "max_chars": 20_000,
            "max_file_chars": 4_000,
        }
        first = _call(server, arguments)
        first_summary = _summary(first)
        delta = first_summary.get("delta")
        if not isinstance(delta, dict) or not isinstance(delta.get("state_fingerprint"), str):
            print("Initial context response did not provide an acknowledgement.", file=sys.stderr)
            return 1

        second_arguments = dict(arguments)
        if sys.argv[1] == "baseline":
            second_arguments["delta"] = False
        else:
            second_arguments["acknowledged_state"] = delta["state_fingerprint"]
        second = _call(server, second_arguments)
        second_summary = _summary(second)
        second_delta = second_summary.get("delta")
        expected_reuse = sys.argv[1] == "ai-dev"
        if (
            second.get("status") != "success"
            or not isinstance(second_delta, dict)
            or second_delta.get("reused") is not expected_reuse
        ):
            print("Repeated context response did not satisfy delta invariants.", file=sys.stderr)
            return 1

        metrics = {
            "outcome_signature": "unchanged-context-confirmed",
            "iterations": 2,
            "files_read": 1,
            "selected_items": 1,
            "relevant_items": 1,
            "true_positive_items": 1,
            "false_negative_items": 0,
        }
        print(
            METRICS_PREFIX + json.dumps(metrics, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
        )
        print(json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


def _call(server: LocalMcpServer, arguments: dict[str, object]) -> dict[str, Any]:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "build_context", "arguments": arguments},
        }
    )
    if not isinstance(response, dict):
        raise RuntimeError("MCP server returned no response.")
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("MCP server returned an invalid result.")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise RuntimeError("MCP tool returned no structured content.")
    return structured


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("Context response returned no summary.")
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
