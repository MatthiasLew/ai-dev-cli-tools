from pathlib import Path

from ai_dev_tools.detectors.repository_map import map_repository


def test_map_omits_ignored_paths(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "x.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x=1", encoding="utf-8")
    report = map_repository(tmp_path)
    listed = "\n".join(report.summary["important_files"] + report.summary["directories"])
    assert "ignored/x.py" not in listed
    assert "src" in report.summary["directories"]


def test_map_omits_ai_reports_and_detects_ci(tmp_path: Path) -> None:
    reports = tmp_path / ".ai" / "reports"
    reports.mkdir(parents=True)
    (reports / "old.md").write_text("generated", encoding="utf-8")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI", encoding="utf-8")
    report = map_repository(tmp_path)
    docs = "\n".join(report.summary["documentation"])
    assert ".ai" not in docs
    assert (
        ".github\\workflows\\ci.yml" in report.summary["ci_workflows"]
        or ".github/workflows/ci.yml" in report.summary["ci_workflows"]
    )
