import json
from pathlib import Path

from ai_dev_tools.cache.prompt_layout import write_cache_layout_manifest
from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.runners.diagnostics import run_diagnostics


def test_diagnostics_reports_local_storage_config_and_efficiency(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("x" * 400, encoding="utf-8")
    (tmp_path / ".ai-dev-tools.toml").write_text(
        '[reports]\ndirectory="artifacts/reports"\nlogs_directory="artifacts/logs"\n',
        encoding="utf-8",
    )
    reports = tmp_path / "artifacts" / "reports"
    logs = tmp_path / "artifacts" / "logs"
    reports.mkdir(parents=True)
    logs.mkdir(parents=True)
    (reports / "one.json").write_text("{}", encoding="utf-8")
    (logs / "one.log").write_text("log", encoding="utf-8")
    update_repository_index(tmp_path)
    write_cache_layout_manifest(tmp_path)
    context_dir = tmp_path / ".ai" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "context-latest.json").write_text(
        json.dumps(
            {
                "summary": {
                    "incremental": {"reused_files": ["source.py"]},
                    "budget": {"used_chars": 800},
                }
            }
        ),
        encoding="utf-8",
    )

    report = run_diagnostics(tmp_path)

    assert report.status == "success"
    assert report.summary["reports"]["files"] == 1
    assert report.summary["logs"]["bytes"] == 3
    assert report.summary["configuration"]["source"].endswith(".ai-dev-tools.toml")
    assert report.summary["repository_index"]["available"] is True
    assert report.summary["cache_layout"]["available"] is True
    assert report.summary["cache_layout"]["provider_breakpoints"] == 3
    metrics = report.summary["efficiency_metrics"]
    assert metrics["latest_context_token_estimate"] == 200
    assert metrics["estimated_tokens_avoided"] == 100
    assert report.summary["privacy"].startswith("local-only")


def test_diagnostics_handles_empty_project(tmp_path: Path) -> None:
    report = run_diagnostics(tmp_path)
    assert report.summary["cache"] == {"entries": 0, "bytes": 0}
    assert report.summary["reports"]["files"] == 0
    assert report.summary["cache_layout"]["available"] is False
    assert report.summary["configuration"]["source"] == "built-in defaults"
