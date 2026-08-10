from pathlib import Path

from ai_dev_tools.detectors.workspaces import detect_workspaces, owning_workspace


def test_detect_node_and_python_workspaces(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"workspaces": ["packages/*"], "scripts": {"lint": "eslint ."}}',
        encoding="utf-8",
    )
    api = tmp_path / "packages" / "api"
    api.mkdir(parents=True)
    (api / "pyproject.toml").write_text(
        '[project]\nname = "api"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    web = tmp_path / "packages" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text(
        '{"scripts": {"test": "vitest"}, "engines": {"node": ">=20"}}',
        encoding="utf-8",
    )
    (web / "package-lock.json").write_text("{}", encoding="utf-8")

    workspaces = detect_workspaces(tmp_path)
    by_root = {item.root: item for item in workspaces}

    assert set(by_root) == {"", "packages/api", "packages/web"}
    assert by_root[""].package_manager == "npm"
    assert by_root["packages/api"].technologies == ("python",)
    assert by_root["packages/api"].runtime_requirements[0].runtime == "python"
    assert by_root["packages/web"].commands["test"] == "npm run test"
    assert owning_workspace(workspaces, "packages/api/src/app.py") == by_root["packages/api"]


def test_detect_declared_maven_module(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text(
        "<project><modules><module>services/api</module></modules></project>",
        encoding="utf-8",
    )
    module = tmp_path / "services" / "api"
    module.mkdir(parents=True)
    (module / "pom.xml").write_text("<project />", encoding="utf-8")

    workspaces = detect_workspaces(tmp_path)

    assert [item.root for item in workspaces] == ["", "services/api"]
    assert workspaces[1].package_manager == "maven"
    assert workspaces[1].commands["test"] == "mvn test"


def test_workspace_scan_prunes_generated_directories(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='root'\n", encoding="utf-8")
    generated = tmp_path / "node_modules" / "dependency"
    generated.mkdir(parents=True)
    (generated / "package.json").write_text("{}", encoding="utf-8")

    workspaces = detect_workspaces(tmp_path)

    assert [item.root for item in workspaces] == [""]


def test_workspace_scan_prunes_test_fixtures(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='root'\n", encoding="utf-8")
    fixture = tmp_path / "tests" / "fixtures" / "projects" / "rust"
    fixture.mkdir(parents=True)
    (fixture / "Cargo.toml").write_text("[package]\nname='fixture'\n", encoding="utf-8")

    workspaces = detect_workspaces(tmp_path)

    assert [item.root for item in workspaces] == [""]
