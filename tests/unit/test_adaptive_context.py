from pathlib import Path

from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.context.adaptive import adaptive_task_scope, apply_adaptive_budget
from ai_dev_tools.context.builder import _compact_context_metadata
from ai_dev_tools.reporters.progressive import run_explain


def test_adaptive_budget_classifies_task_and_shrinks_default_budget(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            task="document the public API",
            include=("README.md",),
            no_git=True,
            explain=True,
            adaptive=True,
        ),
    )

    decision = report.summary["adaptive_context"]
    assert decision["enabled"] is True
    assert decision["intent"] == "docs"
    assert decision["scope"] == "focused"
    assert decision["resolved_budget"]["max_chars"] == 16_800
    assert decision["resolved_budget"]["estimated_token_ceiling"] == 4_200
    assert report.summary["options"]["max_chars"] == 16_800


def test_adaptive_budget_preserves_explicit_limits() -> None:
    original = ContextOptions(
        task="implement feature", adaptive=True, max_chars=9_000, max_files=7
    )
    resolved, decision = apply_adaptive_budget(
        original,
        original,
        changed_files=1,
        candidate_files=5,
        latest_errors=0,
    )

    assert resolved.max_chars == 9_000
    assert resolved.max_files == 7
    assert decision["explicit_overrides"] == ["max_chars", "max_files"]


def test_adaptive_incremental_memory_is_scoped_to_normalized_task(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    def context(task: str):  # type: ignore[no-untyped-def]
        return build_context(
            tmp_path,
            ContextOptions(
                task=task,
                include=("app.py",),
                no_git=True,
                incremental=True,
                adaptive=True,
                format="json",
            ),
        )

    first = context("Fix parser bug")
    repeated = context("  fix PARSER bug  ")
    different = context("Document public API")

    assert [item["path"] for item in first.summary["selected_files"]] == ["app.py"]
    assert repeated.summary["selected_files"] == []
    assert repeated.summary["incremental"]["reused"] == 1
    assert [item["path"] for item in different.summary["selected_files"]] == ["app.py"]
    assert adaptive_task_scope("Fix parser bug") == adaptive_task_scope("  fix PARSER bug  ")
    assert adaptive_task_scope("Fix parser bug") != adaptive_task_scope("Document public API")


def test_uncertain_adaptive_task_broadens_instead_of_over_narrowing() -> None:
    original = ContextOptions(task="", adaptive=True)
    resolved, decision = apply_adaptive_budget(
        original,
        original,
        changed_files=0,
        candidate_files=20,
        latest_errors=0,
    )

    assert decision["scope"] == "uncertain"
    assert decision["reason_codes"] == ["LOW_CONFIDENCE_BROADENED"]
    assert resolved.max_chars == 34_500


def test_adaptive_budget_keeps_disabled_mode_unchanged() -> None:
    original = ContextOptions(task="review everything")

    resolved, decision = apply_adaptive_budget(
        original,
        original,
        changed_files=50,
        candidate_files=200,
        latest_errors=4,
    )

    assert resolved == original
    assert decision == {"enabled": False}


def test_adaptive_budget_broadens_large_review_and_prioritizes_failures() -> None:
    broad = ContextOptions(task="review the entire architecture", adaptive=True)
    broad_resolved, broad_decision = apply_adaptive_budget(
        broad,
        broad,
        changed_files=1,
        candidate_files=5,
        latest_errors=0,
    )
    failing = ContextOptions(task="check current behavior", adaptive=True)
    failing_resolved, failing_decision = apply_adaptive_budget(
        failing,
        failing,
        changed_files=4,
        candidate_files=20,
        latest_errors=2,
    )

    assert broad_decision["scope"] == "broad"
    assert broad_resolved.max_chars == 37_800
    assert failing_decision["intent"] == "debug"
    assert failing_decision["scope"] == "bounded"
    assert failing_resolved.max_chars == 32_000


def test_context_metadata_compaction_bounds_repeated_lists() -> None:
    summary: dict[str, object] = {
        "changed_symbols": [
            {"path": f"src/{index}.py", "name": f"symbol_{index}", "content": "unused"}
            for index in range(15)
        ],
        "repository_map": {"files": [f"src/{index}.py" for index in range(14)]},
        "retrieval": {"omitted_candidates": tuple(range(25))},
    }

    assert _compact_context_metadata(summary) is True
    symbols = summary["changed_symbols"]
    repository_map = summary["repository_map"]
    retrieval = summary["retrieval"]
    assert isinstance(symbols, list)
    assert isinstance(repository_map, dict)
    assert isinstance(repository_map["files"], list)
    assert isinstance(retrieval, dict)
    assert isinstance(retrieval["omitted_candidates"], list)
    assert len(symbols) == 12
    assert summary["changed_symbols_omitted"] == 3
    assert len(repository_map["files"]) == 10
    assert summary["repository_map_omitted"] == {"files": 4}
    assert len(retrieval["omitted_candidates"]) == 20
    assert retrieval["omitted_candidates_truncated"] is True


def test_global_character_budget_omits_low_priority_content_before_agent_output(
    tmp_path: Path,
) -> None:
    (tmp_path / "first.md").write_text("A" * 4_000, encoding="utf-8")
    (tmp_path / "second.md").write_text("B" * 4_000, encoding="utf-8")

    report = build_context(
        tmp_path,
        ContextOptions(
            task="document API",
            include=("*.md",),
            no_git=True,
            max_chars=3_000,
            max_file_chars=4_000,
            format="json",
        ),
    )

    budget = report.summary["character_budget"]
    assert budget["content_omitted"] is True
    assert budget["chars_avoided"] >= 4_000
    selected = report.summary["selected_files"]
    assert any(item["budget_reason_code"] == "GLOBAL_CONTEXT_BUDGET" for item in selected)
    assert sum(len(str(item["content"])) for item in selected) <= 4_000
    omitted = next(item for item in selected if item.get("budget_reason_code"))
    expanded = run_explain(tmp_path, str(omitted["evidence_id"]), tail=2)
    assert expanded.status == "success"
    assert expanded.summary["evidence"]["expanded_content"]
    assert expanded.summary["evidence"]["evidence_state"] in {"unchanged", "recomputed"}
