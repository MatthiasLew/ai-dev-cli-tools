from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from ai_dev_tools.mcp_server import LocalMcpServer
from ai_dev_tools.runners.benchmark import METRICS_PREFIX

README_PREFIX = "bounded project context\n"


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"reset", "baseline", "ai-dev", "validate"}:
        print("usage: benchmark_mcp_context_ack.py reset|baseline|ai-dev|validate", file=sys.stderr)
        return 2

    action = sys.argv[1]
    evidence = Path.cwd() / ".ai" / "tmp" / "context-ack-benchmark-evidence.json"
    if action == "reset":
        evidence.unlink(missing_ok=True)
        return 0
    if action == "validate":
        return validate(evidence)

    evidence.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-dev-context-ack-") as temp:
        root = Path(temp)
        (root / "pyproject.toml").write_text(
            "[project]\nname='context-ack-benchmark'\nversion='0.0.0'\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text(README_PREFIX * 200, encoding="utf-8")
        server = LocalMcpServer(root)
        arguments: dict[str, object] = {
            "task": "inspect project documentation",
            "profile": "docs",
            "max_chars": 20_000,
            "max_file_chars": 8_000,
            "incremental": False,
            "adaptive": False,
            "write_artifacts": True,
        }
        first = _call(server, arguments)
        first_summary = _summary(first)
        delta = first_summary.get("delta")
        if not isinstance(delta, dict) or not isinstance(delta.get("state_fingerprint"), str):
            print("Initial context response did not provide an acknowledgement.", file=sys.stderr)
            return 1

        second_arguments = dict(arguments)
        if action == "baseline":
            second_arguments["delta"] = False
        else:
            second_arguments["acknowledged_state"] = delta["state_fingerprint"]
        second = _call(server, second_arguments)
        second_summary = _summary(second)
        second_delta = second_summary.get("delta")
        expected_reuse = action == "ai-dev"
        if (
            second.get("status") != "success"
            or not isinstance(second_delta, dict)
            or second_delta.get("reused") is not expected_reuse
        ):
            print("Repeated context response did not satisfy delta invariants.", file=sys.stderr)
            return 1

        selected = set(_selected(first_summary if expected_reuse else second_summary))
        expected = {"README.md", "pyproject.toml"}
        evidence.write_text(
            json.dumps({"variant": action, "first": first, "second": second}), encoding="utf-8"
        )
        metrics = {
            "iterations": 2,
            "selected_items": len(selected),
            "relevant_items": len(expected),
            "true_positive_items": len(selected & expected),
            "false_negative_items": len(expected - selected),
        }
        print(
            METRICS_PREFIX + json.dumps(metrics, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
        )
        print(json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0


def _selected(summary: dict[str, Any]) -> dict[str, str]:
    return {row["path"]: row.get("content", "") for row in summary.get("selected_files", [])}


def validate(evidence: Path) -> int:
    if not evidence.is_file():
        print("Missing context acknowledgement evidence.", file=sys.stderr)
        return 1
    trial = json.loads(evidence.read_text(encoding="utf-8"))
    first = _summary(trial["first"])
    second = _summary(trial["second"])
    selected = _selected(first)
    assert trial["first"]["status"] == trial["second"]["status"] == "success"
    assert selected.get("README.md") == README_PREFIX * 200
    assert "name='context-ack-benchmark'" in selected.get("pyproject.toml", "")
    assert first["delta"]["state_fingerprint"] == second["delta"]["state_fingerprint"]
    if trial["variant"] == "ai-dev":
        assert second["delta"]["reused"] is True
        assert second["delta"]["acknowledged_fingerprint"] == first["delta"]["state_fingerprint"]
        assert second["context_receipt"]["selected_file_count"] == len(selected)
        assert not _selected(second)
    else:
        assert second["delta"]["reused"] is False
        assert _selected(second) == selected
    print("Verified acknowledged README context")
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
