from __future__ import annotations

from pathlib import Path

import pytest

from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.source_symbols import extract_source_symbols, select_structural_symbols


@pytest.mark.parametrize(
    ("suffix", "source", "expected"),
    [
        (
            ".java",
            "public class Service {\n  public Service() {}\n  public int calculate(int value) {\n    return value + 1;\n  }\n}\n",  # noqa: E501
            {
                ("Service", "class"),
                ("Service.Service", "constructor"),
                ("Service.calculate", "method"),
            },
        ),
        (
            ".rs",
            "pub struct Service { value: i32 }\n\nimpl Service {\n    pub fn calculate(&self) -> i32 { self.value + 1 }\n}\n\npub fn create() -> Service { Service { value: 0 } }\n",  # noqa: E501
            {
                ("Service", "struct"),
                ("Service", "impl"),
                ("Service::calculate", "function"),
                ("create", "function"),
            },
        ),
        (
            ".php",
            "<?php\nclass Service {\n  public function __construct() {}\n  public function calculate(int $value): int {\n    return $value + 1;\n  }\n}\n\nfunction create(): Service { return new Service(); }\n",  # noqa: E501
            {
                ("Service", "class"),
                ("Service.__construct", "method"),
                ("Service.calculate", "method"),
                ("create", "function"),
            },
        ),
    ],
)
def test_additional_language_extractors_find_declarations(
    suffix: str, source: str, expected: set[tuple[str, str]]
) -> None:
    symbols = extract_source_symbols(source, suffix)
    assert symbols is not None
    assert {(item.name, item.kind) for item in symbols} == expected


@pytest.mark.parametrize(
    ("suffix", "source", "expected_names"),
    [
        (
            ".java",
            "class First {\n  public void run() {}\n}\nclass Second {\n  public void run() {}\n}\n",
            {"First.run", "Second.run"},
        ),
        (
            ".rs",
            "trait First {\n  fn run(&self);\n}\nimpl Second {\n  fn run(&self) {}\n}\n",
            {"First::run", "Second::run"},
        ),
        (
            ".php",
            "<?php\nclass First {\n  public function run() {}\n}\n"
            "class Second {\n  public function run() {}\n}\n",
            {"First.run", "Second.run"},
        ),
    ],
)
def test_qualified_members_distinguish_owners(
    suffix: str, source: str, expected_names: set[str]
) -> None:
    symbols = extract_source_symbols(source, suffix)
    assert symbols is not None
    assert expected_names <= {item.name for item in symbols}


def test_structural_selection_prefers_task_symbol_and_reports_references() -> None:
    source = (
        "public class Service {\n"
        "  private int helper(int value) { return value; }\n"
        "  public int calculateTotal(int value) { return helper(value) + 1; }\n"
        "}\n" + "// filler\n" * 100
    )

    selection = select_structural_symbols(source, source, "fix calculate total", 300, ".java")

    assert selection is not None
    symbol = next(item for item in selection.snippets if item.name == "Service.calculateTotal")
    assert symbol.reason_code == "TASK_SYMBOL_MATCH"
    assert symbol.referenced_local_symbols == ["Service.helper"]


@pytest.mark.parametrize(
    ("suffix", "strategy"),
    [(".java", "java-structure"), (".rs", "rust-structure"), (".php", "php-structure")],
)
def test_context_builder_uses_additional_language_adapter(
    tmp_path: Path, suffix: str, strategy: str
) -> None:
    source = tmp_path / f"service{suffix}"
    declaration, symbol_name = {
        ".java": (
            "public class Service {\n  public int calculate(int value) { return value; }\n}\n",
            "Service.calculate",
        ),
        ".rs": ("pub fn calculate(value: i32) -> i32 { value }\n", "calculate"),
        ".php": ("<?php\nfunction calculate(int $value): int { return $value; }\n", "calculate"),
    }[suffix]
    source.write_text(declaration + "// filler\n" * 100, encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            include=(source.name,),
            task="repair calculate",
            max_file_chars=250,
            max_chars=10_000,
        ),
    )

    selected = report.summary["selected_files"][0]
    assert selected["selection_strategy"] == strategy
    assert any(item["name"] == symbol_name for item in selected["snippets"])


def test_ambiguous_unbalanced_source_falls_back() -> None:
    source = "public class Broken {\n  public void run() {\n"
    assert extract_source_symbols(source, ".java") is None
    assert select_structural_symbols(source * 20, source * 20, "run", 100, ".java") is None
