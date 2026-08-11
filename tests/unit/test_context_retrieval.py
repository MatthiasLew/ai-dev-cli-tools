from __future__ import annotations

from pathlib import Path

import pytest

from ai_dev_tools.context import ContextOptions, build_context


def _project(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "src" / "app.py").write_text(
        "from helper import VALUE\nprint(VALUE)\n", encoding="utf-8"
    )
    (root / "src" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(
        "def test_app():\n    assert True\n", encoding="utf-8"
    )
    (root / "tests" / "test_unrelated.py").write_text(
        "def test_unrelated():\n    assert True\n", encoding="utf-8"
    )
    (root / "docs" / "guide.md").write_text("long documentation\n", encoding="utf-8")


def test_auto_retrieval_abstains_for_focused_file_and_keeps_evidence(tmp_path: Path) -> None:
    _project(tmp_path)

    report = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            explain=True,
            include=("src/app.py",),
            retrieval="auto",
            max_files=20,
        ),
    )

    retrieval = report.summary["retrieval"]
    selected = {item["path"] for item in report.summary["selected_files"]}
    assert retrieval["decision"] == "abstain"
    assert retrieval["reason_code"] == "FOCUSED_ROOTS_SUFFICIENT"
    assert retrieval["false_negative_proxy"] is False
    assert retrieval["expected_related_tests"] == ("tests/test_app.py",)
    assert "src/app.py" in selected
    assert "tests/test_app.py" in selected
    assert "tests/test_unrelated.py" not in selected
    assert "docs/guide.md" in retrieval["omitted_candidates"]
    assert retrieval["expansion_command"] == "ai-dev context build --retrieval always"


def test_auto_retrieval_adds_static_dependencies_after_abstention(tmp_path: Path) -> None:
    _project(tmp_path)

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, include=("src/app.py",), retrieval="auto", max_files=20),
    )

    selected = {item["path"] for item in report.summary["selected_files"]}
    assert "src/helper.py" in selected
    assert report.summary["retrieval"]["decision"] == "abstain"


def test_auto_retrieval_uses_conservative_fallback_without_focus(tmp_path: Path) -> None:
    _project(tmp_path)

    report = build_context(
        tmp_path,
        ContextOptions(no_git=True, explain=True, retrieval="auto", max_files=20),
    )

    retrieval = report.summary["retrieval"]
    assert retrieval["decision"] == "retrieve"
    assert retrieval["reason_code"] == "NO_FOCUS_CONSERVATIVE_FALLBACK"
    assert retrieval["conservative_fallback_used"] is True
    assert retrieval["omitted_candidate_count"] == 0


def test_always_and_never_override_auto_policy(tmp_path: Path) -> None:
    _project(tmp_path)

    always = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            explain=True,
            include=("src/app.py",),
            retrieval="always",
            max_files=20,
        ),
    )
    never = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            explain=True,
            include=("src/app.py",),
            retrieval="never",
            max_files=20,
        ),
    )

    always_paths = {item["path"] for item in always.summary["selected_files"]}
    never_paths = {item["path"] for item in never.summary["selected_files"]}
    assert "docs/guide.md" in always_paths
    assert "docs/guide.md" not in never_paths
    assert always.summary["retrieval"]["reason_code"] == "RETRIEVAL_FORCED"
    assert never.summary["retrieval"]["reason_code"] == "RETRIEVAL_DISABLED"


def test_unknown_retrieval_mode_is_rejected(tmp_path: Path) -> None:
    _project(tmp_path)

    with pytest.raises(ValueError, match="unknown retrieval mode"):
        build_context(
            tmp_path,
            ContextOptions(no_git=True, retrieval="invalid"),  # type: ignore[arg-type]
        )
