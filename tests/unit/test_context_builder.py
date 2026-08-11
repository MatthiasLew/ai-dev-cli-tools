from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.context import ContextOptions, build_context


def test_context_explain_selects_files_without_writing_pack(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, explain=True, include=("src/*.py",), task="explain task"),
    )

    assert report.status == "success"
    assert report.summary["explain_only"] is True
    assert any(item["path"] == "src/app.py" for item in report.summary["selected_files"])
    assert report.summary["selected_files"][0]["reason_code"]
    assert not (tmp_path / ".ai" / "context" / "context-latest.md").exists()


def test_context_build_writes_markdown_json_and_masks_secret(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    secret = "sk-" + "a" * 30
    (tmp_path / "src" / "client.py").write_text(
        f"API_KEY = '{secret}'\nprint(API_KEY)\n", encoding="utf-8"
    )

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("src/*.py",), max_chars=20_000, task="mask secrets"),
    )

    md_path = tmp_path / ".ai" / "context" / "context-latest.md"
    json_path = tmp_path / ".ai" / "context" / "context-latest.json"
    assert report.status in {"success", "partial"}
    assert md_path.exists()
    assert json_path.exists()
    assert secret not in md_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(data)
    assert secret not in serialized
    assert data["command"] == "context build"
    assert data["summary"]["secret_findings"][0]["kind"] == "openai_key"


def test_context_build_infers_python_dependency_and_related_test(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "src" / "handler.py").write_text(
        "from service import VALUE\nprint(VALUE)\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_handler.py").write_text(
        "def test_handler():\n    assert True\n", encoding="utf-8"
    )

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("src/handler.py",), max_files=10, task="deps"),
    )

    selected = {item["path"]: item for item in report.summary["selected_files"]}
    assert "src/handler.py" in selected
    assert "src/service.py" in selected
    assert "tests/test_handler.py" in selected


def test_context_rejects_env_and_binary_files(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("EXAMPLE=value\n", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"not really png")

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("*",), max_files=10, task="reject"),
    )

    rejected = {item["path"]: item["reason"] for item in report.summary["rejected_files"]}
    assert rejected[".env"] == "environment or secret-bearing file"
    assert rejected["logo.png"] == "binary or sensitive file type"
    rejected_codes = {
        item["path"]: item["reason_code"] for item in report.summary["rejected_files"]
    }
    assert rejected_codes == {
        ".env": "SENSITIVE_OR_ENV_FILE",
        "logo.png": "BINARY_OR_SENSITIVE_TYPE",
    }


def test_context_budget_truncates_large_file(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("A" * 1000, encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("README.md",), max_file_chars=20, max_chars=500),
    )

    selected = report.summary["selected_files"][0]
    assert selected["truncated"] is True
    assert "[TRUNCATED]" in selected["content"]


def test_context_build_includes_git_diff_and_latest_error(tmp_path: Path) -> None:
    from ai_dev_tools.utils.subprocess import run_command

    run_command(["git", "init"], tmp_path)
    run_command(["git", "config", "user.email", "agent@example.com"], tmp_path)
    run_command(["git", "config", "user.name", "Agent"], tmp_path)
    (tmp_path / "README.md").write_text("old\n", encoding="utf-8")
    run_command(["git", "add", "README.md"], tmp_path)
    run_command(["git", "commit", "-m", "initial"], tmp_path)
    (tmp_path / "README.md").write_text("new\n", encoding="utf-8")
    reports = tmp_path / ".ai" / "reports"
    reports.mkdir(parents=True)
    (reports / "check-fast-latest.json").write_text(
        '{"status":"failed","summary":{"first_failure":"boom"}}', encoding="utf-8"
    )

    report = build_context(tmp_path, ContextOptions(task="diff task", max_chars=30_000))

    assert report.summary["changed_files"] == ["README.md"]
    assert report.summary["latest_errors"][0]["first_failure"] == "boom"
    assert report.summary["diffs"][0]["chars"] > 0
    assert report.summary["recent_commits"]


def test_context_build_custom_output_markdown_only(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    out = tmp_path / "custom context"

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("README.md",), output=out, format="markdown"),
    )

    assert (out / "context-latest.md").exists()
    assert not (out / "context-latest.json").exists()
    assert [artifact.kind for artifact in report.artifacts] == ["markdown"]


def test_context_build_covers_static_dependency_hints(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("import {x} from './util'\n", encoding="utf-8")
    (tmp_path / "src" / "util.ts").write_text("export const x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "main.rs").write_text("mod helper;\n", encoding="utf-8")
    (tmp_path / "src" / "helper.rs").write_text("pub fn helper() {}\n", encoding="utf-8")
    (tmp_path / "src" / "App.java").write_text("package demo;\nclass App {}\n", encoding="utf-8")
    (tmp_path / "src" / "Helper.java").write_text(
        "package demo;\nclass Helper {}\n", encoding="utf-8"
    )
    (tmp_path / "src" / "index.php").write_text("<?php echo 'x';\n", encoding="utf-8")
    (tmp_path / "src" / "Helper.php").write_text("<?php class Helper {}\n", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            include=("src/app.ts", "src/main.rs", "src/App.java", "src/index.php"),
            max_files=20,
        ),
    )

    selected = {item["path"] for item in report.summary["selected_files"]}
    assert {"src/util.ts", "src/helper.rs", "src/Helper.java", "src/Helper.php"} <= selected


def test_context_build_changed_only_with_git(tmp_path: Path) -> None:
    from ai_dev_tools.utils.subprocess import run_command

    run_command(["git", "init"], tmp_path)
    run_command(["git", "config", "user.email", "agent@example.com"], tmp_path)
    run_command(["git", "config", "user.name", "Agent"], tmp_path)
    (tmp_path / "README.md").write_text("old\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("stable\n", encoding="utf-8")
    run_command(["git", "add", "README.md", "notes.md"], tmp_path)
    run_command(["git", "commit", "-m", "initial"], tmp_path)
    (tmp_path / "README.md").write_text("new\n", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(changed_only=True, include=("*.md",), max_files=10, max_chars=30_000),
    )

    selected = [item["path"] for item in report.summary["selected_files"]]
    assert selected == ["README.md"]


def test_context_explain_reports_rejected_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-context-file.txt"
    outside.write_text("outside", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("../outside-context-file.txt",), explain=True),
    )

    assert report.summary["rejected_files"][0]["reason"] == "outside project root"


def test_incremental_context_reuses_unchanged_files_and_invalidates_changes(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    options = ContextOptions(
        no_git=True,
        include=("src/*.py",),
        incremental=True,
        format="json",
        max_chars=20_000,
    )

    first = build_context(tmp_path, options)
    assert any(item["path"] == "src/app.py" for item in first.summary["selected_files"])
    assert first.summary["incremental"]["reused"] == 0

    second = build_context(tmp_path, options)
    assert second.summary["selected_files"] == []
    assert second.summary["incremental"]["reused"] >= 1

    source.write_text("VALUE = 200\n", encoding="utf-8")
    third = build_context(tmp_path, options)
    assert any(item["path"] == "src/app.py" for item in third.summary["selected_files"])
    data = json.loads(
        (tmp_path / ".ai" / "context" / "context-latest.json").read_text(encoding="utf-8")
    )
    artifact_paths = {item["path"] for item in data["artifacts"]}
    assert str(tmp_path / ".ai" / "context" / "context-latest.json") in artifact_paths
    assert str(tmp_path / ".ai" / "cache" / "context-manifest.json") in artifact_paths


def test_review_context_compacts_raw_diff_to_changed_symbols(tmp_path: Path) -> None:
    from ai_dev_tools.utils.subprocess import run_command

    run_command(["git", "init", "-b", "main"], tmp_path)
    run_command(["git", "config", "user.email", "agent@example.com"], tmp_path)
    run_command(["git", "config", "user.name", "Agent"], tmp_path)
    source = tmp_path / "service.py"
    source.write_text("def calculate(value):\n    return value + 1\n", encoding="utf-8")
    run_command(["git", "add", "service.py"], tmp_path)
    run_command(["git", "commit", "-m", "initial"], tmp_path)
    source.write_text(
        "def calculate(value, offset=2):\n    return value + offset\n", encoding="utf-8"
    )

    report = build_context(
        tmp_path,
        ContextOptions(profile="review", task="review calculation", max_chars=30_000),
    )

    assert report.summary["changed_symbols"][0]["name"] == "calculate"
    diff = report.summary["diffs"][0]
    assert diff["selection_strategy"] == "symbol-diff"
    assert diff["omitted_content"] is True
    assert "raw_diff_omitted" in diff["content"]
    assert "@@" not in diff["content"]


def test_context_reports_token_categories_and_enforces_source_budget(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('large source')\n" * 20, encoding="utf-8")
    usage = tmp_path / "usage.json"
    usage.write_text(
        '{"input_tokens":100,"output_tokens":12,"input_tokens_details":{"cached_tokens":80}}',
        encoding="utf-8",
    )

    report = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            include=("app.py",),
            max_chars=20_000,
            token_budgets=("source=3", "cached_input=100", "output=20"),
            provider_usage=Path("usage.json"),
        ),
    )

    accounting = report.summary["token_accounting"]
    assert report.status == "partial"
    assert accounting["categories"]["source"]["tokens"] <= 3
    assert accounting["categories"]["source"]["truncated"] is True
    assert accounting["provider_usage"]["cached_input_tokens"] == 80
    assert accounting["provider_usage"]["output_tokens"] == 12
    assert report.summary["selected_files"][0]["token_budget_truncated"] is True
