from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.context.compression import apply_safe_compression


def _summary() -> dict[str, Any]:
    repeated = "This paragraph explains the same useful behavior."
    return {
        "selected_files": [
            {"path": "src/app.py", "content": "print('exact')\n", "chars": 15},
            {"path": "data.json", "content": '{"exact":true}', "chars": 14},
            {
                "path": "guide.md",
                "content": f"{repeated}\n\n{repeated}\n\n```python\nprint('exact')\n```\n",
                "chars": 140,
            },
            {
                "path": "service.log",
                "content": (
                    "Worker is waiting for another request\n" * 3
                    + "src/app.py:10 abcdef1234567890\n" * 2
                ),
                "chars": 200,
            },
        ],
        "diffs": [{"content": "+exact", "name": "unstaged"}],
        "validation_plan": [{"command": ["pytest", "-q"]}],
        "latest_errors": [{"first_failure": "src/app.py:10"}],
        "changed_symbols": [{"name": "exact", "signature": "abcdef1234567890"}],
        "recent_commits": [{"hash": "abcdef1234567890", "subject": "verify"}],
    }


def test_conservative_compression_only_deduplicates_safe_natural_language() -> None:
    summary = _summary()
    protected_before = {
        item["path"]: item["content"]
        for item in summary["selected_files"]
        if item["path"] in {"src/app.py", "data.json"}
    }
    diffs_before = list(summary["diffs"])

    report = apply_safe_compression(summary, "conservative")

    assert report["compressed_count"] == 2
    assert report["chars_saved"] > 0
    assert report["protected_integrity"] is True
    selected = {item["path"]: item for item in summary["selected_files"]}
    assert selected["src/app.py"]["content"] == protected_before["src/app.py"]
    assert selected["data.json"]["content"] == protected_before["data.json"]
    assert summary["diffs"] == diffs_before
    assert "```python\nprint('exact')\n```" in selected["guide.md"]["content"]
    assert selected["guide.md"]["content"].count("This paragraph explains") == 1
    assert "[repeated 3 times]" in selected["service.log"]["content"]
    assert selected["service.log"]["content"].count("src/app.py:10 abcdef1234567890") == 2


def test_compression_off_is_noop_and_unknown_mode_is_rejected() -> None:
    summary = _summary()
    original = repr(summary)

    report = apply_safe_compression(summary, "off")

    assert repr(summary) == original
    assert report["compressed_count"] == 0
    with pytest.raises(ValueError, match="unknown compression mode"):
        apply_safe_compression(summary, "unsafe")


def test_context_build_reports_compression_savings(tmp_path: Path) -> None:
    paragraph = "A useful documentation paragraph with several words."
    (tmp_path / "guide.md").write_text(f"{paragraph}\n\n{paragraph}\n", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            no_git=True,
            include=("guide.md",),
            compression="conservative",
            max_chars=20_000,
        ),
    )

    assert report.summary["compression"]["compressed_count"] == 1
    assert report.summary["compression"]["protected_integrity"] is True
    assert report.summary["selected_files"][0]["semantic_compressed"] is True
