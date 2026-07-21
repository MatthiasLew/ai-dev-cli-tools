from pathlib import Path

from ai_dev_tools.config import load_settings


def test_config_overrides_defaults(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[project]\nname='demo'\n[commands]\ntest='pytest'\n[ignore]\npaths=['tmp']\n[reports]\ndirectory='.reports'\nlogs_directory='.logs'\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)
    assert settings.project_name == "demo"
    assert settings.commands["test"] == "pytest"
    assert "tmp" in settings.ignore_paths
    assert settings.reports_directory.name == ".reports"
