from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.utils.subprocess import CommandResult

ERROR_MARKERS = ("error", "failed", "failure", "traceback", "assertionerror", "exception")
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PROGRESS_PATTERN = re.compile(r"\r[^\n]*")
WARNING_PATTERN = re.compile(r"\bwarning\b", re.IGNORECASE)
PROJECT_FRAME_PATTERN = re.compile(
    r"(?P<file>[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|java|rs|php)):(?P<line>\d+)(?::(?P<column>\d+))?"
)
TEST_COUNT_PATTERN = re.compile(
    r"(?P<count>\d+)\s+(?P<kind>passed|failed|failures?|skipped|errors?|xfailed|xpassed|tests?)",
    re.IGNORECASE,
)
PYTEST_FAILURE_PATTERN = re.compile(r"FAILED\s+(?P<test>\S+)(?:\s+-\s+(?P<message>.*))?")
JEST_VITEST_PATTERN = re.compile(
    r"Tests:\s+(?:(?P<failed>\d+) failed,\s*)?(?:(?P<passed>\d+) passed,\s*)?(?P<total>\d+) total",
    re.IGNORECASE,
)
CARGO_PATTERN = re.compile(
    r"test result:\s+\w+\.\s+(?P<passed>\d+) passed;\s+(?P<failed>\d+) failed", re.IGNORECASE
)
PHPUNIT_PATTERN = re.compile(
    r"Tests:\s*(?P<total>\d+).*?Assertions:\s*(?P<assertions>\d+)(?:.*?Failures:\s*(?P<failed>\d+))?(?:.*?Errors:\s*(?P<errors>\d+))?",
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


@dataclass(frozen=True, slots=True)
class ProjectFrame:
    file: str
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class FailureDetails:
    message: str
    test: str | None = None
    location: str | None = None


@dataclass(slots=True)
class ParsedToolResult:
    tool: str
    parser: str
    parser_confidence: str
    status: str
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    errors: int | None = None
    warnings: int | None = None
    tests_total: int | None = None
    duration_seconds: float | None = None
    first_failure: FailureDetails | None = None
    project_frames: list[ProjectFrame] = field(default_factory=list)
    line_count: int = 0
    first_failure_reason: str | None = None
    first_project_frame: str | None = None
    grouped_repeated_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ToolOutputParser(Protocol):
    tool_name: str

    def can_parse(self, command: CommandResult) -> bool: ...

    def parse(self, command: CommandResult) -> ParsedToolResult: ...


@dataclass(frozen=True, slots=True)
class RegexToolParser:
    tool_name: str
    markers: tuple[str, ...]
    confidence: str = "medium"

    def can_parse(self, command: CommandResult) -> bool:
        text = f"{' '.join(command.command)}\n{command.combined_output}".lower()
        return any(marker in text for marker in self.markers)

    def parse(self, command: CommandResult) -> ParsedToolResult:
        return _parsed_from_output(self.tool_name, self.tool_name, self.confidence, command)


class GenericParser:
    tool_name = "generic"

    def can_parse(self, command: CommandResult) -> bool:
        return True

    def parse(self, command: CommandResult) -> ParsedToolResult:
        return _parsed_from_output("generic", "generic", "low", command)


Parser = RegexToolParser | GenericParser


PARSERS: tuple[Parser, ...] = (
    RegexToolParser("pytest", ("pytest", "failed tests/", "= short test summary info ="), "high"),
    RegexToolParser("ruff", ("ruff", "would reformat"), "high"),
    RegexToolParser("mypy", ("mypy", "success: no issues found", "checked 1 source file"), "high"),
    RegexToolParser("coverage", ("coverage", "fail_under", "cover"), "medium"),
    RegexToolParser("jest", ("jest", "test suites:", "fail src/"), "high"),
    RegexToolParser("vitest", ("vitest", "test files", "duration"), "high"),
    RegexToolParser("eslint", ("eslint", "problems", "no-unused-vars"), "high"),
    RegexToolParser("tsc", ("tsc", "typescript", "ts(", "error ts"), "high"),
    RegexToolParser("npm", ("npm", "npm err!", "npm run"), "medium"),
    RegexToolParser("maven-surefire", ("surefire", "tests run:"), "high"),
    RegexToolParser("maven", ("mvn", "[error] build failure", "[info] build success"), "medium"),
    RegexToolParser("gradle", ("gradle", "build failed", "build successful"), "medium"),
    RegexToolParser("cargo-test", ("cargo test", "test result:"), "high"),
    RegexToolParser("cargo-clippy", ("cargo clippy", "clippy"), "high"),
    RegexToolParser("cargo-fmt", ("cargo fmt", "rustfmt"), "high"),
    RegexToolParser("phpunit", ("phpunit", "there was 1 failure", "phpunit\\"), "high"),
    RegexToolParser("phpstan", ("phpstan", "phpstan.neon"), "high"),
    RegexToolParser("php-cs-fixer", ("php-cs-fixer", "cs fixer"), "high"),
    GenericParser(),
)


def clean_output(output: str) -> str:
    output = ANSI_PATTERN.sub("", output)
    output = PROGRESS_PATTERN.sub("", output)
    return "\n".join(
        line.rstrip() for line in output.replace("\r\n", "\n").splitlines() if line.strip()
    )


def parse_tool_output(tool: str, output: str, exit_code: int = 0) -> dict[str, object]:
    command = CommandResult(tool.split(), exit_code, output, "", 0.0)
    return parse_command_result(command).to_dict()


def parse_command_result(command: CommandResult) -> ParsedToolResult:
    for parser in PARSERS:
        if parser.can_parse(command):
            return parser.parse(command)
    return GenericParser().parse(command)


def summarize_output(output: str) -> dict[str, object]:
    return _summary_parts(clean_output(output))


def parse_test_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "xfailed": 0, "xpassed": 0}
    for match in TEST_COUNT_PATTERN.finditer(output):
        kind = match.group("kind").lower()
        if kind in TEST_KINDS:
            counts[TEST_KINDS[kind]] += int(match.group("count"))
    cargo = CARGO_PATTERN.search(output)
    if cargo:
        counts["passed"] = max(counts["passed"], int(cargo.group("passed")))
        counts["failed"] = max(counts["failed"], int(cargo.group("failed")))
    js = JEST_VITEST_PATTERN.search(output)
    if js:
        counts["passed"] = max(counts["passed"], int(js.group("passed") or 0))
        counts["failed"] = max(counts["failed"], int(js.group("failed") or 0))
    phpunit = PHPUNIT_PATTERN.search(output)
    if phpunit:
        counts["failed"] = max(counts["failed"], int(phpunit.group("failed") or 0))
        counts["errors"] = max(counts["errors"], int(phpunit.group("errors") or 0))
    return counts


def summarize_latest_log(project_root: Path) -> Report:
    settings = load_settings(project_root)
    logs = sorted(
        settings.logs_directory.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    report = Report(command="logs summarize", project_root=settings.project_root)
    if not logs:
        report.status = "partial"
        report.summary = {
            "message": "No logs found",
            "logs_directory": str(settings.logs_directory),
        }
        report.finish()
        write_markdown(report, settings.reports_directory / "logs-summary-latest.md")
        write_json(report, settings.reports_directory / "logs-summary-latest.json")
        return report
    return summarize_log_file(settings.project_root, logs[0])


def summarize_log_file(project_root: Path, log_path: Path, tool: str = "auto") -> Report:
    settings = load_settings(project_root)
    report = Report(command="logs summarize", project_root=settings.project_root)
    path = log_path if log_path.is_absolute() else settings.project_root / log_path
    if not path.exists():
        report.status = "failed"
        report.exit_code = 1
        report.summary = {"message": "Log file does not exist", "log": str(path)}
        report.finish()
        return report
    size = path.stat().st_size
    if size > 50_000_000:
        report.status = "failed"
        report.exit_code = 1
        report.summary = {
            "message": "Log file exceeds 50 MB limit",
            "log": str(path),
            "bytes": size,
        }
        report.finish()
        return report
    text = path.read_text(encoding="utf-8", errors="replace")
    command_text = tool if tool != "auto" else path.stem.replace("-", " ")
    parsed = parse_tool_output(command_text, text, 0)
    report.summary = {"log": str(path), "detected_tool": parsed["tool"], **parsed}
    report.finish()
    write_markdown(report, settings.reports_directory / "logs-summary-latest.md")
    write_json(report, settings.reports_directory / "logs-summary-latest.json")
    return report


def _parsed_from_output(
    tool: str, parser: str, confidence: str, command: CommandResult
) -> ParsedToolResult:
    cleaned = clean_output(command.combined_output)
    summary = _summary_parts(cleaned)
    failed = _as_int(summary.get("failed")) + _as_int(summary.get("errors"))
    status = "failed" if command.exit_code != 0 or failed else "success"
    first_failure = _first_failure(tool, cleaned, summary)
    return ParsedToolResult(
        tool=tool,
        parser=parser,
        parser_confidence=confidence,
        status=status,
        passed=_as_int(summary.get("passed")),
        failed=_as_int(summary.get("failed")),
        skipped=_as_int(summary.get("skipped")),
        errors=_as_int(summary.get("errors")),
        warnings=_as_int(summary.get("warnings")),
        tests_total=_as_int(summary.get("tests_total")),
        duration_seconds=command.duration_seconds,
        first_failure=first_failure,
        project_frames=_project_frames(cleaned),
        line_count=_as_int(summary.get("line_count")),
        first_failure_reason=_string_or_none(summary.get("first_failure_reason")),
        first_project_frame=_string_or_none(summary.get("first_project_frame")),
        grouped_repeated_messages=_string_list(summary.get("grouped_repeated_messages")),
    )


def _summary_parts(output: str) -> dict[str, object]:
    lines = [line.strip() for line in clean_output(output).splitlines() if line.strip()]
    grouped = Counter(lines)
    errors = [line for line in lines if any(marker in line.lower() for marker in ERROR_MARKERS)]
    frames = _project_frames("\n".join(lines))
    test_counts = parse_test_counts(output)
    tests_total = sum(test_counts.values())
    js = JEST_VITEST_PATTERN.search(output)
    if js and js.group("total"):
        tests_total = max(tests_total, int(js.group("total")))
    phpunit = PHPUNIT_PATTERN.search(output)
    if phpunit and phpunit.group("total"):
        tests_total = max(tests_total, int(phpunit.group("total")))
    return {
        "line_count": len(lines),
        "tests_total": tests_total,
        **test_counts,
        "warnings": len(WARNING_PATTERN.findall(output)),
        "first_failure_reason": errors[0] if errors else None,
        "first_project_frame": _frame_to_location(frames[0]) if frames else None,
        "grouped_repeated_messages": [
            f"{line} x {count}" for line, count in grouped.items() if count > 1
        ][:20],
        "errors": errors[:20],
    }


def _first_failure(tool: str, output: str, summary: dict[str, object]) -> FailureDetails | None:
    match = PYTEST_FAILURE_PATTERN.search(output)
    if match:
        message = match.group("message") or _string_or_none(summary.get("first_failure_reason"))
        return FailureDetails(
            message or f"{tool} failure",
            test=match.group("test"),
            location=_string_or_none(summary.get("first_project_frame")),
        )
    reason = _string_or_none(summary.get("first_failure_reason"))
    if reason:
        return FailureDetails(
            reason,
            test=None,
            location=_string_or_none(summary.get("first_project_frame")),
        )
    return None


def _project_frames(output: str) -> list[ProjectFrame]:
    frames: list[ProjectFrame] = []
    seen: set[tuple[str, int | None, int | None]] = set()
    for match in PROJECT_FRAME_PATTERN.finditer(output):
        frame = ProjectFrame(
            match.group("file"),
            int(match.group("line")) if match.group("line") else None,
            int(match.group("column")) if match.group("column") else None,
        )
        key = (frame.file, frame.line, frame.column)
        if key not in seen:
            frames.append(frame)
            seen.add(key)
    return frames[:10]


def _frame_to_location(frame: ProjectFrame) -> str:
    location = frame.file
    if frame.line is not None:
        location += f":{frame.line}"
    if frame.column is not None:
        location += f":{frame.column}"
    return location


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
