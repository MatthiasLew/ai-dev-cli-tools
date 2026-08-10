from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from ai_dev_tools.models.workspace import RuntimeRequirement

_VERSION = re.compile(r"\d+(?:\.\d+){0,3}")


def detect_runtime_requirements(root: Path) -> list[RuntimeRequirement]:
    requirements: list[RuntimeRequirement] = []
    pyproject = _toml(root / "pyproject.toml")
    project = pyproject.get("project", {})
    if isinstance(project, dict) and isinstance(project.get("requires-python"), str):
        requirements.append(
            RuntimeRequirement("python", project["requires-python"], "pyproject.toml")
        )
    python_version = _first_line(root / ".python-version")
    if python_version:
        requirements.append(RuntimeRequirement("python", python_version, ".python-version"))

    package = _json(root / "package.json")
    engines = package.get("engines", {})
    if isinstance(engines, dict) and isinstance(engines.get("node"), str):
        requirements.append(RuntimeRequirement("node", engines["node"], "package.json"))
    nvmrc = _first_line(root / ".nvmrc")
    if nvmrc:
        requirements.append(RuntimeRequirement("node", nvmrc, ".nvmrc"))

    rust_toolchain = _toml(root / "rust-toolchain.toml")
    toolchain = rust_toolchain.get("toolchain", {})
    if isinstance(toolchain, dict) and isinstance(toolchain.get("channel"), str):
        requirements.append(RuntimeRequirement("rust", toolchain["channel"], "rust-toolchain.toml"))
    elif channel := _first_line(root / "rust-toolchain"):
        requirements.append(RuntimeRequirement("rust", channel, "rust-toolchain"))

    composer = _json(root / "composer.json")
    composer_require = composer.get("require", {})
    if isinstance(composer_require, dict) and isinstance(composer_require.get("php"), str):
        requirements.append(RuntimeRequirement("php", composer_require["php"], "composer.json"))

    pom_text = _text(root / "pom.xml")
    java_constraint = _first_match(
        pom_text,
        (
            r"<maven\.compiler\.release>\s*([^<]+)",
            r"<maven\.compiler\.source>\s*([^<]+)",
            r"<java\.version>\s*([^<]+)",
        ),
    )
    if java_constraint:
        requirements.append(RuntimeRequirement("java", java_constraint, "pom.xml"))

    gradle_text = _text(root / "build.gradle") + "\n" + _text(root / "build.gradle.kts")
    gradle_java = _first_match(
        gradle_text,
        (
            r"(?:sourceCompatibility|languageVersion)\s*[=:]?\s*(?:JavaVersion\.VERSION_)?([0-9_\.]+)",
        ),
    )
    if gradle_java:
        requirements.append(
            RuntimeRequirement("java", gradle_java.replace("_", "."), "Gradle configuration")
        )
    return _deduplicate(requirements)


def evaluate_requirement(
    requirement: RuntimeRequirement, detected_version: str | None
) -> dict[str, str | None]:
    if detected_version is None:
        return {
            **requirement.to_dict(),
            "detected": None,
            "status": "missing",
        }
    detected = _version_tuple(detected_version)
    if detected is None:
        return {
            **requirement.to_dict(),
            "detected": detected_version,
            "status": "unknown",
        }
    compatible = _matches_constraint(detected, requirement.constraint)
    return {
        **requirement.to_dict(),
        "detected": detected_version,
        "status": "compatible" if compatible else "incompatible",
    }


def _matches_constraint(version: tuple[int, ...], constraint: str) -> bool:
    normalized = constraint.strip().lower().removeprefix("v")
    if normalized in {"stable", "nightly", "beta", "*", "latest"}:
        return True
    alternatives = [item.strip() for item in normalized.split("||")]
    return any(_matches_all(version, alternative) for alternative in alternatives)


def _matches_all(version: tuple[int, ...], constraint: str) -> bool:
    parts = [item for item in re.split(r"\s*,\s*|\s+", constraint) if item]
    if not parts:
        return True
    for part in parts:
        match = re.match(r"(>=|<=|==|=|>|<|\^|~)?\s*v?(\d+(?:\.\d+){0,3})", part)
        if match is None:
            continue
        operator = match.group(1) or "=="
        expected = _version_tuple(match.group(2))
        if expected is None:
            continue
        left, right = _padded(version, expected)
        if operator in {"=", "=="} and left[: len(expected)] != right[: len(expected)]:
            return False
        if operator == ">=" and left < right:
            return False
        if operator == "<=" and left > right:
            return False
        if operator == ">" and left <= right:
            return False
        if operator == "<" and left >= right:
            return False
        if operator == "^":
            upper = (right[0] + 1, *([0] * (len(right) - 1)))
            if left < right or left >= upper:
                return False
        if operator == "~":
            upper = (right[0], (right[1] if len(right) > 1 else 0) + 1, 0, 0)
            upper = upper[: len(right)]
            if left < right or left >= upper:
                return False
    return True


def _padded(
    left: tuple[int, ...], right: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    size = max(len(left), len(right), 3)
    return left + (0,) * (size - len(left)), right + (0,) * (size - len(right))


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = _VERSION.search(value)
    return tuple(int(item) for item in match.group(0).split(".")) if match else None


def _deduplicate(items: list[RuntimeRequirement]) -> list[RuntimeRequirement]:
    found: dict[tuple[str, str, str], RuntimeRequirement] = {}
    for item in items:
        found[(item.runtime, item.constraint, item.source)] = item
    return list(found.values())


def _first_match(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if match := re.search(pattern, text):
            return match.group(1).strip()
    return None


def _first_line(path: Path) -> str | None:
    text = _text(path).strip()
    return text.splitlines()[0].strip() if text else None


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
            return value if isinstance(value, dict) else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
