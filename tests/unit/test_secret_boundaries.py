import shutil
from pathlib import Path

import pytest

import ai_dev_tools.detectors.environment as environment
import ai_dev_tools.runners.check as check
from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.security.secrets import mask_text
from ai_dev_tools.utils.subprocess import CommandResult


def test_mask_text_covers_supported_secret_families() -> None:
    values = [
        "ghp_" + "a" * 24,
        "sk-" + "b" * 24,
        "AKIA" + "C" * 16,
        "-----BEGIN PRIVATE KEY-----",
        "postgres://user:password@localhost/db",
        "password=very-secret-password",
        "token=very-secret-token-value",
    ]
    masked = mask_text("\n".join(values))
    assert all(value not in masked for value in values)
    assert masked.count("***MASKED_") >= len(values)


def test_context_artifacts_exclude_blocked_files_keys_and_tokens(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=env-secret-value", encoding="utf-8")
    (tmp_path / "private.pem").write_text(
        "-----BEGIN PRIVATE KEY-----\nprivate-material\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text('token = "very-secret-token-value"\n', encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("**/*",), max_chars=20_000),
    )

    artifact_text = "\n".join(
        Path(item.path).read_text(encoding="utf-8") for item in report.artifacts
    )
    assert "env-secret-value" not in artifact_text
    assert "private-material" not in artifact_text
    assert "very-secret-token-value" not in artifact_text
    assert "MASKED_" in artifact_text
    rejected = {item["path"] for item in report.summary["rejected_files"]}
    assert {".env", "private.pem"} <= rejected


def test_check_masks_command_output_before_cache_log_and_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = "sk-" + "q" * 24
    (tmp_path / ".ai-dev-tools.toml").write_text('[commands]\nlint="demo"\n', encoding="utf-8")
    monkeypatch.setattr(
        check,
        "run_command",
        lambda command, cwd: CommandResult(command, 1, f"error: {secret}", "", 0.01),
    )

    report = check.run_check(tmp_path, mode="full", use_cache=False)

    serialized = str(report.to_dict())
    log = Path(report.summary["results"][0]["full_log"]).read_text(encoding="utf-8")
    assert secret not in serialized
    assert secret not in log
    assert "MASKED_OPENAI_KEY" in log


def test_doctor_masks_tool_version_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = "ghp_" + "x" * 24
    monkeypatch.setattr(shutil, "which", lambda executable: executable)
    monkeypatch.setattr(
        environment,
        "run_command",
        lambda command, root, timeout_seconds=20: CommandResult(command, 0, secret, "", 0.01),
    )

    report = environment.run_doctor(tmp_path)

    assert secret not in str(report.to_dict())
    assert "MASKED_GITHUB_TOKEN" in str(report.to_dict())


def test_report_writers_apply_final_secret_mask(tmp_path: Path) -> None:
    secret = "sk-" + "r" * 24
    report = Report(command="test", project_root=tmp_path, summary={"user_text": secret})
    markdown = write_markdown(report, tmp_path / "report.md")
    structured = write_json(report, tmp_path / "report.json")

    for path in (markdown, structured):
        content = path.read_text(encoding="utf-8")
        assert secret not in content
        assert "MASKED_OPENAI_KEY" in content
