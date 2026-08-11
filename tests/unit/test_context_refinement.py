from __future__ import annotations

from pathlib import Path

from ai_dev_tools.context.refinement import refine_candidates


def test_refinement_follows_dependencies_across_bounded_rounds(tmp_path: Path) -> None:
    app = tmp_path / "app.py"
    helper = tmp_path / "helper.py"
    leaf = tmp_path / "leaf.py"
    app.write_text("import helper\n", encoding="utf-8")
    helper.write_text("import leaf\n", encoding="utf-8")
    leaf.write_text("VALUE = 1\n", encoding="utf-8")

    refined, report = refine_candidates(
        tmp_path,
        {app: "included"},
        {app: "included"},
        ["failure in app"],
        max_rounds=2,
        max_added_files=5,
    )

    assert set(refined) == {app, helper, leaf}
    assert report["added_files"] == ["helper.py", "leaf.py"]
    assert report["stop_reason"] == "REFINEMENT_ROUND_BUDGET_REACHED"
    assert len(report["rounds"]) == 2


def test_refinement_matches_failure_path_and_stops_at_file_budget(tmp_path: Path) -> None:
    app = tmp_path / "app.py"
    auth = tmp_path / "auth_service.py"
    test = tmp_path / "tests" / "test_auth_service.py"
    test.parent.mkdir()
    for path in (app, auth, test):
        path.write_text("pass\n", encoding="utf-8")

    refined, report = refine_candidates(
        tmp_path,
        {app: "changed"},
        {app: "changed", auth: "source", test: "test"},
        [{"first_failure": "tests/test_auth_service.py:10"}],
        max_rounds=3,
        max_added_files=1,
    )

    assert len(refined) == 2
    assert report["added_files"] == ["tests/test_auth_service.py"]
    assert report["stop_reason"] == "REFINEMENT_FILE_BUDGET_REACHED"


def test_refinement_is_noop_without_signal_or_budget(tmp_path: Path) -> None:
    app = tmp_path / "app.py"
    app.write_text("pass\n", encoding="utf-8")

    _, no_signal = refine_candidates(tmp_path, {app: "seed"}, {}, [], 2, 5)
    _, disabled = refine_candidates(tmp_path, {app: "seed"}, {}, ["app"], 0, 5)

    assert no_signal["stop_reason"] == "NO_REFINEMENT_SIGNAL"
    assert no_signal["added_count"] == 0
    assert disabled["enabled"] is False
