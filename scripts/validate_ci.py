from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
DOCS = ROOT / ".github" / "workflows" / "docs.yml"
REQUIRED_OS = ["ubuntu-latest", "windows-latest", "macos-latest"]
REQUIRED_PYTHON = ['"3.11"', '"3.12"', '"3.13"']
REQUIRED_STEPS = [
    "ruff check .",
    "mypy src tests",
    "coverage run -m pytest",
    "coverage report",
    "python -m build",
    "ai-dev --version",
    "ai-dev doctor --json",
    "ai-dev scan --json",
    "ai-dev git inspect --json",
    "ai-dev capabilities --json",
]


def main() -> int:
    errors: list[str] = []
    ci = _read(CI, errors)
    docs = _read(DOCS, errors)
    for item in REQUIRED_OS:
        if item not in ci:
            errors.append(f"missing CI OS matrix entry: {item}")
    for item in REQUIRED_PYTHON:
        if item not in ci:
            errors.append(f"missing CI Python matrix entry: {item}")
    for step in REQUIRED_STEPS:
        if step not in ci:
            errors.append(f"missing CI step: {step}")
    for step in ["python -m ai_dev_tools.cli --help", "python -m ai_dev_tools.cli check --help"]:
        if step not in docs:
            errors.append(f"missing Docs step: {step}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("CI workflow validation passed")
    return 0


def _read(path: Path, errors: list[str]) -> str:
    if not path.exists():
        errors.append(f"missing workflow: {path}")
        return ""
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
