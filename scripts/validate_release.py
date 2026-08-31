from __future__ import annotations

import argparse
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "ai-dev-cli-tools"
ARCHIVE_STEM = "ai_dev_cli_tools"


def read_project_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml is missing project.version")
    return version


def validate_release(root: Path, tag: str, dist: Path | None = None) -> list[str]:
    errors: list[str] = []
    version = read_project_version(root)
    expected_tags = {f"v{version}"}
    candidate = re.fullmatch(r"(\d+\.\d+\.\d+)rc(\d+)", version)
    if candidate:
        expected_tags.add(f"v{candidate.group(1)}-rc.{candidate.group(2)}")
    if tag not in expected_tags:
        errors.append(
            f"tag {tag!r} does not match project version; expected one of {sorted(expected_tags)!r}"
        )

    init_text = (root / "src" / "ai_dev_tools" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.MULTILINE)
    init_version = match.group(1) if match else None
    if init_version != version:
        errors.append(f"package __version__ {init_version!r} does not match {version!r}")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = rf"^## {re.escape(version)}(?:\s+-\s+\d{{4}}-\d{{2}}-\d{{2}})?$"
    if not re.search(heading, changelog, re.MULTILINE):
        errors.append(f"CHANGELOG.md has no release heading for {version}")

    if dist is not None:
        dist_path = dist if dist.is_absolute() else root / dist
        actual = {path.name for path in dist_path.iterdir()} if dist_path.is_dir() else set()
        expected = {
            f"{ARCHIVE_STEM}-{version}-py3-none-any.whl",
            f"{ARCHIVE_STEM}-{version}.tar.gz",
        }
        missing = expected - actual
        unexpected = actual - expected
        if missing:
            errors.append(f"missing distribution files: {sorted(missing)}")
        if unexpected:
            errors.append(f"unexpected distribution files: {sorted(unexpected)}")
        for name in sorted(expected & actual):
            errors.extend(_validate_archive(dist_path / name))
    return errors


def _validate_archive(path: Path) -> list[str]:
    try:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        else:
            with tarfile.open(path, "r:gz") as archive:
                names = archive.getnames()
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        return [f"invalid distribution archive: {path.name}"]
    forbidden = {
        ".ai",
        ".coverage",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
    unsafe = sorted(
        name
        for name in names
        if any(part in forbidden for part in Path(name.replace("\\", "/")).parts)
    )
    return [f"distribution contains generated or private paths: {unsafe[:20]}"] if unsafe else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate release tag, versions, and artifacts.")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args(argv)
    errors = validate_release(ROOT, args.tag, args.dist)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Release validation passed for {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
