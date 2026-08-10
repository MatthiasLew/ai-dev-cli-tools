from pathlib import Path
from typing import cast

import pytest

from ai_dev_tools.parsers.logs import (
    ParsedToolResult,
    clean_output,
    parse_tool_output,
    parser_names,
    register_parser,
    unregister_parser,
)
from ai_dev_tools.utils.subprocess import CommandResult

FIXTURES = Path("tests/fixtures/logs")


def test_parse_pytest_failure() -> None:
    parsed = parse_tool_output(
        "python -m pytest",
        "FAILED tests/test_auth.py::test_login - expected 200\n1 failed, 2 passed",
        exit_code=1,
    )
    assert parsed["parser"] == "pytest"
    assert parsed["parser_confidence"] == "high"
    assert parsed["failed"] == 1
    assert parsed["passed"] == 2
    first_failure = cast(dict[str, object], parsed["first_failure"])
    assert first_failure["test"] == "tests/test_auth.py::test_login"


@pytest.mark.parametrize(
    ("command", "fixture", "parser", "status"),
    [
        ("ruff check .", "ruff-fail.log", "ruff", "failed"),
        ("mypy src", "mypy-fail.log", "mypy", "failed"),
        ("coverage report", "coverage-ok.log", "coverage", "success"),
        ("npm test -- --runInBand", "jest-fail.log", "jest", "failed"),
        ("vitest run", "vitest-ok.log", "vitest", "success"),
        ("eslint .", "eslint-fail.log", "eslint", "failed"),
        ("tsc --noEmit", "tsc-fail.log", "tsc", "failed"),
        ("mvn test", "maven-fail.log", "maven-surefire", "failed"),
        ("gradle test", "gradle-ok.log", "gradle", "success"),
        ("cargo test", "cargo-fail.log", "cargo-test", "failed"),
        ("phpunit", "phpunit-fail.log", "phpunit", "failed"),
    ],
)
def test_tool_specific_parsers(command: str, fixture: str, parser: str, status: str) -> None:
    output = (FIXTURES / fixture).read_text(encoding="utf-8")
    parsed = parse_tool_output(command, output, exit_code=0 if status == "success" else 1)
    assert parsed["parser"] == parser
    assert parsed["status"] == status
    assert parsed["parser_confidence"] in {"high", "medium"}


def test_parse_known_tool_names_and_generic_fallback() -> None:
    assert parse_tool_output("custom", "\x1b[31mwarning\x1b[0m\nwarning")["parser"] == "generic"
    generic = parse_tool_output("custom", "\x1b[31mwarning\x1b[0m\nwarning")
    assert generic["parser_confidence"] == "low"
    assert generic["warnings"] == 2


def test_clean_output_removes_ansi_crlf_and_blank_lines() -> None:
    assert clean_output("\x1b[32mok\x1b[0m\r\n\r\n") == "ok"


class CustomParser:
    tool_name = "acme"

    def can_parse(self, command: CommandResult) -> bool:
        return command.command[:1] == ["acme"]

    def parse(self, command: CommandResult) -> ParsedToolResult:
        return ParsedToolResult(
            tool=self.tool_name,
            parser=self.tool_name,
            parser_confidence="high",
            status="success" if command.exit_code == 0 else "failed",
        )


def test_parser_registry_supports_extension_and_guards_duplicate_names() -> None:
    parser = CustomParser()
    register_parser(parser)
    try:
        assert parser_names()[0] == "acme"
        assert parse_tool_output("acme check", "all good")["parser"] == "acme"
        with pytest.raises(ValueError, match="already registered"):
            register_parser(parser)
    finally:
        unregister_parser("acme")
    with pytest.raises(KeyError):
        unregister_parser("acme")
