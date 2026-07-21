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


def test_config_warns_and_ignores_invalid_types(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "unknown=true\ncommands='bad'\n[project]\nname=123\nextra='x'\n[ignore]\npaths='tmp'\n[reports]\ndirectory=42\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)
    assert settings.commands == {}
    assert settings.project_name is None
    assert settings.reports_directory.name == "reports"
    assert "Unknown top-level config key: unknown" in settings.warnings
    assert "Config section [commands] must be a table" in settings.warnings
    assert "Config value [project].name must be a string" in settings.warnings
    assert "Unknown config key: [project].extra" in settings.warnings
    assert "Config value [ignore].paths must be a list of strings" in settings.warnings
    assert "Config value [reports].directory must be a string" in settings.warnings
