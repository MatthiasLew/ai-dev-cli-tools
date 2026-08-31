import json
from pathlib import Path

from ai_dev_tools.models.report import Issue, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown


def test_report_schema_contains_required_fields(tmp_path: Path) -> None:
    report = Report(
        command="scan", project_root=tmp_path, issues=[Issue("warning", "note")]
    ).finish()
    data = report.to_dict()
    assert data["schema_version"] == "1.1"
    assert data["tool_version"] == "1.0.0"
    assert data["status"] == "success"
    assert data["command"] == "scan"
    assert data["summary"] == {}
    assert data["issues"][0]["message"] == "note"
    assert "duration_seconds" in data


def test_written_json_contains_all_report_artifacts(tmp_path: Path) -> None:
    report = Report(command="scan", project_root=tmp_path).finish()
    markdown_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    write_markdown(report, markdown_path)
    write_json(report, json_path)
    write_json(report, json_path)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    artifacts = {(item["kind"], item["path"]) for item in data["artifacts"]}
    assert artifacts == {("markdown", str(markdown_path)), ("json", str(json_path))}
    assert len(report.artifacts) == 2


def test_report_json_schema_contract_matches_model(tmp_path: Path) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "docs" / "report-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    report = Report(command="contract", project_root=tmp_path).finish().to_dict()

    assert set(schema["required"]) == set(report)
    assert schema["properties"]["schema_version"]["const"] == report["schema_version"]
    assert report["status"] in schema["properties"]["status"]["enum"]
