from typing import cast

from ai_dev_tools.parsers.logs import summarize_output


def test_summarize_output_groups_repeated_lines() -> None:
    summary = summarize_output("Warning X\nWarning X\nAssertionError: nope\nsrc/app.py:10\n")
    assert summary["first_failure_reason"] == "AssertionError: nope"
    assert summary["first_project_frame"] == "src/app.py:10"
    messages = cast(list[str], summary["grouped_repeated_messages"])
    assert "Warning X x 2" in messages
