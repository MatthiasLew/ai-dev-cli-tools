import json
from pathlib import Path

from ai_dev_tools.reporters.sarif import run_sarif_export


def test_sarif_export_maps_structured_issue_locations(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "code": "TYPE_ERROR",
                        "message": "Invalid value",
                        "file": "src/app.py",
                        "line": 4,
                        "column": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = run_sarif_export(tmp_path, Path("report.json"), None)

    assert report.status == "success"
    output = json.loads((tmp_path / ".ai" / "reports" / "ai-dev.sarif").read_text())
    result = output["runs"][0]["results"][0]
    assert result["ruleId"] == "TYPE_ERROR"
    assert result["locations"][0]["physicalLocation"]["region"]["startLine"] == 4


def test_sarif_export_rejects_external_input(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.json"
    report = run_sarif_export(tmp_path, outside, None)
    assert report.status == "invalid_configuration"


def test_sarif_export_rejects_invalid_json_and_ignores_boolean_locations(tmp_path: Path) -> None:
    source = tmp_path / "invalid.json"
    source.write_text("not-json", encoding="utf-8")
    assert run_sarif_export(tmp_path, source, None).status == "invalid_configuration"

    source.write_text(
        json.dumps({"issues": [{"file": "app.py", "line": True, "column": False}]}),
        encoding="utf-8",
    )
    report = run_sarif_export(tmp_path, source, None)
    assert report.status == "success"
    output = json.loads((tmp_path / ".ai" / "reports" / "ai-dev.sarif").read_text())
    physical = output["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert "region" not in physical
