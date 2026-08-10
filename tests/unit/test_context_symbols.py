from pathlib import Path

from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.context.symbols import select_javascript_symbols, select_python_symbols


def test_python_symbol_selection_prefers_task_match_and_reports_references() -> None:
    source = (
        "import time\n\n"
        "def helper():\n    return 1\n\n"
        "def unrelated():\n    return 'x' * 1000\n\n"
        "def authenticate_timeout():\n    return helper()\n" + "# filler\n" * 200
    )

    selection = select_python_symbols(source, source, "fix authenticate timeout", 400)

    assert selection is not None
    assert "def authenticate_timeout" in selection.content
    assert "def unrelated" not in selection.content
    symbol = next(item for item in selection.snippets if item.name == "authenticate_timeout")
    assert symbol.kind == "function"
    assert symbol.start_line > 1
    assert symbol.end_line >= symbol.start_line
    assert symbol.reason == "symbol name matches task terms"
    assert symbol.reason_code == "TASK_SYMBOL_MATCH"
    assert symbol.referenced_local_symbols == ["helper"]
    assert selection.omitted_content is True


def test_python_symbol_selection_falls_back_for_invalid_or_small_source() -> None:
    assert select_python_symbols("def broken(:\n", "def broken(:\n", "broken", 5) is None
    source = "def small():\n    return 1\n"
    assert select_python_symbols(source, source, "small", 100) is None


def test_context_builder_emits_ast_symbol_metadata_and_masks_content(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    secret = "sk-" + "z" * 30
    source = (
        "import os\n\n"
        "def unrelated():\n    return 1\n\n"
        f"def authenticate_timeout():\n    token = '{secret}'\n    return token\n\n"
        + "# padding\n"
        * 300
    )
    (tmp_path / "src" / "auth.py").write_text(source, encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            include=("src/auth.py",),
            task="fix authenticate timeout",
            max_file_chars=450,
            max_chars=20_000,
            format="json",
        ),
    )

    selected = next(
        item for item in report.summary["selected_files"] if item["path"] == "src/auth.py"
    )
    assert selected["selection_strategy"] == "python-ast"
    assert selected["omitted_content"] is True
    assert selected["snippets"][1]["name"] == "authenticate_timeout"
    assert secret not in selected["content"]
    assert "MASKED_" in selected["content"]


def test_large_import_block_cannot_displace_matching_symbol() -> None:
    imports = "".join(f"import module_{index}\n" for index in range(100))
    source = imports + "\ndef target_handler():\n    return 42\n"

    selection = select_python_symbols(source, source, "repair target handler", 350)

    assert selection is not None
    assert "def target_handler" in selection.content
    assert any(item.name == "target_handler" for item in selection.snippets)


def test_javascript_symbol_selection_prefers_task_match_and_reports_references() -> None:
    source = (
        "import { clock } from './clock';\n\n"
        "const helper = () => 1;\n\n"
        "function unrelated() {\n  return 'x'.repeat(1000);\n}\n\n"
        + "// filler\n"
        * 200
        + "export const authenticateTimeout = async (request: Request) => {\n"
        "  return helper() + request.timeout;\n"
        "};\n"
    )

    selection = select_javascript_symbols(source, source, "fix authenticate timeout", 500)

    assert selection is not None
    assert "authenticateTimeout" in selection.content
    assert "function unrelated" not in selection.content
    symbol = next(item for item in selection.snippets if item.name == "authenticateTimeout")
    assert symbol.kind == "arrow-function"
    assert symbol.reason_code == "TASK_SYMBOL_MATCH"
    assert symbol.referenced_local_symbols == ["helper"]
    assert selection.omitted_content is True


def test_javascript_extractor_ignores_nested_symbols_and_braces_in_strings() -> None:
    source = (
        "const template = 'value { not structure }';\n"
        "export function outerHandler() {\n"
        "  function nestedTarget() { return '}'; }\n"
        "  return nestedTarget();\n"
        "}\n" + "// padding\n" * 100
    )

    selection = select_javascript_symbols(source, source, "nested target", 250)

    assert selection is not None
    assert [item.name for item in selection.snippets] == ["outerHandler"]
    assert selection.snippets[0].start_line == 2
    assert selection.snippets[0].end_line == 5


def test_javascript_symbol_selection_falls_back_for_unbalanced_or_small_source() -> None:
    assert (
        select_javascript_symbols(
            "export function broken() {\n", "export function broken() {\n", "broken", 5
        )
        is None
    )
    source = "export function small() { return 1; }\n"
    assert select_javascript_symbols(source, source, "small", 100) is None


def test_context_builder_emits_javascript_symbol_metadata_and_masks_content(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
    (tmp_path / "src").mkdir()
    secret = "sk-" + "y" * 30
    source = (
        "const helper = () => 1;\n"
        + "// irrelevant padding\n" * 300
        + "export const authenticateTimeout = (request: Request) => {\n"
        f"  const token = '{secret}';\n"
        "  return helper() + request.timeout + token.length;\n"
        "};\n"
    )
    (tmp_path / "src" / "auth.ts").write_text(source, encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            include=("src/auth.ts",),
            task="fix authenticate timeout",
            max_file_chars=450,
            max_chars=20_000,
            format="json",
        ),
    )

    selected = next(
        item for item in report.summary["selected_files"] if item["path"] == "src/auth.ts"
    )
    assert selected["selection_strategy"] == "javascript-structure"
    assert selected["omitted_content"] is True
    symbol = next(item for item in selected["snippets"] if item["name"] == "authenticateTimeout")
    assert symbol["referenced_local_symbols"] == ["helper"]
    assert secret not in selected["content"]
    assert "MASKED_" in selected["content"]


def test_javascript_extractor_recognizes_types_and_skips_bodyless_declarations() -> None:
    source = (
        "/* ignored { braces } */\n"
        "export function declaredOnly(value: string): void;\n"
        "export interface ApiClient { request(): void }\n"
        "export type RequestId = string;\n"
        "export enum Mode { Fast, Safe }\n"
        "export namespace Internal { export const value = 1; }\n"
        "export class SessionStore { load() { return new ApiClient(); } }\n" + "// padding\n" * 100
    )

    selection = select_javascript_symbols(source, source, "repair session store", 300)

    assert selection is not None
    assert "class SessionStore" in selection.content
    assert "declaredOnly" not in [item.name for item in selection.snippets]
    symbol = next(item for item in selection.snippets if item.name == "SessionStore")
    assert symbol.kind == "class"
    assert symbol.referenced_local_symbols == ["ApiClient"]


def test_javascript_extractor_returns_none_without_supported_top_level_symbols() -> None:
    source = "console.log('no declarations');\n" + "// padding\n" * 100
    assert select_javascript_symbols(source, source, "anything", 100) is None
