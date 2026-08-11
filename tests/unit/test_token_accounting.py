from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_dev_tools.context.tokens import (
    apply_token_accounting,
    parse_token_budgets,
    token_counter,
)


def _summary() -> dict[str, Any]:
    return {
        "selected_files": [
            {"path": "src/app.py", "content": "abcdefgh" * 10, "chars": 80},
            {"path": "tests/test_app.py", "content": "test data" * 10, "chars": 90},
        ],
        "diffs": [{"name": "unstaged", "content": "+changed\n" * 20}],
        "latest_errors": [{"first_failure": "one"}, {"first_failure": "two"}],
        "repository_map": {"tests": ["tests/test_app.py", "tests/test_other.py"]},
        "recent_commits": [{"subject": "one"}, {"subject": "two"}],
    }


def test_estimated_accounting_enforces_independent_content_budgets(tmp_path: Path) -> None:
    summary = _summary()

    accounting = apply_token_accounting(
        tmp_path,
        summary,
        "estimate",
        ("source=5", "tests=4", "diffs=3", "logs=5", "maps=6", "history=5"),
        None,
    )

    assert accounting["exact"] is False
    assert accounting["method"] == "utf8_bytes_divided_by_4"
    categories = accounting["categories"]
    for name in ("source", "tests", "diffs", "logs", "maps", "history"):
        assert categories[name]["tokens"] <= categories[name]["budget_tokens"]
        assert categories[name]["truncated"] is True
    assert summary["selected_files"][0]["token_budget_truncated"] is True
    assert accounting["provider_usage"]["available"] is False


def test_provider_usage_normalizes_openai_and_anthropic_fields(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    usage.write_text(
        json.dumps(
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 70,
                "cache_creation_input_tokens": 10,
                "input_tokens_details": {"cached_tokens": 60},
            }
        ),
        encoding="utf-8",
    )

    accounting = apply_token_accounting(
        tmp_path, _summary(), "estimate", ("cached_input=50", "output=25"), usage
    )

    assert accounting["provider_usage"]["cached_input_tokens"] == 70
    assert accounting["provider_usage"]["cache_write_tokens"] == 10
    assert accounting["budget_violations"] == ["cached_input"]


def test_exact_tokenizer_is_optional_and_reports_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr("ai_dev_tools.context.tokens.importlib.import_module", missing)
    counter = token_counter("o200k_base")

    assert counter.exact is False
    assert counter.used == "estimate"
    assert counter.fallback_reason == "TOKENIZER_UNAVAILABLE"


def test_exact_tokenizer_uses_selected_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    class Encoding:
        def encode(self, text: str) -> list[str]:
            return text.split()

    class Module:
        @staticmethod
        def get_encoding(name: str) -> Encoding:
            assert name == "cl100k_base"
            return Encoding()

    monkeypatch.setattr(
        "ai_dev_tools.context.tokens.importlib.import_module", lambda name: Module()
    )
    counter = token_counter("cl100k_base")

    assert counter.exact is True
    assert counter.count("one two three") == 3


def test_token_inputs_reject_invalid_budgets_tokenizers_and_external_usage(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="invalid token budget"):
        parse_token_budgets(("unknown=1",))
    with pytest.raises(ValueError, match="invalid token budget"):
        parse_token_budgets(("source=-1",))
    with pytest.raises(ValueError, match="invalid token budget"):
        parse_token_budgets(("source=1", "source=2"))
    with pytest.raises(ValueError, match="unknown tokenizer"):
        token_counter("unknown")
    outside = tmp_path.parent / "usage-outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="inside project root"):
        apply_token_accounting(tmp_path, _summary(), "estimate", (), outside)
