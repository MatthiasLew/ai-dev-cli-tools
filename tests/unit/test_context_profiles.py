from pathlib import Path

import pytest

from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.context.profiles import profile_names


def test_minimal_profile_applies_budgets_and_preserves_explicit_override(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            profile="minimal",
            max_chars=13_000,
            no_git=True,
            explain=True,
            include=("README.md",),
        ),
    )

    options = report.summary["options"]
    assert options["profile"] == "minimal"
    assert options["max_chars"] == 13_000
    assert options["max_files"] == 8
    assert options["max_file_chars"] == 2_500
    assert options["max_diff_chars"] == 4_000


def test_review_profile_enables_changed_only(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(profile="review", no_git=True, explain=True, include=("README.md",)),
    )

    assert report.summary["options"]["changed_only"] is True
    assert report.summary["selected_files"] == []


def test_context_profiles_are_stable_and_unknown_profile_fails(tmp_path: Path) -> None:
    assert profile_names() == ("minimal", "debug", "review", "implement", "docs", "full")
    with pytest.raises(ValueError, match="Unknown context profile"):
        build_context(tmp_path, ContextOptions(profile="unknown", no_git=True))


@pytest.mark.parametrize(
    ("profile", "max_chars", "max_files", "max_file_chars", "max_diff_chars"),
    [
        ("implement", 70_000, 40, 12_000, 18_000),
        ("docs", 45_000, 35, 10_000, 12_000),
    ],
)
def test_implement_and_docs_profiles_have_stable_contracts(
    tmp_path: Path,
    profile: str,
    max_chars: int,
    max_files: int,
    max_file_chars: int,
    max_diff_chars: int,
) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(profile=profile, no_git=True, explain=True, include=("README.md",)),
    )

    options = report.summary["options"]
    assert options == {
        **options,
        "profile": profile,
        "max_chars": max_chars,
        "max_files": max_files,
        "max_file_chars": max_file_chars,
        "max_diff_chars": max_diff_chars,
    }
