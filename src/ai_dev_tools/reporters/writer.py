from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Artifact, Report


def write_json(report: Report, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _register_artifact(report, path, "json", "Structured report")
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_markdown(report: Report) -> str:
    lines = [
        f"# ai-dev {report.command}",
        "",
        f"- Status: `{report.status.upper()}`",
        f"- Duration: `{report.duration_seconds}s`",
        f"- Project: `{report.project_root}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(_render_value(report.summary))
    if report.issues:
        lines.extend(["", "## Issues", ""])
        for issue in report.issues:
            suffix = f" ({issue.location})" if issue.location else ""
            lines.append(f"- `{issue.severity}` {issue.message}{suffix}")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown(report: Report, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _register_artifact(report, path, "markdown", "Human report")
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


def _register_artifact(report: Report, path: Path, kind: str, description: str) -> None:
    artifact_path = str(path)
    if any(item.path == artifact_path and item.kind == kind for item in report.artifacts):
        return
    report.artifacts.append(Artifact(path=artifact_path, kind=kind, description=description))


def _render_value(value: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, dict | list):
                lines.append(f"{prefix}- {key}:")
                lines.extend(_render_value(item, indent + 1))
            else:
                lines.append(f"{prefix}- {key}: `{item}`")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict | list):
                lines.extend(_render_value(item, indent))
            else:
                lines.append(f"{prefix}- `{item}`")
        return lines
    return [f"{prefix}- `{value}`"]
