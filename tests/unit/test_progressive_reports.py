from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.reporters.progressive import run_explain
from ai_dev_tools.reporters.writer import write_json


def test_report_assigns_stable_evidence_ids_and_expansion_metadata(tmp_path: Path) -> None:
    report = Report(command="check", project_root=tmp_path)
    report.issues.append(Issue("error", "boom", code="TEST_FAILURE", file="tests/test_app.py"))
    report.summary = {
        "selected_files": [
            {
                "path": "src/app.py",
                "reason": "changed file",
                "snippets": [{"name": "main", "start_line": 1, "end_line": 3}],
            }
        ],
        "diffs": [{"name": "unstaged", "content": "+changed"}],
    }

    first = report.to_dict()
    second = report.to_dict()

    issue_id = first["issues"][0]["evidence_id"]
    assert issue_id.startswith("issue:")
    assert first["summary"]["selected_files"][0]["evidence_id"].startswith("file:")
    assert first["summary"]["selected_files"][0]["snippets"][0]["evidence_id"].startswith(
        "snippet:"
    )
    assert first["summary"]["diffs"][0]["evidence_id"].startswith("diff:")
    assert first["metadata"]["progressive"]["expandable_evidence"] == 4
    assert first["metadata"]["progressive"] == second["metadata"]["progressive"]


def test_explain_expands_only_requested_local_artifact(tmp_path: Path) -> None:
    log = tmp_path / ".ai" / "logs" / "check.log"
    log.parent.mkdir(parents=True)
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    report = Report(command="check", project_root=tmp_path)
    report.artifacts.append(Artifact(str(log), "log", "Full check log"))
    report_path = tmp_path / ".ai" / "reports" / "check-latest.json"
    write_json(report, report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    reference = payload["artifacts"][0]["evidence_id"]

    expanded = run_explain(tmp_path, reference, tail=2)

    assert expanded.status == "success"
    assert expanded.summary["evidence"]["expanded_content"] == ["two", "three"]
    assert expanded.summary["evidence"]["total_line_count"] == 3


def test_explain_reports_unknown_reference(tmp_path: Path) -> None:
    report = run_explain(tmp_path, "issue:missing")

    assert report.status == "failed"
    assert report.summary["reason_code"] == "EVIDENCE_NOT_FOUND"
