from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_dev_tools.telemetry import record_usage
from ai_dev_tools.telemetry_optimizer import (
    compact_optimizer_status,
    export_usage,
    optimize_usage,
)


def _pricing(root: Path) -> None:
    path = root / ".ai-dev/telemetry-pricing.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "currency": "USD",
        "models": {
            "capable": {"input_per_million": 10, "output_per_million": 20},
            "cheap": {"input_per_million": 1, "output_per_million": 2},
        },
    }), encoding="utf-8")


def _record(
    root: Path, request: str, *, model: str = "capable", quality: bool | None = True,
    tokens: int = 100,
) -> dict[str, object]:
    return record_usage(
        root,
        client="codex",
        model=model,
        request_id=request,
        input_tokens=tokens,
        cached_input_tokens=tokens // 4,
        output_tokens=tokens // 10,
        phase="implementation",
        tool_name="build_context",
        task_kind="code-review",
        quality_passed=quality,
        duration_seconds=tokens / 10,
    )


def test_optimizer_attributes_usage_and_recommends_percentile_budget(tmp_path: Path) -> None:
    for index, tokens in enumerate((100, 110, 120, 130, 200)):
        _record(tmp_path, f"sample-{index}", tokens=tokens)

    report = optimize_usage(
        tmp_path, min_sessions=5, percentile=95, safety_margin_percent=20
    )

    assert report.status == "success"
    assert report.summary["overall"]["p50_total_tokens"] == 132
    assert report.summary["overall"]["p95_total_tokens"] == 220
    assert report.summary["overall"]["cache_share_percent"] > 0
    assert report.summary["overall"]["p50_duration_seconds"] == 12.0
    assert report.summary["overall"]["p95_duration_seconds"] == 20.0
    assert report.summary["attribution"]["phases"][0]["name"] == "implementation"
    assert report.summary["attribution"]["tools"][0]["name"] == "build_context"
    global_budget = report.summary["budget_recommendations"][0]
    assert global_budget["recommended_max_total_tokens"] == 264
    assert global_budget["automatic_apply"] is False


def test_optimizer_recommends_cheaper_model_only_with_quality_and_cost_evidence(
    tmp_path: Path,
) -> None:
    _pricing(tmp_path)
    for index in range(6):
        _record(tmp_path, f"capable-{index}", model="capable")
    for index in range(5):
        _record(tmp_path, f"cheap-{index}", model="cheap")

    report = optimize_usage(tmp_path, min_sessions=5, accuracy_target_percent=95)
    recommendation = report.summary["model_recommendations"][0]

    assert recommendation["current_model"] == "capable"
    assert recommendation["candidate_model"] == "cheap"
    assert recommendation["candidate_quality_percent"] == 100.0
    assert recommendation["estimated_savings_percent"] == 90.0
    assert recommendation["requires_human_approval"] is True
    assert recommendation["automatic_switch"] is False


def test_optimizer_rejects_cheaper_model_below_accuracy_target(tmp_path: Path) -> None:
    _pricing(tmp_path)
    for index in range(6):
        _record(tmp_path, f"capable-{index}", model="capable")
    for index in range(5):
        _record(tmp_path, f"cheap-{index}", model="cheap", quality=index < 4)

    report = optimize_usage(tmp_path, min_sessions=5, accuracy_target_percent=95)

    assert report.summary["model_recommendations"] == []
    assert report.summary["gaps"][-1]["code"] == (
        "MODEL_ROUTING_NO_CHEAPER_QUALIFIED_MODEL"
    )


def test_optimizer_reports_evidence_gaps_without_guessing(tmp_path: Path) -> None:
    for index in range(3):
        _record(tmp_path, f"sample-{index}", quality=None)

    report = optimize_usage(tmp_path, min_sessions=5)

    codes = {item["code"] for item in report.summary["gaps"]}
    assert codes == {
        "TOKEN_OPTIMIZER_INSUFFICIENT_USAGE_DATA",
        "MODEL_ROUTING_NO_QUALITY_DATA",
    }
    assert report.summary["automatic_changes"] is False
    assert compact_optimizer_status(tmp_path)["gaps"] == 2


@pytest.mark.parametrize(("argument", "value"), [
    ("min_sessions", 1),
    ("percentile", 49),
    ("safety_margin_percent", -1),
    ("accuracy_target_percent", 101),
    ("max_accuracy_drop_percent", float("nan")),
])
def test_optimizer_configuration_is_bounded(
    tmp_path: Path, argument: str, value: object
) -> None:
    options: dict[str, object] = {argument: value}

    report = optimize_usage(tmp_path, **options)  # type: ignore[arg-type]

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "INVALID_TELEMETRY_OPTIMIZER"


def test_usage_metadata_is_bounded_and_contains_no_content(tmp_path: Path) -> None:
    stored = _record(tmp_path, "metadata")

    assert stored["phase"] == "implementation"
    assert stored["tool_name"] == "build_context"
    assert stored["task_kind"] == "code-review"
    assert stored["quality_passed"] is True
    assert stored["duration_seconds"] == 10.0
    assert "prompt" not in stored
    with pytest.raises(ValueError, match="phase"):
        record_usage(
            tmp_path, client="generic", input_tokens=1, output_tokens=1,
            phase="x" * 101,
        )
    with pytest.raises(ValueError, match="quality_passed"):
        record_usage(
            tmp_path, client="generic", input_tokens=1, output_tokens=1,
            quality_passed="yes",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="duration_seconds"):
        record_usage(
            tmp_path, client="generic", input_tokens=1, output_tokens=1,
            duration_seconds=float("inf"),
        )


def test_optimizer_exports_aggregated_json_and_csv_without_content(tmp_path: Path) -> None:
    for index in range(5):
        _record(tmp_path, f"sample-{index}", tokens=100 + index)

    json_report = export_usage(
        tmp_path, format_name="json", output_path=Path("exports/usage.json")
    )
    csv_report = export_usage(
        tmp_path, format_name="csv", output_path=Path("exports/usage.csv")
    )

    assert json_report.status == "success"
    assert csv_report.status == "success"
    exported_json = (tmp_path / "exports/usage.json").read_text(encoding="utf-8")
    exported_csv = (tmp_path / "exports/usage.csv").read_text(encoding="utf-8")
    assert "request_id" not in exported_json
    assert "prompt" not in exported_json
    assert "p95_duration_seconds" in exported_csv
    assert "sample-" not in exported_csv


def test_optimizer_export_rejects_overwrite_and_external_path(tmp_path: Path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")

    overwrite = export_usage(tmp_path, output_path=existing)
    outside = export_usage(tmp_path, output_path=tmp_path.parent / "outside.json")

    assert overwrite.summary["reason_code"] == "TELEMETRY_EXPORT_EXISTS"
    assert outside.summary["reason_code"] == "TELEMETRY_EXPORT_OUTSIDE_PROJECT"
