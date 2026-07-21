from typing import cast

from ai_dev_tools.parsers.logs import clean_output, parse_tool_output


def test_parse_pytest_failure() -> None:
    parsed = parse_tool_output(
        "python -m pytest",
        "FAILED tests/test_auth.py::test_login - expected 200\n1 failed, 2 passed",
    )
    assert parsed["parser"] == "pytest"
    assert parsed["failed"] == 1
    assert parsed["passed"] == 2
    first_failure = cast(dict[str, object], parsed["first_failure"])
    assert first_failure["test"] == "tests/test_auth.py::test_login"


def test_parse_known_tool_names_and_generic_fallback() -> None:
    assert parse_tool_output("mypy", "Success: no issues found")["parser"] == "mypy"
    assert (
        parse_tool_output("cargo test", "test result: ok. 3 passed; 0 failed")["parser"] == "cargo"
    )
    generic = parse_tool_output("custom", "\x1b[31mwarning\x1b[0m\nwarning")
    assert generic["parser"] == "generic"
    assert generic["parser_confidence"] == "low"
    assert generic["warnings"] == 2


def test_clean_output_removes_ansi_and_blank_lines() -> None:
    assert clean_output("\x1b[32mok\x1b[0m\n\n") == "ok"
