from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Artifact, Issue, Report

CLIENTS = {"codex", "claude", "cursor", "generic"}
FORMATS = {"auto", "openai", "anthropic", "generic"}
MAX_IMPORT_BYTES = 5_000_000
MAX_TOKENS = 10_000_000_000


def import_usage(
    project_root: Path,
    input_path: Path,
    *,
    client: str,
    format_name: str = "auto",
    pricing_path: Path | None = None,
) -> Report:
    root = project_root.resolve()
    report = Report(command="telemetry import", project_root=root)
    try:
        path = _local_file(root, input_path, "telemetry input")
        raw = path.read_bytes()
        if len(raw) > MAX_IMPORT_BYTES:
            raise ValueError(f"telemetry input exceeds {MAX_IMPORT_BYTES} bytes")
        records = _decode_records(raw)
        usage = normalize_records(records, client=client, format_name=format_name)
        source_id = hashlib.sha256(raw).hexdigest()
        stored = record_usage(
            root,
            client=client,
            input_tokens=usage["input_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            cache_write_input_tokens=usage["cache_write_input_tokens"],
            output_tokens=usage["output_tokens"],
            reasoning_tokens=usage["reasoning_tokens"],
            model=usage.get("model", ""),
            request_id=usage.get("request_id", ""),
            source=f"import:{format_name}",
            source_id=source_id,
            pricing_path=pricing_path,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_TELEMETRY", "message": str(exc)}
        report.issues.append(Issue("error", str(exc), code="INVALID_TELEMETRY"))
        return report
    stored_path = Path(stored["path"])
    stored["path"] = str(stored_path)
    report.summary = stored
    policy = stored.get("policy")
    if isinstance(policy, dict) and policy.get("passed") is False:
        report.status = "partial"
        report.issues.append(
            Issue("warning", "Telemetry policy has active violations", code="TELEMETRY_ALERT")
        )
    report.artifacts.append(Artifact(str(stored_path), "telemetry", "Normalized usage"))
    return report


def record_usage(
    project_root: Path,
    *,
    client: str,
    input_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
    output_tokens: int,
    reasoning_tokens: int = 0,
    model: str = "",
    request_id: str = "",
    source: str = "client_reported",
    source_id: str = "",
    pricing_path: Path | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    if client not in CLIENTS:
        raise ValueError(f"unknown AI client: {client}")
    values = {
        "input_tokens": _token(input_tokens, "input_tokens"),
        "cached_input_tokens": _token(cached_input_tokens, "cached_input_tokens"),
        "cache_write_input_tokens": _token(
            cache_write_input_tokens, "cache_write_input_tokens"
        ),
        "output_tokens": _token(output_tokens, "output_tokens"),
        "reasoning_tokens": _token(reasoning_tokens, "reasoning_tokens"),
    }
    if (
        values["cached_input_tokens"] + values["cache_write_input_tokens"]
        > values["input_tokens"]
    ):
        raise ValueError("cached and cache-write input cannot exceed input_tokens")
    model = _bounded_text(model, "model", 200)
    request_id = _bounded_text(request_id, "request_id", 200)
    recorded_at = datetime.now(UTC).isoformat()
    identity = source_id or request_id or recorded_at
    session_id = hashlib.sha256(
        json.dumps([client, identity, model, values], sort_keys=True).encode()
    ).hexdigest()[:24]
    payload: dict[str, Any] = {
        "schema_version": "1",
        "session_id": session_id,
        "recorded_at": recorded_at,
        "client": client,
        "model": model or None,
        "request_id": request_id or None,
        "source": source,
        "measurement": "provider_reported",
        **values,
        "total_tokens": values["input_tokens"] + values["output_tokens"],
    }
    pricing = _load_pricing(root, pricing_path)
    cost = _estimate_cost(payload, pricing)
    if cost:
        payload["cost"] = cost
    directory = root / ".ai" / "token-efficiency"
    path = directory / "sessions" / f"{session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = directory / "latest-session.json"
    latest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    from ai_dev_tools.telemetry_policy import optional_policy_status

    return {**payload, "path": path, "policy": optional_policy_status(root)}


def telemetry_status(project_root: Path) -> Report:
    root = project_root.resolve()
    report = Report(command="telemetry status", project_root=root)
    from ai_dev_tools.telemetry_policy import optional_policy_status

    report.summary = {**aggregate_usage(root), "policy": optional_policy_status(root)}
    return report


def aggregate_usage(project_root: Path) -> dict[str, Any]:
    rows = load_session_rows(project_root)
    by_client: dict[str, dict[str, int]] = {}
    costs: dict[str, float] = {}
    for row in rows:
        client = str(row.get("client", "generic"))
        bucket = by_client.setdefault(
            client, {"sessions": 0, "input_tokens": 0, "cached_input_tokens": 0,
                     "cache_write_input_tokens": 0, "output_tokens": 0,
                     "reasoning_tokens": 0}
        )
        bucket["sessions"] += 1
        for key in (
            "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_tokens",
        ):
            bucket[key] += _safe_int(row.get(key))
        cost = row.get("cost")
        if isinstance(cost, dict):
            currency = cost.get("currency")
            amount = cost.get("estimated_amount")
            if isinstance(currency, str) and isinstance(amount, int | float):
                costs[currency] = round(costs.get(currency, 0.0) + float(amount), 8)
    return {
        "sessions": len(rows),
        "measurement": "provider_reported",
        "input_tokens": sum(item["input_tokens"] for item in by_client.values()),
        "cached_input_tokens": sum(item["cached_input_tokens"] for item in by_client.values()),
        "cache_write_input_tokens": sum(
            item["cache_write_input_tokens"] for item in by_client.values()
        ),
        "output_tokens": sum(item["output_tokens"] for item in by_client.values()),
        "reasoning_tokens": sum(item["reasoning_tokens"] for item in by_client.values()),
        "by_client": by_client,
        "estimated_costs": costs,
        "retention_limit": 1000,
    }


def load_session_rows(project_root: Path, limit: int = 1000) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("session limit must be an integer from 1 to 1000")
    directory = project_root.resolve() / ".ai" / "token-efficiency" / "sessions"
    if not directory.exists():
        return []
    candidates = sorted(
        directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
    )[: max(limit * 2, 1000)]
    rows: list[dict[str, Any]] = []
    for path in candidates:
        if path.stat().st_size > 100_000:
            continue
        row = _read_object(path)
        recorded_at = row.get("recorded_at")
        if row.get("measurement") == "provider_reported" and isinstance(recorded_at, str):
            try:
                datetime.fromisoformat(recorded_at)
            except ValueError:
                continue
            rows.append(row)
    rows.sort(key=lambda item: str(item["recorded_at"]))
    return rows[-limit:]


def normalize_records(
    records: list[dict[str, Any]], *, client: str, format_name: str
) -> dict[str, Any]:
    if client not in CLIENTS or format_name not in FORMATS:
        raise ValueError("unsupported telemetry client or format")
    if not records:
        raise ValueError("telemetry input contains no JSON objects")
    chosen = format_name
    if chosen == "auto":
        chosen = _detect_format(records)
    normalized: list[dict[str, Any]] = []
    for record in records:
        item = _normalize_one(record, chosen)
        if item is not None:
            normalized.append(item)
    if not normalized:
        raise ValueError("no complete usage object found")
    deduplicated: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for item in normalized:
        identifier = str(item.get("request_id", ""))
        if identifier:
            deduplicated[identifier] = item
        else:
            anonymous.append(item)
    rows = [*deduplicated.values(), *anonymous]
    return {
        "input_tokens": sum(_safe_int(item.get("input_tokens")) for item in rows),
        "cached_input_tokens": sum(_safe_int(item.get("cached_input_tokens")) for item in rows),
        "cache_write_input_tokens": sum(
            _safe_int(item.get("cache_write_input_tokens")) for item in rows
        ),
        "output_tokens": sum(_safe_int(item.get("output_tokens")) for item in rows),
        "reasoning_tokens": sum(_safe_int(item.get("reasoning_tokens")) for item in rows),
        "model": _common_value(rows, "model"),
        "request_id": _common_value(rows, "request_id"),
    }


def _normalize_one(payload: dict[str, Any], format_name: str) -> dict[str, Any] | None:
    container = payload
    if isinstance(payload.get("response"), dict):
        container = payload["response"]
    if isinstance(container.get("body"), dict):
        container = container["body"]
    usage = container.get("usage")
    if not isinstance(usage, dict):
        return None
    if format_name == "anthropic":
        cached = _safe_int(usage.get("cache_read_input_tokens"))
        cache_write = _safe_int(usage.get("cache_creation_input_tokens"))
        input_tokens = _token(usage.get("input_tokens", 0), "input_tokens")
        input_tokens += cached + cache_write
    elif format_name == "openai":
        details = usage.get("input_tokens_details", {})
        cached = _safe_int(details.get("cached_tokens")) if isinstance(details, dict) else 0
        cache_write = (
            _safe_int(details.get("cache_write_tokens")) if isinstance(details, dict) else 0
        )
        input_tokens = _token(usage.get("input_tokens", 0), "input_tokens")
    else:
        cached = _safe_int(usage.get("cached_input_tokens"))
        cache_write = _safe_int(usage.get("cache_write_input_tokens"))
        input_tokens = _token(usage.get("input_tokens", 0), "input_tokens")
    output_details = usage.get("output_tokens_details", {})
    reasoning = _safe_int(usage.get("reasoning_tokens"))
    if isinstance(output_details, dict) and "reasoning_tokens" in output_details:
        reasoning = _safe_int(output_details.get("reasoning_tokens"))
    result: dict[str, Any] = {
        "input_tokens": _token(input_tokens, "input_tokens"),
        "cached_input_tokens": _token(cached, "cached_input_tokens"),
        "cache_write_input_tokens": _token(cache_write, "cache_write_input_tokens"),
        "output_tokens": _token(usage.get("output_tokens", 0), "output_tokens"),
        "reasoning_tokens": _token(reasoning, "reasoning_tokens"),
        "model": str(container.get("model", payload.get("model", "")))[:200],
        "request_id": str(container.get("id", payload.get("request_id", "")))[:200],
    }
    if result["cached_input_tokens"] + result["cache_write_input_tokens"] > result["input_tokens"]:
        raise ValueError("cached and cache-write input exceed input tokens")
    return result


def _detect_format(records: list[dict[str, Any]]) -> str:
    encoded = json.dumps(records[:20], sort_keys=True)
    if "input_tokens_details" in encoded:
        return "openai"
    if "cache_read_input_tokens" in encoded or "cache_creation_input_tokens" in encoded:
        return "anthropic"
    if "cached_input_tokens" in encoded or "cache_write_input_tokens" in encoded:
        return "generic"
    raise ValueError("auto format is ambiguous; specify --format")


def _decode_records(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = value if isinstance(value, list) else [value]
    if any(not isinstance(item, dict) for item in values):
        raise ValueError("telemetry records must be JSON objects")
    return values


def _load_pricing(root: Path, path: Path | None) -> dict[str, Any]:
    candidate = path or Path(".ai-dev/telemetry-pricing.json")
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.exists() and path is None:
        return {}
    resolved = _local_file(root, resolved, "pricing configuration")
    if resolved.stat().st_size > 100_000:
        raise ValueError("pricing configuration is too large")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pricing configuration must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("pricing configuration must be a JSON object")
    active = value.get("active_snapshot")
    if active is not None:
        expected_sha = value.get("sha256")
        if not isinstance(active, str) or not active or "\x00" in active:
            raise ValueError("active_snapshot must be a project-relative path")
        snapshot = _local_file(root, Path(active), "active pricing snapshot")
        if snapshot.stat().st_size > 100_000:
            raise ValueError("active pricing snapshot is too large")
        try:
            value = json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("active pricing snapshot must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("active pricing snapshot must be a JSON object")
        snapshot_core = {
            key: value.get(key)
            for key in (
                "schema_version",
                "provider",
                "version",
                "source",
                "currency",
                "models",
            )
        }
        actual_sha = hashlib.sha256(
            json.dumps(snapshot_core, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if (
            not isinstance(expected_sha, str)
            or value.get("sha256") != expected_sha
            or actual_sha != expected_sha
        ):
            raise ValueError("active pricing snapshot integrity check failed")
    return value


def _estimate_cost(usage: dict[str, Any], pricing: dict[str, Any]) -> dict[str, Any]:
    if not pricing:
        return {}
    models = pricing.get("models")
    if not isinstance(models, dict):
        raise ValueError("pricing configuration requires a models object")
    model = usage.get("model")
    rates = models.get(model) if isinstance(model, str) else None
    if not isinstance(rates, dict):
        rates = models.get("default")
    if not isinstance(rates, dict):
        return {}
    input_rate = _rate(rates.get("input_per_million"), "input_per_million")
    cached_rate = _rate(rates.get("cached_input_per_million", input_rate),
                        "cached_input_per_million")
    cache_write_rate = _rate(
        rates.get("cache_write_input_per_million", input_rate),
        "cache_write_input_per_million",
    )
    output_rate = _rate(rates.get("output_per_million"), "output_per_million")
    cached = _safe_int(usage.get("cached_input_tokens"))
    cache_write = _safe_int(usage.get("cache_write_input_tokens"))
    uncached = _safe_int(usage.get("input_tokens")) - cached - cache_write
    amount = (
        uncached * input_rate + cached * cached_rate + cache_write * cache_write_rate
        + _safe_int(usage.get("output_tokens")) * output_rate
    ) / 1_000_000
    currency = pricing.get("currency", "USD")
    if not isinstance(currency, str) or not 1 <= len(currency) <= 10:
        raise ValueError("pricing currency must be a short string")
    return {
        "estimated_amount": round(amount, 8),
        "currency": currency,
        "kind": "local_pricing_estimate",
        "pricing_provider": pricing.get("provider"),
        "pricing_version": pricing.get("version"),
        "pricing_sha256": pricing.get("sha256"),
    }


def _local_file(root: Path, path: Path, label: str) -> Path:
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"{label} must be an existing file inside the project")
    return resolved


def _token(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_TOKENS:
        raise ValueError(f"{name} must be an integer from 0 to {MAX_TOKENS}")
    return value


def _rate(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _bounded_text(value: str, name: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{name} must be a string up to {maximum} characters")
    return value


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _common_value(rows: list[dict[str, Any]], key: str) -> str:
    values = {str(row.get(key, "")) for row in rows if row.get(key)}
    return values.pop() if len(values) == 1 else ""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
