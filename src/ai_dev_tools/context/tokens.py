from __future__ import annotations

import importlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATEGORIES = ("source", "diffs", "tests", "logs", "maps", "history", "cached_input", "output")


@dataclass(frozen=True, slots=True)
class TokenCounter:
    requested: str
    used: str
    method: str
    exact: bool
    fallback_reason: str | None
    count: Callable[[str], int]


def apply_token_accounting(
    root: Path,
    summary: dict[str, Any],
    tokenizer: str,
    budget_specs: tuple[str, ...],
    provider_usage_path: Path | None,
) -> dict[str, Any]:
    budgets = parse_token_budgets(budget_specs)
    counter = token_counter(tokenizer)
    originals = _category_texts(summary)
    truncated = _enforce_content_budgets(summary, budgets, counter)
    texts = _category_texts(summary)
    provider = _provider_usage(root, provider_usage_path)
    categories: dict[str, dict[str, object]] = {}
    for category in CATEGORIES:
        if category == "cached_input":
            tokens = _integer(provider.get("cached_input_tokens"))
            original = tokens
            chars = 0
            size = 0
        elif category == "output":
            tokens = _integer(provider.get("output_tokens"))
            original = tokens
            chars = 0
            size = 0
        else:
            text = texts[category]
            tokens = counter.count(text)
            original = counter.count(originals[category])
            chars = len(text)
            size = len(text.encode("utf-8"))
        budget = budgets.get(category)
        categories[category] = {
            "chars": chars,
            "utf8_bytes": size,
            "tokens": tokens,
            "original_tokens": original,
            "budget_tokens": budget,
            "truncated": category in truncated,
            "within_budget": budget is None or tokens <= budget,
        }
    violations = [
        category for category, data in categories.items() if data["within_budget"] is False
    ]
    return {
        "tokenizer_requested": counter.requested,
        "tokenizer_used": counter.used,
        "method": counter.method,
        "exact": counter.exact,
        "fallback_reason": counter.fallback_reason,
        "categories": categories,
        "input_tokens": sum(
            _integer(categories[name].get("tokens"))
            for name in ("source", "diffs", "tests", "logs", "maps", "history")
        ),
        "provider_usage": provider,
        "budget_violations": violations,
    }


def parse_token_budgets(specs: tuple[str, ...]) -> dict[str, int]:
    budgets: dict[str, int] = {}
    for spec in specs:
        name, separator, raw = spec.partition("=")
        if separator != "=" or name not in CATEGORIES:
            raise ValueError(f"invalid token budget: {spec}")
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"invalid token budget: {spec}") from exc
        if value < 0 or name in budgets:
            raise ValueError(f"invalid token budget: {spec}")
        budgets[name] = value
    return budgets


def token_counter(requested: str) -> TokenCounter:
    if requested == "estimate":
        return TokenCounter(
            requested, "estimate", "utf8_bytes_divided_by_4", False, None, _estimate
        )
    if requested not in {"cl100k_base", "o200k_base"}:
        raise ValueError(f"unknown tokenizer: {requested}")
    try:
        module = importlib.import_module("tiktoken")
        encoding = module.get_encoding(requested)
    except (ImportError, AttributeError, KeyError):
        return TokenCounter(
            requested,
            "estimate",
            "utf8_bytes_divided_by_4",
            False,
            "TOKENIZER_UNAVAILABLE",
            _estimate,
        )
    return TokenCounter(
        requested,
        requested,
        f"tiktoken:{requested}",
        True,
        None,
        lambda text: len(encoding.encode(text)),
    )


def _enforce_content_budgets(
    summary: dict[str, Any], budgets: dict[str, int], counter: TokenCounter
) -> set[str]:
    truncated: set[str] = set()
    selected = summary.get("selected_files")
    if isinstance(selected, list):
        for category in ("source", "tests"):
            items = [
                item
                for item in selected
                if isinstance(item, dict) and _file_category(str(item.get("path", ""))) == category
            ]
            if category in budgets and _limit_content_items(items, budgets[category], counter):
                truncated.add(category)
    diffs = summary.get("diffs")
    if "diffs" in budgets and isinstance(diffs, list):
        items = [item for item in diffs if isinstance(item, dict)]
        if _limit_content_items(items, budgets["diffs"], counter):
            truncated.add("diffs")
    for category, key in (("logs", "latest_errors"), ("history", "recent_commits")):
        value = summary.get(key)
        if category in budgets and isinstance(value, list):
            kept = _fit_values(value, budgets[category], counter)
            if len(kept) < len(value):
                summary[key] = kept
                truncated.add(category)
    repository_map = summary.get("repository_map")
    if "maps" in budgets and isinstance(repository_map, dict):
        flat = [(key, item) for key in sorted(repository_map) for item in repository_map[key]]
        kept_pairs = _fit_values(flat, budgets["maps"], counter)
        if len(kept_pairs) < len(flat):
            summary["repository_map"] = {
                key: [item for item_key, item in kept_pairs if item_key == key]
                for key in sorted(repository_map)
            }
            truncated.add("maps")
    return truncated


def _limit_content_items(items: list[dict[str, Any]], budget: int, counter: TokenCounter) -> bool:
    remaining = budget
    truncated = False
    for item in items:
        content = str(item.get("content", ""))
        tokens = counter.count(content)
        if tokens <= remaining:
            remaining -= tokens
            continue
        item["content"] = _prefix_within(content, remaining, counter)
        item["chars"] = len(str(item["content"]))
        item["truncated"] = True
        item["omitted_content"] = True
        item["token_budget_truncated"] = True
        remaining = 0
        truncated = True
    return truncated


def _prefix_within(text: str, budget: int, counter: TokenCounter) -> str:
    if budget <= 0:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if counter.count(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _fit_values(values: list[Any], budget: int, counter: TokenCounter) -> list[Any]:
    kept: list[Any] = []
    for value in values:
        candidate = [*kept, value]
        if counter.count(json.dumps(candidate, sort_keys=True, default=str)) > budget:
            break
        kept.append(value)
    return kept


def _category_texts(summary: dict[str, Any]) -> dict[str, str]:
    selected = summary.get("selected_files", [])
    files = (
        [item for item in selected if isinstance(item, dict)] if isinstance(selected, list) else []
    )
    return {
        "source": "\n".join(
            str(item.get("content", ""))
            for item in files
            if _file_category(str(item.get("path", ""))) == "source"
        ),
        "tests": "\n".join(
            str(item.get("content", ""))
            for item in files
            if _file_category(str(item.get("path", ""))) == "tests"
        ),
        "diffs": "\n".join(
            str(item.get("content", ""))
            for item in summary.get("diffs", [])
            if isinstance(item, dict)
        ),
        "logs": _json(summary.get("latest_errors", [])),
        "maps": _json(summary.get("repository_map", {})),
        "history": _json(summary.get("recent_commits", [])),
    }


def _provider_usage(root: Path, path: Path | None) -> dict[str, object]:
    empty: dict[str, object] = {
        "available": False,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
    }
    if path is None:
        return empty
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("provider usage file must be inside project root") from exc
    if resolved.stat().st_size > 64_000:
        raise ValueError("provider usage file is too large")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider usage must be a JSON object")
    details = payload.get("input_tokens_details", {})
    details = details if isinstance(details, dict) else {}
    values = {
        "input_tokens": payload.get("input_tokens", 0),
        "cached_input_tokens": payload.get(
            "cache_read_input_tokens", details.get("cached_tokens", 0)
        ),
        "cache_write_tokens": payload.get("cache_creation_input_tokens", 0),
        "output_tokens": payload.get("output_tokens", 0),
    }
    if any(not isinstance(value, int) or value < 0 for value in values.values()):
        raise ValueError("provider usage token values must be non-negative integers")
    return {"available": True, "source": resolved.relative_to(root.resolve()).as_posix(), **values}


def _file_category(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    name = Path(normalized).name
    return (
        "tests"
        if normalized.startswith("tests/") or name.startswith("test_") or ".test." in name
        else "source"
    )


def _estimate(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 4)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0
