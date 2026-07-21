from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown

ERROR_MARKERS = ("error", "failed", "failure", "traceback", "assertionerror", "exception")

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PROGRESS_PATTERN = re.compile(r"\r[^\n]*")
WARNING_PATTERN = re.compile(r"\bwarning\b", re.IGNORECASE)
PYTEST_FAILURE_PATTERN = re.compile(r"FAILED\s+(?P<test>\S+)(?:\s+-\s+(?P<message>.*))?")


def clean_output(output: str) -> str:
    output = ANSI_PATTERN.sub("", output)
    output = PROGRESS_PATTERN.sub("", output)
    return "\n".join(line.rstrip() for line in output.splitlines() if line.strip())


def parse_tool_output(tool: str, output: str) -> dict[str, object]:
    cleaned = clean_output(output)
    generic = summarize_output(cleaned)
    parser, confidence = _parser_name(tool, cleaned)
    first_failure = _first_failure(tool, cleaned, generic)
    return {
        "tool": tool,
        "parser": parser,
        "parser_confidence": confidence,
        "warnings": len(WARNING_PATTERN.findall(cleaned)),
        "status": "failed" if generic.get("failed", 0) or generic.get("errors", 0) else "success",
        "first_failure": first_failure,
        **generic,
    }


def _parser_name(tool: str, output: str) -> tuple[str, str]:
    lowered = tool.lower()
    if "pytest" in lowered or "pytest" in output.lower():
        return ("pytest", "medium")
    if "ruff" in lowered:
        return ("ruff", "medium")
    if "mypy" in lowered:
        return ("mypy", "medium")
    if "npm" in lowered or "jest" in output.lower() or "vitest" in output.lower():
        return ("npm", "medium")
    if "maven" in lowered or "mvn" in lowered:
        return ("maven", "medium")
    if "gradle" in lowered:
        return ("gradle", "medium")
    if "cargo" in lowered:
        return ("cargo", "medium")
    if "php" in lowered or "phpunit" in output.lower():
        return ("php", "medium")
    return ("generic", "low")


def _first_failure(tool: str, output: str, generic: dict[str, object]) -> dict[str, object] | None:
    match = PYTEST_FAILURE_PATTERN.search(output)
    if match:
        return {
            "tool": tool,
            "test": match.group("test"),
            "message": match.group("message") or generic.get("first_failure_reason"),
            "location": generic.get("first_project_frame"),
        }
    reason = generic.get("first_failure_reason")
    if reason:
        return {
            "tool": tool,
            "test": None,
            "message": reason,
            "location": generic.get("first_project_frame"),
        }
    return None


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
    output = clean_output(output)
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
        report.finish()
        write_markdown(report, settings.reports_directory / "logs-summary-latest.md")
        write_json(report, settings.reports_directory / "logs-summary-latest.json")
        return report
    latest = logs[0]
    report.summary = {
        "log": str(latest),
        **summarize_output(latest.read_text(encoding="utf-8", errors="replace")),
    }
    report.finish()
    write_markdown(report, settings.reports_directory / "logs-summary-latest.md")
    write_json(report, settings.reports_directory / "logs-summary-latest.json")
    return report
