from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO, cast

from ai_dev_tools import __version__
from ai_dev_tools.security.secrets import mask_text

MCP_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "ai-dev-cli-tools"
SERVER_INSTRUCTIONS = (
    "Use project_status first. Prefer preview-only context and check calls until the user asks "
    "to execute validation. Expand evidence by stable ID instead of requesting broad output. "
    "All tools are local to the configured project root; no repository data is transmitted."
)

JsonObject = dict[str, Any]
ToolHandler = Callable[[JsonObject], JsonObject]


class ToolInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    input_schema: JsonObject
    output_schema: JsonObject
    annotations: JsonObject
    handler: ToolHandler

    def descriptor(self) -> JsonObject:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": self.annotations,
        }


class LocalMcpServer:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self._tools = {tool.name: tool for tool in self._build_tools()}

    def handle(self, message: object) -> JsonObject | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _rpc_error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        is_notification = "id" not in message
        method = message.get("method")
        if not isinstance(method, str):
            return None if is_notification else _rpc_error(request_id, -32600, "Invalid Request")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return None if is_notification else _rpc_error(request_id, -32602, "Invalid params")

        try:
            result = self._dispatch(method, params)
        except ToolInputError as exc:
            if is_notification:
                return None
            return _rpc_error(request_id, -32602, mask_text(str(exc)))
        except Exception as exc:
            if is_notification:
                return None
            return _rpc_error(request_id, -32603, f"Internal error: {mask_text(str(exc))}")

        if is_notification:
            return None
        if result is None:
            return _rpc_error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: JsonObject) -> JsonObject | None:
        if method == "initialize":
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": SERVER_INSTRUCTIONS,
            }
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {
                "tools": [
                    tool.descriptor()
                    for tool in sorted(self._tools.values(), key=lambda item: item.name)
                ]
            }
        if method == "tools/call":
            return self._call_tool(params)
        return None

    def _call_tool(self, params: JsonObject) -> JsonObject:
        _validate_keys(params, {"name", "arguments"})
        name = params.get("name")
        if not isinstance(name, str) or name not in self._tools:
            raise ToolInputError("Unknown MCP tool.")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ToolInputError("Tool arguments must be an object.")
        tool = self._tools[name]
        try:
            payload = tool.handler(arguments)
        except ToolInputError:
            raise
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"{name} failed: {mask_text(str(exc))}"}],
                "isError": True,
            }
        status = str(payload.get("status", "success"))
        return {
            "content": [{"type": "text", "text": f"{name}: {status}."}],
            "structuredContent": payload,
            "isError": status
            in {"failed", "blocked", "invalid_configuration", "environment_error"},
        }

    def _build_tools(self) -> list[ToolDefinition]:
        common_output = _common_output_schema()
        return [
            ToolDefinition(
                name="project_status",
                title="Get project status",
                description=(
                    "Inspect project technology, Git changes, cache/index health, and local "
                    "diagnostics before planning work."
                ),
                input_schema=_object_schema({}),
                output_schema=common_output,
                annotations=_annotations(read_only=True),
                handler=self._project_status,
            ),
            ToolDefinition(
                name="feedback",
                title="Get compact development feedback",
                description=(
                    "Build one bounded agent report containing changes, validation status, "
                    "failures, and task-relevant context. Checks are preview-only by default."
                ),
                input_schema=_object_schema(
                    {
                        "task": {"type": "string", "maxLength": 2000, "default": ""},
                        "execute_checks": {"type": "boolean", "default": False},
                        "jobs": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                    }
                ),
                output_schema=common_output,
                annotations=_annotations(read_only=False),
                handler=self._feedback,
            ),
            ToolDefinition(
                name="build_context",
                title="Build bounded project context",
                description=(
                    "Select task-relevant files, symbols, diffs, tests, and evidence within "
                    "explicit character budgets. Preview-only by default."
                ),
                input_schema=_object_schema(
                    {
                        "task": {"type": "string", "maxLength": 2000, "default": ""},
                        "profile": {
                            "type": "string",
                            "enum": ["default", "minimal", "debug", "review", "full"],
                            "default": "minimal",
                        },
                        "max_chars": {
                            "type": "integer",
                            "minimum": 1000,
                            "maximum": 100000,
                            "default": 20000,
                        },
                        "max_files": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20,
                        },
                        "max_file_chars": {
                            "type": "integer",
                            "minimum": 200,
                            "maximum": 20000,
                            "default": 4000,
                        },
                        "changed_only": {"type": "boolean", "default": False},
                        "staged_only": {"type": "boolean", "default": False},
                        "incremental": {"type": "boolean", "default": True},
                        "tokenizer": {
                            "type": "string",
                            "enum": ["estimate", "cl100k_base", "o200k_base"],
                            "default": "estimate",
                        },
                        "token_budgets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 8,
                            "default": [],
                        },
                        "refine": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 10,
                            "default": [],
                        },
                        "refinement_rounds": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 3,
                            "default": 1,
                        },
                        "refinement_max_files": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "default": 5,
                        },
                        "retrieval": {
                            "type": "string",
                            "enum": ["auto", "always", "never"],
                            "default": "auto",
                        },
                        "write_artifacts": {"type": "boolean", "default": False},
                    }
                ),
                output_schema=common_output,
                annotations=_annotations(read_only=False),
                handler=self._context,
            ),
            ToolDefinition(
                name="run_checks",
                title="Plan or run project checks",
                description=(
                    "Return the deterministic validation plan or execute bounded project checks. "
                    "Execution is disabled by default."
                ),
                input_schema=_object_schema(
                    {
                        "mode": {
                            "type": "string",
                            "enum": ["fast", "changed", "full"],
                            "default": "changed",
                        },
                        "execute": {"type": "boolean", "default": False},
                        "jobs": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                        "retry_flaky": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 3,
                            "default": 0,
                        },
                    }
                ),
                output_schema=common_output,
                annotations=_annotations(read_only=False),
                handler=self._checks,
            ),
            ToolDefinition(
                name="coordinate_agents",
                title="Coordinate local coding agents",
                description=(
                    "Register, claim, renew, release, complete, or inspect local tasks with "
                    "expiring leases and path-conflict detection."
                ),
                input_schema=_object_schema(
                    {
                        "action": {
                            "type": "string",
                            "enum": ["status", "add", "claim", "heartbeat", "release", "complete"],
                        },
                        "task_id": {"type": "string", "maxLength": 100, "default": ""},
                        "agent_id": {"type": "string", "maxLength": 100, "default": ""},
                        "title": {"type": "string", "maxLength": 500, "default": ""},
                        "paths": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                        "dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 100,
                        },
                        "lease_seconds": {
                            "type": "integer",
                            "minimum": 30,
                            "maximum": 86400,
                            "default": 900,
                        },
                    },
                    required=["action"],
                ),
                output_schema=common_output,
                annotations=_annotations(read_only=False),
                handler=self._coordinate_agents,
            ),
            ToolDefinition(
                name="explain_evidence",
                title="Expand local evidence",
                description=(
                    "Expand one stable evidence ID from existing local reports instead of "
                    "rebuilding or returning broad context."
                ),
                input_schema=_object_schema(
                    {
                        "reference": {"type": "string", "minLength": 3, "maxLength": 200},
                        "tail": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 1000,
                            "default": 100,
                        },
                    },
                    required=["reference"],
                ),
                output_schema=common_output,
                annotations=_annotations(read_only=True),
                handler=self._explain,
            ),
        ]

    def _project_status(self, arguments: JsonObject) -> JsonObject:
        _validate_keys(arguments, set())
        _require_project(self.project_root)
        from ai_dev_tools.detectors.project import scan_project
        from ai_dev_tools.git.inspect import inspect_git
        from ai_dev_tools.runners.diagnostics import run_diagnostics

        reports = [
            scan_project(self.project_root, write_reports=False),
            inspect_git(self.project_root, detailed=False, write_reports=False),
            run_diagnostics(self.project_root),
        ]
        finished = [_finish_report(report) for report in reports]
        statuses = [str(item["status"]) for item in finished]
        status = (
            "failed" if "failed" in statuses else "partial" if "partial" in statuses else "success"
        )
        return {
            "command": "project status",
            "status": status,
            "summary": {
                "scan": finished[0]["summary"],
                "git": finished[1]["summary"],
                "diagnostics": finished[2]["summary"],
            },
            "issues": [issue for item in finished for issue in item["issues"]],
            "artifacts": [],
        }

    def _feedback(self, arguments: JsonObject) -> JsonObject:
        _validate_keys(arguments, {"task", "execute_checks", "jobs"})
        task = _string(arguments, "task", "", 2000)
        execute = _boolean(arguments, "execute_checks", False)
        jobs = _integer(arguments, "jobs", 4, 1, 8)
        _require_project(self.project_root)
        from ai_dev_tools.runners.feedback import FeedbackOptions, run_feedback

        return _finish_report(
            run_feedback(
                self.project_root,
                FeedbackOptions(task=task, explain=not execute, jobs=jobs),
            )
        )

    def _context(self, arguments: JsonObject) -> JsonObject:
        allowed = {
            "task",
            "profile",
            "max_chars",
            "max_files",
            "max_file_chars",
            "changed_only",
            "staged_only",
            "incremental",
            "retrieval",
            "tokenizer",
            "token_budgets",
            "refine",
            "refinement_rounds",
            "refinement_max_files",
            "write_artifacts",
        }
        _validate_keys(arguments, allowed)
        task = _string(arguments, "task", "", 2000)
        profile = _choice(
            arguments,
            "profile",
            "minimal",
            {"default", "minimal", "debug", "review", "full"},
        )
        write_artifacts = _boolean(arguments, "write_artifacts", False)
        _require_project(self.project_root)
        from ai_dev_tools.context import ContextOptions, build_context

        return _finish_report(
            build_context(
                self.project_root,
                ContextOptions(
                    task=task,
                    profile=profile,
                    max_chars=_integer(arguments, "max_chars", 20000, 1000, 100000),
                    max_files=_integer(arguments, "max_files", 20, 1, 100),
                    max_file_chars=_integer(arguments, "max_file_chars", 4000, 200, 20000),
                    changed_only=_boolean(arguments, "changed_only", False),
                    staged_only=_boolean(arguments, "staged_only", False),
                    incremental=_boolean(arguments, "incremental", True),
                    retrieval=cast(
                        Literal["auto", "always", "never"],
                        _choice(arguments, "retrieval", "auto", {"auto", "always", "never"}),
                    ),
                    tokenizer=_choice(
                        arguments,
                        "tokenizer",
                        "estimate",
                        {"estimate", "cl100k_base", "o200k_base"},
                    ),
                    token_budgets=tuple(_string_array(arguments, "token_budgets", 8)),
                    refine=tuple(_string_array(arguments, "refine", 10)),
                    refinement_rounds=_integer(arguments, "refinement_rounds", 1, 0, 3),
                    refinement_max_files=_integer(arguments, "refinement_max_files", 5, 0, 20),
                    format="json",
                    explain=not write_artifacts,
                ),
            )
        )

    def _checks(self, arguments: JsonObject) -> JsonObject:
        _validate_keys(arguments, {"mode", "execute", "jobs", "retry_flaky"})
        mode = _choice(arguments, "mode", "changed", {"fast", "changed", "full"})
        execute = _boolean(arguments, "execute", False)
        jobs = _integer(arguments, "jobs", 4, 1, 8)
        retry_flaky = _integer(arguments, "retry_flaky", 0, 0, 3)
        _require_project(self.project_root)
        from ai_dev_tools.runners.check import run_check

        return _finish_report(
            run_check(
                self.project_root,
                mode=mode,
                explain=not execute,
                jobs=jobs,
                use_cache=True,
                policy="feedback-first" if execute else "complete",
                resume=execute,
                retry_flaky=retry_flaky,
            )
        )

    def _coordinate_agents(self, arguments: JsonObject) -> JsonObject:
        allowed = {
            "action",
            "task_id",
            "agent_id",
            "title",
            "paths",
            "dependencies",
            "lease_seconds",
        }
        _validate_keys(arguments, allowed)
        action = _choice(
            arguments,
            "action",
            "status",
            {"status", "add", "claim", "heartbeat", "release", "complete"},
        )
        _require_project(self.project_root)
        from ai_dev_tools.runners.coordination import coordinate_agents

        return _finish_report(
            coordinate_agents(
                self.project_root,
                action,
                task_id=_optional_string(arguments, "task_id", 100),
                agent_id=_optional_string(arguments, "agent_id", 100),
                title=_optional_string(arguments, "title", 500),
                paths=_string_array(arguments, "paths", 100),
                dependencies=_string_array(arguments, "dependencies", 100),
                lease_seconds=_integer(arguments, "lease_seconds", 900, 30, 86400),
            )
        )

    def _explain(self, arguments: JsonObject) -> JsonObject:
        _validate_keys(arguments, {"reference", "tail"})
        reference = _string(arguments, "reference", None, 200)
        tail = _integer(arguments, "tail", 100, 0, 1000)
        _require_project(self.project_root)
        from ai_dev_tools.reporters.progressive import run_explain

        return _finish_report(run_explain(self.project_root, reference, tail))


def serve_mcp(
    project_root: Path,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    reader = input_stream or sys.stdin
    writer = output_stream or sys.stdout
    server = LocalMcpServer(project_root)
    for raw_line in reader:
        if not raw_line.strip():
            continue
        response: JsonObject | None
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError:
            response = _rpc_error(None, -32700, "Parse error")
        else:
            response = server.handle(message)
        if response is not None:
            writer.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
            writer.flush()
    return 0


def _finish_report(report: Any) -> JsonObject:
    if report.finished_at is None:
        report.finish()
    payload = report.to_dict()
    return {
        "command": payload["command"],
        "status": payload["status"],
        "summary": payload["summary"],
        "issues": payload["issues"],
        "artifacts": payload["artifacts"],
        "duration_seconds": payload["duration_seconds"],
        "evidence": payload.get("metadata", {}).get("progressive", {}),
    }


def _rpc_error(request_id: object, code: int, message: str) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _object_schema(
    properties: Mapping[str, object], required: list[str] | None = None
) -> JsonObject:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": required or [],
        "additionalProperties": False,
    }


def _common_output_schema() -> JsonObject:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "status": {"type": "string"},
            "summary": {"type": "object"},
            "issues": {"type": "array"},
            "artifacts": {"type": "array"},
            "duration_seconds": {"type": "number"},
            "evidence": {"type": "object"},
        },
        "required": ["command", "status", "summary", "issues", "artifacts"],
        "additionalProperties": True,
    }


def _annotations(read_only: bool) -> JsonObject:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": False,
        "openWorldHint": False,
        "idempotentHint": read_only,
    }


def _validate_keys(arguments: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolInputError(f"Unknown tool arguments: {', '.join(unknown)}")


def _string(
    arguments: Mapping[str, object],
    name: str,
    default: str | None,
    maximum: int,
) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        if default == "" and value == "":
            return ""
        raise ToolInputError(f"{name} must be a non-empty string up to {maximum} characters.")
    return value


def _optional_string(arguments: Mapping[str, object], name: str, maximum: int) -> str:
    value = arguments.get(name, "")
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ToolInputError(f"{name} must be a string up to {maximum} characters.")
    return value


def _string_array(arguments: Mapping[str, object], name: str, maximum: int) -> list[str]:
    value = arguments.get(name, [])
    if not isinstance(value, list) or len(value) > maximum:
        raise ToolInputError(f"{name} must be an array with at most {maximum} strings.")
    if any(not isinstance(item, str) or not item or len(item) > 500 for item in value):
        raise ToolInputError(f"{name} contains an invalid string.")
    return value


def _boolean(arguments: Mapping[str, object], name: str, default: bool) -> bool:
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise ToolInputError(f"{name} must be a boolean.")
    return value


def _integer(
    arguments: Mapping[str, object],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ToolInputError(f"{name} must be an integer from {minimum} to {maximum}.")
    return value


def _choice(
    arguments: Mapping[str, object],
    name: str,
    default: str,
    choices: set[str],
) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str) or value not in choices:
        raise ToolInputError(f"{name} must be one of: {', '.join(sorted(choices))}.")
    return value


def _require_project(project_root: Path) -> None:
    if not project_root.exists() or not project_root.is_dir():
        raise RuntimeError("Configured project root does not exist or is not a directory.")
