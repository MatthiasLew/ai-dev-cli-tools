from __future__ import annotations

from collections import Counter
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report

ERROR_MARKERS = ("error", "failed", "failure", "traceback", "assertionerror", "exception")


def summarize_output(output: str) -> dict[str, object]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    grouped = Counter(lines)
    errors = [line for line in lines if any(marker in line.lower() for marker in ERROR_MARKERS)]
    first_project_frame = next(
        (
            line
            for line in lines
            if ".py:" in line or ".ts:" in line or ".js:" in line or ".php:" in line
        ),
        None,
    )
    return {
        "line_count": len(lines),
        "first_failure_reason": errors[0] if errors else None,
        "first_project_frame": first_project_frame,
        "grouped_repeated_messages": [
            f"{line} x {count}" for line, count in grouped.items() if count > 1
        ][:20],
        "errors": errors[:20],
    }


def summarize_latest_log(project_root: Path) -> Report:
    settings = load_settings(project_root)
    logs = sorted(
        settings.logs_directory.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    report = Report(command="logs summarize", project_root=settings.project_root)
    if not logs:
        report.status = "warning"
        report.summary = {
            "message": "No logs found",
            "logs_directory": str(settings.logs_directory),
        }
        return report
    latest = logs[0]
    report.summary = {
        "log": str(latest),
        **summarize_output(latest.read_text(encoding="utf-8", errors="replace")),
    }
    return report
