from pathlib import Path

from ai_dev_tools.models.report import Issue, Report


def test_report_schema_contains_required_fields(tmp_path: Path) -> None:
    report = Report(
        command="scan", project_root=tmp_path, issues=[Issue("warning", "note")]
    ).finish()
    data = report.to_dict()
    assert data["schema_version"] == "1.1"
    assert data["tool_version"] == "0.4.0"
    assert data["status"] == "success"
    assert data["command"] == "scan"
    assert data["summary"] == {}
    assert data["issues"][0]["message"] == "note"
    assert "duration_seconds" in data
