from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_dev_tools.telemetry import load_session_rows, record_usage
from ai_dev_tools.telemetry_policy import (
    activate_pricing_snapshot,
    import_pricing_snapshot,
    telemetry_gate,
)


def _record(root: Path, request_id: str, tokens: int, *, client: str = "codex",
            model: str = "model-a") -> None:
    record_usage(
        root,
        client=client,
        model=model,
        request_id=request_id,
        input_tokens=tokens,
        output_tokens=tokens // 10,
    )


def test_gate_enforces_global_client_and_model_limits(tmp_path: Path) -> None:
    _record(tmp_path, "one", 100, client="codex", model="model-a")
    _record(tmp_path, "two", 200, client="claude", model="model-b")
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.parent.mkdir()
    policy.write_text(json.dumps({
        "schema_version": "1",
        "window_sessions": 10,
        "limits": {"max_total_tokens": 250},
        "clients": {"codex": {"max_input_tokens": 50}},
        "models": {"model-b": {"max_output_tokens": 10}},
    }), encoding="utf-8")

    report = telemetry_gate(tmp_path)

    assert report.status == "failed"
    assert report.summary["passed"] is False
    scopes = {item["scope"] for item in report.summary["violations"]}
    assert scopes == {"global", "client:codex", "model:model-b"}
    assert {issue.code for issue in report.issues} == {"TELEMETRY_BUDGET_EXCEEDED"}


def test_regression_uses_two_equal_chronological_windows(tmp_path: Path) -> None:
    for index, tokens in enumerate((100, 100, 200, 220)):
        _record(tmp_path, f"request-{index}", tokens)
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.parent.mkdir()
    policy.write_text(json.dumps({
        "regression": {
            "recent_sessions": 2,
            "min_baseline_sessions": 2,
            "max_total_tokens_percent": 50,
        }
    }), encoding="utf-8")

    report = telemetry_gate(tmp_path)

    alert = report.summary["alerts"][0]
    assert report.status == "failed"
    assert alert["code"] == "TELEMETRY_REGRESSION_EXCEEDED"
    assert alert["regression_percent"] == 110.0


def test_regression_reports_insufficient_data_without_failing(tmp_path: Path) -> None:
    _record(tmp_path, "one", 100)
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.parent.mkdir()
    policy.write_text(json.dumps({
        "regression": {"recent_sessions": 2, "min_baseline_sessions": 2,
                       "max_total_tokens_percent": 10}
    }), encoding="utf-8")

    report = telemetry_gate(tmp_path)

    assert report.status == "success"
    assert report.summary["alerts"][0]["code"] == "TELEMETRY_REGRESSION_INSUFFICIENT_DATA"


def test_session_loader_orders_recorded_time_not_hash_name(tmp_path: Path) -> None:
    directory = tmp_path / ".ai/token-efficiency/sessions"
    directory.mkdir(parents=True)
    for name, timestamp, tokens in (
        ("z.json", "2026-01-01T00:00:00+00:00", 1),
        ("a.json", "2026-01-02T00:00:00+00:00", 2),
    ):
        (directory / name).write_text(json.dumps({
            "measurement": "provider_reported", "recorded_at": timestamp,
            "input_tokens": tokens,
        }), encoding="utf-8")

    rows = load_session_rows(tmp_path)

    assert [row["input_tokens"] for row in rows] == [1, 2]


def test_pricing_snapshot_is_versioned_active_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "pricing.json"
    source.write_text(json.dumps({
        "currency": "USD",
        "models": {"model-a": {"input_per_million": 2, "output_per_million": 8}},
    }), encoding="utf-8")

    first = import_pricing_snapshot(
        tmp_path, source, provider="openai", version="2026-09-01",
        source="https://developers.openai.com/api/docs/models/compare",
    )
    second = import_pricing_snapshot(
        tmp_path, source, provider="openai", version="2026-09-01",
        source="https://developers.openai.com/api/docs/models/compare",
    )
    stored = record_usage(
        tmp_path, client="codex", model="model-a", request_id="priced",
        input_tokens=1000, output_tokens=100,
    )

    assert first.status == second.status == "success"
    assert first.summary["sha256"] == second.summary["sha256"]
    assert Path(first.summary["snapshot"]).is_file()
    assert stored["cost"]["estimated_amount"] == 0.0028
    assert stored["cost"]["pricing_provider"] == "openai"
    assert stored["cost"]["pricing_version"] == "2026-09-01"
    assert stored["cost"]["pricing_sha256"] == first.summary["sha256"]


def test_snapshot_conflict_and_invalid_policy_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "pricing.json"
    source.write_text(json.dumps({
        "models": {"default": {"input_per_million": 1, "output_per_million": 2}}
    }), encoding="utf-8")
    assert import_pricing_snapshot(
        tmp_path, source, provider="generic", version="v1"
    ).status == "success"
    source.write_text(json.dumps({
        "models": {"default": {"input_per_million": 9, "output_per_million": 9}}
    }), encoding="utf-8")
    assert import_pricing_snapshot(
        tmp_path, source, provider="generic", version="v1"
    ).status == "invalid_configuration"

    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.write_text(json.dumps({"unknown": True}), encoding="utf-8")
    assert telemetry_gate(tmp_path).status == "invalid_configuration"


def test_snapshot_can_be_imported_inactive_then_activated(tmp_path: Path) -> None:
    source = tmp_path / "pricing.json"
    source.write_text(json.dumps({
        "models": {"default": {"input_per_million": 1, "output_per_million": 2}}
    }), encoding="utf-8")
    imported = import_pricing_snapshot(
        tmp_path, source, provider="generic", version="v2", activate=False
    )

    assert imported.status == "success"
    assert not (tmp_path / ".ai-dev/telemetry-pricing.json").exists()
    activated = activate_pricing_snapshot(tmp_path, provider="generic", version="v2")
    assert activated.status == "success"
    assert (tmp_path / ".ai-dev/telemetry-pricing.json").is_file()


def test_active_snapshot_detects_content_tampering(tmp_path: Path) -> None:
    source = tmp_path / "pricing.json"
    source.write_text(json.dumps({
        "models": {"default": {"input_per_million": 1, "output_per_million": 2}}
    }), encoding="utf-8")
    imported = import_pricing_snapshot(
        tmp_path, source, provider="generic", version="tamper-test"
    )
    snapshot = Path(imported.summary["snapshot"])
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["models"]["default"]["input_per_million"] = 999
    snapshot.write_text(json.dumps(payload), encoding="utf-8")

    try:
        record_usage(
            tmp_path, client="generic", request_id="tampered",
            input_tokens=1, output_tokens=1,
        )
    except ValueError as exc:
        assert str(exc) == "active pricing snapshot integrity check failed"
    else:
        raise AssertionError("tampered active snapshot was accepted")


def test_reimport_detects_existing_snapshot_tampering(tmp_path: Path) -> None:
    source = tmp_path / "pricing.json"
    source.write_text(json.dumps({
        "models": {"default": {"input_per_million": 1, "output_per_million": 2}}
    }), encoding="utf-8")
    imported = import_pricing_snapshot(
        tmp_path, source, provider="generic", version="reimport-test"
    )
    snapshot = Path(imported.summary["snapshot"])
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["models"]["default"]["output_per_million"] = 999
    snapshot.write_text(json.dumps(payload), encoding="utf-8")

    repeated = import_pricing_snapshot(
        tmp_path, source, provider="generic", version="reimport-test"
    )

    assert repeated.status == "invalid_configuration"


@pytest.mark.parametrize("payload", [
    {"schema_version": "2"},
    {"window_sessions": True},
    {"limits": []},
    {"limits": {"unknown": 1}},
    {"limits": {"max_estimated_costs": {}}},
    {"clients": []},
    {"clients": {"\x00": {}}},
    {"models": {str(index): {} for index in range(101)}},
    {"regression": []},
    {"regression": {"unknown": 1}},
    {"regression": {"recent_sessions": 0}},
    {"regression": {"max_total_tokens_percent": -1}},
    {"regression": {"currency": "\x00"}},
])
def test_invalid_policy_shapes_fail_closed(tmp_path: Path, payload: object) -> None:
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.parent.mkdir()
    policy.write_text(json.dumps(payload), encoding="utf-8")

    report = telemetry_gate(tmp_path)

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "INVALID_TELEMETRY_POLICY"


@pytest.mark.parametrize(("provider", "version", "source_payload"), [
    ("invalid", "v1", {"models": {"default": {}}}),
    ("generic", "bad/version", {"models": {"default": {}}}),
    ("generic", "v1", []),
    ("generic", "v1", {"currency": "\x00", "models": {"default": {}}}),
    ("generic", "v1", {"models": {}}),
    ("generic", "v1", {"models": {"\x00": {}}}),
    ("generic", "v1", {"models": {"default": {"unknown": 1}}}),
    ("generic", "v1", {"models": {"default": {"input_per_million": 1}}}),
    ("generic", "v1", {"models": {"default": {
        "input_per_million": -1, "output_per_million": 1,
    }}}),
])
def test_invalid_pricing_inputs_fail_closed(
    tmp_path: Path, provider: str, version: str, source_payload: object
) -> None:
    source = tmp_path / "pricing.json"
    source.write_text(json.dumps(source_payload), encoding="utf-8")

    report = import_pricing_snapshot(
        tmp_path, source, provider=provider, version=version
    )

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "INVALID_PRICING_SNAPSHOT"


def test_cost_budget_and_cost_regression_are_enforced(tmp_path: Path) -> None:
    source = tmp_path / "pricing.json"
    source.write_text(json.dumps({
        "currency": "USD",
        "models": {"model-a": {"input_per_million": 1, "output_per_million": 2}},
    }), encoding="utf-8")
    assert import_pricing_snapshot(
        tmp_path, source, provider="generic", version="cost-gate"
    ).status == "success"
    for request_id, tokens in (("base-1", 100), ("base-2", 100),
                               ("recent-1", 300), ("recent-2", 300)):
        _record(tmp_path, request_id, tokens)
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.write_text(json.dumps({
        "limits": {"max_estimated_costs": {"USD": 0.0005}},
        "regression": {
            "recent_sessions": 2,
            "min_baseline_sessions": 2,
            "max_estimated_cost_percent": 50,
            "currency": "USD",
        },
    }), encoding="utf-8")

    report = telemetry_gate(tmp_path)
    codes = {item["code"] for item in report.summary["violations"]}

    assert report.status == "failed"
    assert "TELEMETRY_COST_BUDGET_EXCEEDED" in codes
    assert "TELEMETRY_REGRESSION_EXCEEDED" in codes


@pytest.mark.parametrize(("provider", "version"), [
    ("invalid", "v1"),
    ("generic", "bad/version"),
    ("generic", "missing"),
])
def test_activate_invalid_snapshot_fails_closed(
    tmp_path: Path, provider: str, version: str
) -> None:
    report = activate_pricing_snapshot(tmp_path, provider=provider, version=version)

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "INVALID_PRICING_SNAPSHOT"


def test_cost_budget_fails_when_any_session_lacks_pricing(tmp_path: Path) -> None:
    _record(tmp_path, "unpriced", 100)
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.parent.mkdir()
    policy.write_text(json.dumps({
        "limits": {"max_estimated_costs": {"USD": 1.0}}
    }), encoding="utf-8")

    report = telemetry_gate(tmp_path)

    assert report.status == "failed"
    assert report.summary["violations"][0]["code"] == "TELEMETRY_COST_DATA_MISSING"


def test_record_usage_returns_active_policy_alert(tmp_path: Path) -> None:
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.parent.mkdir()
    policy.write_text(json.dumps({"limits": {"max_total_tokens": 5}}), encoding="utf-8")

    stored = record_usage(
        tmp_path, client="generic", request_id="over-budget",
        input_tokens=10, output_tokens=1,
    )

    assert stored["policy"]["passed"] is False
    assert stored["policy"]["violations"][0]["code"] == "TELEMETRY_BUDGET_EXCEEDED"
