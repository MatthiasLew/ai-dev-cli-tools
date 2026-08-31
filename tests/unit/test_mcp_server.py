from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from ai_dev_tools.mcp_server import (
    MCP_PROTOCOL_VERSION,
    SERVER_INSTRUCTIONS,
    LocalMcpServer,
    serve_mcp,
)


def _request(
    method: str,
    params: dict[str, object] | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    payload: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return payload


def _call(
    server: LocalMcpServer,
    name: str,
    arguments: dict[str, object] | None = None,
) -> dict[str, Any]:
    response = server.handle(_request("tools/call", {"name": name, "arguments": arguments or {}}))
    assert response is not None
    result = response.get("result")
    assert isinstance(result, dict)
    return result


def test_initialize_advertises_tools_and_bounded_instructions(tmp_path: Path) -> None:
    server = LocalMcpServer(tmp_path)

    initialized = server.handle(_request("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION}))
    listed = server.handle(_request("tools/list", request_id=2))

    assert initialized is not None
    result = initialized["result"]
    assert isinstance(result, dict)
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["serverInfo"] == {
        "name": "ai-dev-cli-tools",
        "version": result["serverInfo"]["version"],
    }
    assert result["instructions"] == SERVER_INSTRUCTIONS
    assert len(SERVER_INSTRUCTIONS) <= 512

    assert listed is not None
    tools = listed["result"]["tools"]
    names = [tool["name"] for tool in tools]
    assert names == [
        "build_context",
        "coordinate_agents",
        "explain_evidence",
        "feedback",
        "plan_work",
        "project_status",
        "run_checks",
    ]
    status = next(tool for tool in tools if tool["name"] == "project_status")
    checks = next(tool for tool in tools if tool["name"] == "run_checks")
    assert status["annotations"]["readOnlyHint"] is True
    assert checks["annotations"]["readOnlyHint"] is False
    assert checks["inputSchema"]["additionalProperties"] is False


def test_stdio_transport_returns_json_lines_and_ignores_notifications(tmp_path: Path) -> None:
    messages = [
        _request("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION}),
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        _request("ping", request_id=2),
    ]
    reader = io.StringIO("\n".join(json.dumps(item) for item in messages) + "\n")
    writer = io.StringIO()

    assert serve_mcp(tmp_path, reader, writer) == 0

    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert [item["id"] for item in responses] == [1, 2]
    assert responses[1]["result"] == {}


def test_stdio_transport_reports_parse_and_method_errors(tmp_path: Path) -> None:
    reader = io.StringIO("{broken\n" + json.dumps(_request("unknown/method", request_id=7)) + "\n")
    writer = io.StringIO()

    serve_mcp(tmp_path, reader, writer)

    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[0]["id"] is None
    assert responses[1]["error"]["code"] == -32601
    assert responses[1]["id"] == 7


def test_project_status_combines_existing_read_only_reports(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='mcp-fixture'\nversion='0.0.0'\n",
        encoding="utf-8",
    )
    server = LocalMcpServer(tmp_path)

    result = _call(server, "project_status")

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["command"] == "project status"
    assert structured["summary"]["scan"]["languages"] == ["python"]
    assert not (tmp_path / ".ai" / "reports").exists()
    assert "diagnostics" in structured["summary"]


def test_check_tool_is_preview_only_by_default(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='mcp-fixture'\nversion='0.0.0'\n",
        encoding="utf-8",
    )
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[commands]\ntest='command-that-must-not-run'\n",
        encoding="utf-8",
    )
    server = LocalMcpServer(tmp_path)

    result = _call(server, "run_checks", {"mode": "full"})

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["summary"]["explain_only"] is True
    selected = structured["summary"]["selected_checks"]
    assert any("command-that-must-not-run" in item["command"] for item in selected)


def test_plan_work_returns_preview_only_agent_plan(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='mcp-plan'\nversion='0.0.0'\n",
        encoding="utf-8",
    )
    server = LocalMcpServer(tmp_path)

    result = _call(server, "plan_work", {"task": "add a bounded feature"})

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["summary"]["constraints"]["preview_only"] is True
    assert structured["summary"]["constraints"]["commands_executed"] is False
    assert (tmp_path / ".ai" / "reports" / "agent-plan.json").exists()


def test_context_tool_is_preview_only_and_bounded_by_default(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='mcp-fixture'\nversion='0.0.0'\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("project docs\n" * 1000, encoding="utf-8")
    server = LocalMcpServer(tmp_path)

    result = _call(
        server,
        "build_context",
        {"task": "inspect project docs", "max_chars": 2000, "max_file_chars": 500},
    )

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["summary"]["budget"]["max_chars"] == 2000
    assert structured["summary"]["adaptive_context"]["enabled"] is True
    assert structured["summary"]["adaptive_context"]["explicit_overrides"] == [
        "max_chars",
        "max_file_chars",
    ]
    assert structured["artifacts"] == []
    assert not (tmp_path / ".ai" / "context" / "context-latest.json").exists()


def test_tool_arguments_are_strict_and_bounded(tmp_path: Path) -> None:
    server = LocalMcpServer(tmp_path)

    unknown = server.handle(
        _request(
            "tools/call",
            {"name": "run_checks", "arguments": {"shell": "rm -rf"}},
        )
    )
    excessive = server.handle(
        _request(
            "tools/call",
            {"name": "run_checks", "arguments": {"jobs": 100}},
            request_id=2,
        )
    )

    assert unknown is not None
    assert unknown["error"]["code"] == -32602
    assert excessive is not None
    assert excessive["error"]["code"] == -32602


def test_missing_project_is_returned_as_tool_error(tmp_path: Path) -> None:
    server = LocalMcpServer(tmp_path / "missing")

    result = _call(server, "project_status")

    assert result["isError"] is True
    assert "does not exist" in result["content"][0]["text"]
    assert "structuredContent" not in result


def test_feedback_defaults_to_preview_only(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='mcp-feedback'\nversion='0.0.0'\n",
        encoding="utf-8",
    )
    server = LocalMcpServer(tmp_path)

    result = _call(server, "feedback")

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["summary"]["validation"]["results"] == []
    assert structured["summary"]["performance"]["total_seconds"] >= 0
    assert structured["summary"]["delta"]["enabled"] is True

    state = structured["summary"]["delta"]["state_fingerprint"]
    repeated = _call(server, "feedback", {"acknowledged_state": state})
    assert repeated["structuredContent"]["summary"]["delta"]["reused"] is True


def test_explain_evidence_returns_bounded_not_found_result(tmp_path: Path) -> None:
    server = LocalMcpServer(tmp_path)

    result = _call(server, "explain_evidence", {"reference": "issue:missing", "tail": 10})

    assert result["isError"] is True
    assert result["structuredContent"]["summary"]["reason_code"] == "EVIDENCE_NOT_FOUND"


def test_protocol_rejects_invalid_shapes_and_unknown_tools(tmp_path: Path) -> None:
    server = LocalMcpServer(tmp_path)

    invalid_request = server.handle([])
    missing_method = server.handle({"jsonrpc": "2.0", "id": 1})
    invalid_params = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": []}
    )
    unknown_tool = server.handle(
        _request("tools/call", {"name": "unknown", "arguments": {}}, request_id=3)
    )
    invalid_arguments = server.handle(
        _request("tools/call", {"name": "project_status", "arguments": []}, request_id=4)
    )

    assert invalid_request is not None
    assert invalid_request["error"]["code"] == -32600
    assert missing_method is not None
    assert missing_method["error"]["code"] == -32600
    assert invalid_params is not None
    assert invalid_params["error"]["code"] == -32602
    assert unknown_tool is not None
    assert unknown_tool["error"]["code"] == -32602
    assert invalid_arguments is not None
    assert invalid_arguments["error"]["code"] == -32602


def test_invalid_bounded_values_return_parameter_errors(tmp_path: Path) -> None:
    server = LocalMcpServer(tmp_path)

    invalid_boolean = server.handle(
        _request(
            "tools/call",
            {"name": "feedback", "arguments": {"execute_checks": "yes"}},
        )
    )
    invalid_choice = server.handle(
        _request(
            "tools/call",
            {"name": "build_context", "arguments": {"profile": "unbounded"}},
            request_id=2,
        )
    )
    invalid_reference = server.handle(
        _request(
            "tools/call",
            {"name": "explain_evidence", "arguments": {"reference": ""}},
            request_id=3,
        )
    )

    assert invalid_boolean is not None
    assert invalid_boolean["error"]["code"] == -32602
    assert invalid_choice is not None
    assert invalid_choice["error"]["code"] == -32602
    assert invalid_reference is not None
    assert invalid_reference["error"]["code"] == -32602


def test_coordinate_agents_tool_claims_and_reports_conflicts(tmp_path: Path) -> None:
    server = LocalMcpServer(tmp_path)
    added = _call(
        server,
        "coordinate_agents",
        {"action": "add", "task_id": "one", "title": "One", "paths": ["src"]},
    )
    claimed = _call(
        server,
        "coordinate_agents",
        {"action": "claim", "task_id": "one", "agent_id": "agent-a"},
    )

    assert added["isError"] is False
    assert claimed["structuredContent"]["summary"]["reason_code"] == "TASK_CLAIMED"
    assert claimed["structuredContent"]["summary"]["active_claims"][0]["id"] == "one"
