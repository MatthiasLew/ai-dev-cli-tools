from __future__ import annotations

from pathlib import Path

from ai_dev_tools.git.symbol_diff import analyze_symbol_diff, parse_unified_hunks
from ai_dev_tools.utils.subprocess import run_command


def _repository(root: Path, files: dict[str, str]) -> None:
    run_command(["git", "init", "-b", "main"], root, 30)
    run_command(["git", "config", "user.email", "agent@example.com"], root, 30)
    run_command(["git", "config", "user.name", "Agent"], root, 30)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_command(["git", "add", "."], root, 30)
    run_command(["git", "commit", "-m", "initial"], root, 30)


def test_parse_unified_hunks_handles_additions_and_deletions() -> None:
    diff = "@@ -2,0 +3,2 @@\n@@ -10,3 +11,0 @@\n"
    changes = parse_unified_hunks(diff)
    assert [(item.old_count, item.new_count) for item in changes] == [(0, 2), (3, 0)]


def test_symbol_diff_reports_modified_python_symbol_signature_and_tests(tmp_path: Path) -> None:
    _repository(
        tmp_path,
        {
            "src/service.py": "def helper():\n    return 1\n\ndef public(value):\n    return helper() + value\n",  # noqa: E501
            "tests/test_service.py": "from src.service import public\n\ndef test_public():\n    assert public(1) == 2\n",  # noqa: E501
        },
    )
    (tmp_path / "src/service.py").write_text(
        "def helper():\n    return 1\n\ndef public(value, scale=1):\n    return (helper() + value) * scale\n",  # noqa: E501
        encoding="utf-8",
    )

    result = analyze_symbol_diff(tmp_path, ["src/service.py"])

    symbol = next(item for item in result["symbols"] if item["name"] == "public")
    assert symbol["kind"] == "function"
    assert symbol["change_type"] == "modified"
    assert symbol["signature_changed"] is True
    assert symbol["risk"] == "high"
    assert symbol["related_tests"] == ["tests/test_service.py"]
    assert result["summary"]["symbols_changed"] == 1


def test_symbol_diff_reports_deleted_and_untracked_symbols(tmp_path: Path) -> None:
    _repository(tmp_path, {"src/old.py": "def removed():\n    return 1\n"})
    (tmp_path / "src/old.py").unlink()
    new_path = tmp_path / "src/new.ts"
    new_path.write_text("export function created() {\n  return 2;\n}\n", encoding="utf-8")

    result = analyze_symbol_diff(
        tmp_path,
        ["src/new.ts", "src/old.py"],
        untracked_files=["src/new.ts"],
        deleted_files=["src/old.py"],
    )

    by_name = {item["name"]: item for item in result["symbols"]}
    assert by_name["removed"]["change_type"] == "deleted"
    assert by_name["removed"]["start_line"] is None
    assert by_name["created"]["change_type"] == "added"
    assert by_name["created"]["confidence"] == "structural"


def test_symbol_diff_reports_conservative_parse_fallback(tmp_path: Path) -> None:
    _repository(tmp_path, {"broken.py": "def valid():\n    return 1\n"})
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    result = analyze_symbol_diff(tmp_path, ["broken.py"])

    assert result["symbols"] == []
    assert result["fallbacks"] == [{"path": "broken.py", "reason_code": "SYMBOL_PARSE_FALLBACK"}]


def test_symbol_diff_preserves_module_level_changes_next_to_symbol_changes(tmp_path: Path) -> None:
    _repository(tmp_path, {"app.py": "VALUE = 1\n\ndef run():\n    return VALUE\n"})
    (tmp_path / "app.py").write_text(
        "VALUE = 2\n\ndef run():\n    return VALUE + 1\n", encoding="utf-8"
    )

    result = analyze_symbol_diff(tmp_path, ["app.py"])

    by_name = {item["name"]: item for item in result["symbols"]}
    assert by_name["run"]["change_type"] == "modified"
    assert by_name["<module>"]["added_lines"] == 1
    assert by_name["<module>"]["deleted_lines"] == 1
