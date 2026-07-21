from pathlib import Path

from ai_dev_tools.detectors.project import scan_project


def test_scan_detects_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\ndependencies=['fastapi']\n[project.scripts]\napp='demo:main'\n",
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("DATABASE_URL=\n", encoding="utf-8")
    report = scan_project(tmp_path)
    assert "python" in report.summary["languages"]
    assert "FastAPI" in report.summary["frameworks"]
    assert "DATABASE_URL" in report.summary["env_example_variables"]
    assert (tmp_path / ".ai" / "reports" / "project-scan.json").exists()
