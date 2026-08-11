from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.cli import main
from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.runners.performance import (
    compare_performance,
    record_performance,
    run_performance_latest,
)


def _settings(root: Path) -> Settings:
    return Settings(
        project_root=root,
        reports_directory=root / ".ai" / "reports",
        logs_directory=root / ".ai" / "logs",
        performance_budgets={"scan": 0.1, "scan.detection": 0.05},
        performance_retention=2,
    )


def test_performance_records_budgets_latest_and_comparison(tmp_path: Path) -> None:
    first = Report(command="scan", project_root=tmp_path)
    first_path = record_performance(
        first,
        "scan",
        {"detection": 0.08, "invalid": float("nan")},
        0.2,
        _settings(tmp_path),
    )
    second = Report(command="scan", project_root=tmp_path)
    second_path = record_performance(
        second,
        "scan",
        {"detection": 0.04},
        0.09,
        _settings(tmp_path),
    )

    assert first.status == "warning"
    assert first.summary["performance"]["budget_violations"]
    assert "invalid" not in first.summary["performance"]["stages_seconds"]
    latest = run_performance_latest(tmp_path)
    compared = compare_performance(tmp_path, first_path, second_path)

    assert latest.status == "success"
    assert latest.summary["total_seconds"] == 0.09
    assert compared.status == "success"
    assert compared.summary["metrics"]["total_seconds"]["percent_change"] == -55.0
    assert compared.summary["decision"] == "within_budget"


def test_performance_config_and_cli_latest(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".ai-dev-tools.toml").write_text(
        """
[performance]
retention = 7

[performance.budgets]
scan = 5.0
"scan.detection" = 2.0
bad = false
""".strip(),
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)

    assert settings.performance_retention == 7
    assert settings.performance_budgets == {"scan": 5.0, "scan.detection": 2.0}
    assert any("performance.budgets" in warning for warning in settings.warnings)

    assert main(["--project", str(tmp_path), "--json", "scan"]) == 0
    scan_payload = json.loads(capsys.readouterr().out)
    assert scan_payload["summary"]["performance"]["operation"] == "scan"

    assert main(["--project", str(tmp_path), "--json", "performance", "latest"]) == 0
    latest_payload = json.loads(capsys.readouterr().out)
    assert latest_payload["summary"]["operation"] == "scan"


def test_performance_compare_rejects_different_operations(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    left = record_performance(Report("scan", tmp_path), "scan", {}, 0.1, settings)
    right = record_performance(
        Report("context build", tmp_path), "context-incremental", {}, 0.1, settings
    )

    compared = compare_performance(tmp_path, left, right)

    assert compared.status == "invalid_configuration"
    assert compared.summary["reason_code"] == "INCOMPARABLE_PERFORMANCE_RECORDS"
