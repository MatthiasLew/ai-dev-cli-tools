from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.telemetry import aggregate_usage, import_usage, normalize_records, record_usage


def test_openai_response_usage_is_normalized_and_priced(tmp_path: Path) -> None:
    source = tmp_path / "response.json"
    source.write_text(json.dumps({
        "id": "resp_1", "model": "gpt-test", "usage": {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 600},
            "output_tokens": 200,
            "output_tokens_details": {"reasoning_tokens": 80},
        }
    }), encoding="utf-8")
    pricing = tmp_path / ".ai-dev/telemetry-pricing.json"
    pricing.parent.mkdir()
    pricing.write_text(json.dumps({
        "currency": "USD", "models": {"gpt-test": {
            "input_per_million": 2.0,
            "cached_input_per_million": 0.5,
            "output_per_million": 8.0,
        }}
    }), encoding="utf-8")

    report = import_usage(tmp_path, source, client="codex", format_name="openai")

    assert report.status == "success"
    assert report.summary["measurement"] == "provider_reported"
    assert report.summary["reasoning_tokens"] == 80
    assert report.summary["cost"]["estimated_amount"] == 0.0027
    assert aggregate_usage(tmp_path)["input_tokens"] == 1000


def test_anthropic_and_generic_usage_are_normalized() -> None:
    anthropic = normalize_records([{"id": "msg_1", "model": "claude-test", "usage": {
        "input_tokens": 500, "cache_read_input_tokens": 300,
        "cache_creation_input_tokens": 100, "output_tokens": 40,
    }}], client="claude", format_name="auto")
    generic = normalize_records([{"usage": {
        "input_tokens": 12, "cached_input_tokens": 3,
        "output_tokens": 5, "reasoning_tokens": 2,
    }}], client="cursor", format_name="generic")

    assert anthropic["cache_write_input_tokens"] == 100
    assert anthropic["cached_input_tokens"] == 300
    assert anthropic["input_tokens"] == 900
    assert generic["reasoning_tokens"] == 2


def test_jsonl_deduplicates_provider_response_ids(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    event = {"type": "response.completed", "response": {"id": "resp_1", "usage": {
        "input_tokens": 10, "input_tokens_details": {"cached_tokens": 4},
        "output_tokens": 3,
    }}}
    source.write_text(json.dumps(event) + "\n" + json.dumps(event) + "\n", encoding="utf-8")

    report = import_usage(tmp_path, source, client="codex", format_name="auto")

    assert report.summary["input_tokens"] == 10
    assert report.summary["output_tokens"] == 3


def test_import_rejects_ambiguous_outside_and_invalid_usage(tmp_path: Path) -> None:
    ambiguous = tmp_path / "ambiguous.json"
    ambiguous.write_text(json.dumps({"usage": {"input_tokens": 1, "output_tokens": 1}}))
    assert import_usage(tmp_path, ambiguous, client="generic").status == "invalid_configuration"

    outside = tmp_path.parent / "outside-telemetry.json"
    outside.write_text(json.dumps({"usage": {"input_tokens": 1}}))
    try:
        assert import_usage(tmp_path, outside, client="generic", format_name="generic").status == (
            "invalid_configuration"
        )
    finally:
        outside.unlink()

    try:
        record_usage(tmp_path, client="generic", input_tokens=1,
                     cached_input_tokens=2, output_tokens=0)
    except ValueError as exc:
        assert "cannot exceed" in str(exc)
    else:
        raise AssertionError("invalid cache accounting was accepted")


def test_reimport_is_idempotent_by_source_content(tmp_path: Path) -> None:
    source = tmp_path / "usage.json"
    source.write_text(json.dumps({"usage": {
        "input_tokens": 7, "cached_input_tokens": 2, "output_tokens": 3,
    }}))

    import_usage(tmp_path, source, client="cursor", format_name="generic")
    import_usage(tmp_path, source, client="cursor", format_name="generic")

    assert aggregate_usage(tmp_path)["sessions"] == 1


def test_cache_write_has_distinct_local_pricing_rate(tmp_path: Path) -> None:
    pricing = tmp_path / ".ai-dev/pricing.json"
    pricing.parent.mkdir()
    pricing.write_text(json.dumps({"currency": "USD", "models": {"default": {
        "input_per_million": 2.0,
        "cached_input_per_million": 0.5,
        "cache_write_input_per_million": 2.5,
        "output_per_million": 8.0,
    }}}), encoding="utf-8")

    stored = record_usage(
        tmp_path, client="claude", input_tokens=900, cached_input_tokens=300,
        cache_write_input_tokens=100, output_tokens=40, pricing_path=pricing,
    )

    assert stored["cost"]["estimated_amount"] == 0.00172


def test_explicit_invalid_pricing_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "usage.json"
    source.write_text(json.dumps({"usage": {
        "input_tokens": 7, "cached_input_tokens": 2, "output_tokens": 3,
    }}))
    pricing = tmp_path / "pricing.json"
    pricing.write_text("not-json", encoding="utf-8")

    report = import_usage(
        tmp_path, source, client="generic", format_name="generic", pricing_path=pricing
    )

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "INVALID_TELEMETRY"
