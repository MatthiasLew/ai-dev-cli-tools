from __future__ import annotations

from pathlib import Path

from scripts.validate_release import read_project_version, validate_release
from scripts.verify_published_package import entrypoint_path


def write_release_project(root: Path, version: str = "1.2.3a1") -> None:
    (root / "src" / "ai_dev_tools").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "ai-dev-cli-tools"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "src" / "ai_dev_tools" / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## {version} - 2026-08-10\n", encoding="utf-8"
    )


def test_validate_release_accepts_matching_source_and_artifacts(tmp_path: Path) -> None:
    write_release_project(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "ai_dev_cli_tools-1.2.3a1-py3-none-any.whl").touch()
    (dist / "ai_dev_cli_tools-1.2.3a1.tar.gz").touch()

    assert read_project_version(tmp_path) == "1.2.3a1"
    assert validate_release(tmp_path, "v1.2.3a1", dist) == []


def test_validate_release_reports_tag_version_changelog_and_artifact_errors(tmp_path: Path) -> None:
    write_release_project(tmp_path)
    (tmp_path / "src" / "ai_dev_tools" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "unexpected.whl").touch()

    errors = validate_release(tmp_path, "v0.0.0", dist)

    assert len(errors) == 5
    assert any("does not match project version" in error for error in errors)
    assert any("package __version__" in error for error in errors)
    assert any("no release heading" in error for error in errors)
    assert any("missing distribution files" in error for error in errors)
    assert any("unexpected distribution files" in error for error in errors)


def test_published_entrypoint_path_matches_platform(tmp_path: Path) -> None:
    path = entrypoint_path(tmp_path)
    assert path.name in {"ai-dev", "ai-dev.exe"}
