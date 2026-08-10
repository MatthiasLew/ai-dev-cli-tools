from pathlib import Path

from ai_dev_tools.detectors.runtime import (
    detect_runtime_requirements,
    evaluate_requirement,
)
from ai_dev_tools.models.workspace import RuntimeRequirement


def test_detect_runtime_requirements_across_ecosystems(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nrequires-python = ">=3.11,<3.14"\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"engines": {"node": ">=20"}}', encoding="utf-8")
    (tmp_path / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "1.80"\n', encoding="utf-8"
    )
    (tmp_path / "composer.json").write_text('{"require": {"php": "^8.2"}}', encoding="utf-8")

    requirements = detect_runtime_requirements(tmp_path)
    values = {(item.runtime, item.constraint, item.source) for item in requirements}

    assert ("python", ">=3.11,<3.14", "pyproject.toml") in values
    assert ("node", ">=20", "package.json") in values
    assert ("rust", "1.80", "rust-toolchain.toml") in values
    assert ("php", "^8.2", "composer.json") in values


def test_runtime_compatibility_reports_all_states() -> None:
    requirement = RuntimeRequirement("python", ">=3.11,<3.14", "pyproject.toml")

    assert evaluate_requirement(requirement, "Python 3.12.4")["status"] == "compatible"
    assert evaluate_requirement(requirement, "Python 3.14.0")["status"] == "incompatible"
    assert evaluate_requirement(requirement, None)["status"] == "missing"
    assert evaluate_requirement(requirement, "development build")["status"] == "unknown"


def test_runtime_compatibility_supports_caret_and_tilde() -> None:
    php = RuntimeRequirement("php", "^8.2", "composer.json")
    node = RuntimeRequirement("node", "~20.3", "package.json")

    assert evaluate_requirement(php, "PHP 8.3.1")["status"] == "compatible"
    assert evaluate_requirement(php, "PHP 9.0.0")["status"] == "incompatible"
    assert evaluate_requirement(node, "v20.3.8")["status"] == "compatible"
    assert evaluate_requirement(node, "v20.4.0")["status"] == "incompatible"
