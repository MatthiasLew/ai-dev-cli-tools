from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report

ERROR_MARKERS = ("error", "failed", "failure", "traceback", "assertionerror", "exception")
TEST_COUNT_PATTERN = re.compile(
    r"(?P<count>\d+)\s+(?P<kind>passed|failed|failures?|skipped|errors?|xfailed|xpassed)",
    re.IGNORECASE,
)
TEST_KINDS = {
    "passed": "passed",
    "failed": "failed",
    "failure": "failed",
    "failures": "failed",
    "skipped": "skipped",
    "error": "errors",
    "errors": "errors",
    "xfailed": "xfailed",
    "xpassed": "xpassed",
}


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
    test_counts = parse_test_counts(output)
    return {
        "line_count": len(lines),
        "tests_total": sum(test_counts.values()),
        **test_counts,
        "first_failure_reason": errors[0] if errors else None,
        "first_project_frame": first_project_frame,
        "grouped_repeated_messages": [
            f"{line} ? {count}" for line, count in grouped.items() if count > 1
        ][:20],
        "errors": errors[:20],
    }


def parse_test_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "xfailed": 0, "xpassed": 0}
    for match in TEST_COUNT_PATTERN.finditer(output):
        key = TEST_KINDS[match.group("kind").lower()]
        counts[key] += int(match.group("count"))
    return counts


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
