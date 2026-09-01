from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.telemetry import load_session_rows

MAX_POLICY_BYTES = 250_000
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PROVIDERS = {"openai", "anthropic", "generic"}
TOKEN_METRICS = ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")
LIMIT_KEYS = {f"max_{metric}" for metric in TOKEN_METRICS} | {
    "max_sessions",
    "max_estimated_costs",
}


def telemetry_gate(project_root: Path, policy_path: Path | None = None) -> Report:
    root = project_root.resolve()
    report = Report(command="telemetry gate", project_root=root)
    try:
        policy = load_policy(root, policy_path, required=True)
        evaluation = evaluate_policy(root, policy)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_TELEMETRY_POLICY", "message": str(exc)}
        report.issues.append(
            Issue("error", str(exc), code="INVALID_TELEMETRY_POLICY")
        )
        return report
    report.summary = evaluation
    if not evaluation["passed"]:
        report.status = "failed"
        for violation in evaluation["violations"]:
            report.issues.append(
                Issue(
                    "error",
                    str(violation["message"]),
                    code=str(violation["code"]),
                )
            )
    return report


def optional_policy_status(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    path = root / ".ai-dev" / "telemetry-budgets.json"
    if not path.exists():
        return {"configured": False, "passed": True, "violations": [], "alerts": []}
    try:
        policy = load_policy(root, path, required=True)
        return {"configured": True, **evaluate_policy(root, policy)}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "configured": True,
            "passed": False,
            "violations": [
                {
                    "code": "INVALID_TELEMETRY_POLICY",
                    "scope": "policy",
                    "metric": "configuration",
                    "message": str(exc),
                }
            ],
            "alerts": [],
        }


def load_policy(root: Path, path: Path | None, *, required: bool) -> dict[str, Any]:
    candidate = path or Path(".ai-dev/telemetry-budgets.json")
    resolved = _project_file(root, candidate, "telemetry policy", required=required)
    if resolved is None:
        return {}
    policy = _strict_object(resolved, MAX_POLICY_BYTES, "telemetry policy")
    unknown = set(policy) - {
        "schema_version", "window_sessions", "limits", "clients", "models", "regression"
    }
    if unknown:
        raise ValueError(f"unknown telemetry policy fields: {', '.join(sorted(unknown))}")
    if policy.get("schema_version", "1") != "1":
        raise ValueError("telemetry policy schema_version must be 1")
    window = _bounded_int(policy.get("window_sessions", 100), "window_sessions", 1, 1000)
    normalized: dict[str, Any] = {
        "schema_version": "1",
        "window_sessions": window,
        "limits": _limits(policy.get("limits", {}), "global"),
        "clients": _scopes(policy.get("clients", {}), "clients"),
        "models": _scopes(policy.get("models", {}), "models"),
        "regression": _regression(policy.get("regression", {})),
    }
    return normalized


def evaluate_policy(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    rows = _session_rows(root)[-_bounded_int(
        policy.get("window_sessions", 100), "window_sessions", 1, 1000
    ):]
    violations: list[dict[str, Any]] = []
    _evaluate_limits(rows, policy.get("limits", {}), "global", violations)
    clients = policy.get("clients", {})
    if isinstance(clients, dict):
        for client, limits in clients.items():
            _evaluate_limits(
                [row for row in rows if row.get("client") == client],
                limits,
                f"client:{client}",
                violations,
            )
    models = policy.get("models", {})
    if isinstance(models, dict):
        for model, limits in models.items():
            _evaluate_limits(
                [row for row in rows if row.get("model") == model],
                limits,
                f"model:{model}",
                violations,
            )
    alerts = _regression_alerts(rows, policy.get("regression", {}))
    violations.extend(item for item in alerts if item.get("severity") == "error")
    return {
        "configured": True,
        "passed": not violations,
        "evaluated_sessions": len(rows),
        "window_sessions": policy.get("window_sessions", 100),
        "violations": violations,
        "alerts": alerts,
    }


def import_pricing_snapshot(
    project_root: Path,
    input_path: Path,
    *,
    provider: str,
    version: str,
    source: str = "",
    activate: bool = True,
) -> Report:
    root = project_root.resolve()
    report = Report(command="telemetry pricing import", project_root=root)
    try:
        if provider not in PROVIDERS:
            raise ValueError(f"provider must be one of: {', '.join(sorted(PROVIDERS))}")
        if not VERSION_PATTERN.fullmatch(version):
            raise ValueError(
                "version must contain 1-64 letters, digits, dots, dashes, or underscores"
            )
        if len(source) > 500 or "\x00" in source:
            raise ValueError("source must be at most 500 characters")
        input_file = _project_file(root, input_path, "pricing input", required=True)
        assert input_file is not None
        pricing = _validate_pricing(_strict_object(input_file, 100_000, "pricing input"))
        core = {
            "schema_version": "1",
            "provider": provider,
            "version": version,
            "source": source or None,
            "currency": pricing["currency"],
            "models": pricing["models"],
        }
        digest = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
        payload = {
            **core,
            "captured_at": datetime.now(UTC).isoformat(),
            "sha256": digest,
        }
        snapshot = root / ".ai-dev" / "pricing" / provider / f"{version}.json"
        if snapshot.exists():
            existing = _strict_object(snapshot, 100_000, "pricing snapshot")
            existing_core = {key: existing.get(key) for key in core}
            existing_digest = hashlib.sha256(
                json.dumps(existing_core, sort_keys=True).encode()
            ).hexdigest()
            if existing.get("sha256") != digest or existing_digest != digest:
                raise ValueError("pricing snapshot version already exists with different content")
            payload = existing
        else:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        active_path: Path | None = None
        if activate:
            active_path = root / ".ai-dev" / "telemetry-pricing.json"
            pointer = {
                "schema_version": "1",
                "active_snapshot": snapshot.relative_to(root).as_posix(),
                "provider": provider,
                "version": version,
                "sha256": digest,
            }
            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_path.write_text(
                json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_PRICING_SNAPSHOT", "message": str(exc)}
        report.issues.append(Issue("error", str(exc), code="INVALID_PRICING_SNAPSHOT"))
        return report
    report.summary = {
        "provider": provider,
        "version": version,
        "sha256": payload["sha256"],
        "snapshot": str(snapshot),
        "active": activate,
        "active_path": str(active_path) if active_path else None,
    }
    report.artifacts.append(Artifact(str(snapshot), "pricing-snapshot", "Versioned pricing"))
    if active_path:
        report.artifacts.append(Artifact(str(active_path), "pricing-pointer", "Active pricing"))
    return report


def activate_pricing_snapshot(project_root: Path, *, provider: str, version: str) -> Report:
    root = project_root.resolve()
    report = Report(command="telemetry pricing activate", project_root=root)
    try:
        if provider not in PROVIDERS:
            raise ValueError(f"provider must be one of: {', '.join(sorted(PROVIDERS))}")
        if not VERSION_PATTERN.fullmatch(version):
            raise ValueError("invalid pricing snapshot version")
        snapshot = root / ".ai-dev" / "pricing" / provider / f"{version}.json"
        payload = _strict_object(snapshot, 100_000, "pricing snapshot")
        if payload.get("provider") != provider or payload.get("version") != version:
            raise ValueError("pricing snapshot identity does not match its path")
        digest = payload.get("sha256")
        core = {key: payload.get(key) for key in (
            "schema_version", "provider", "version", "source", "currency", "models"
        )}
        expected = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
        if not isinstance(digest, str) or digest != expected:
            raise ValueError("pricing snapshot integrity check failed")
        active_path = root / ".ai-dev" / "telemetry-pricing.json"
        pointer = {
            "schema_version": "1",
            "active_snapshot": snapshot.relative_to(root).as_posix(),
            "provider": provider,
            "version": version,
            "sha256": digest,
        }
        active_path.write_text(
            json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_PRICING_SNAPSHOT", "message": str(exc)}
        report.issues.append(Issue("error", str(exc), code="INVALID_PRICING_SNAPSHOT"))
        return report
    report.summary = {
        "provider": provider,
        "version": version,
        "sha256": digest,
        "snapshot": str(snapshot),
        "active": True,
        "active_path": str(active_path),
    }
    report.artifacts.append(Artifact(str(active_path), "pricing-pointer", "Active pricing"))
    return report


def _evaluate_limits(
    rows: list[dict[str, Any]],
    limits: object,
    scope: str,
    violations: list[dict[str, Any]],
) -> None:
    if not isinstance(limits, dict):
        return
    actuals = {metric: sum(_safe_int(row.get(metric)) for row in rows) for metric in TOKEN_METRICS}
    actuals["sessions"] = len(rows)
    for metric in (*TOKEN_METRICS, "sessions"):
        key = f"max_{metric}"
        limit = limits.get(key)
        if isinstance(limit, int) and actuals[metric] > limit:
            violations.append(_violation("TELEMETRY_BUDGET_EXCEEDED", scope, metric,
                                         actuals[metric], limit))
    cost_limits = limits.get("max_estimated_costs", {})
    if isinstance(cost_limits, dict):
        actual_costs = _costs(rows)
        for currency, limit in cost_limits.items():
            missing = sum(1 for row in rows if not _has_cost(row, currency))
            if missing:
                violations.append({
                    "code": "TELEMETRY_COST_DATA_MISSING",
                    "severity": "error",
                    "scope": scope,
                    "metric": f"estimated_cost:{currency}",
                    "missing_sessions": missing,
                    "message": f"{scope} has {missing} sessions without {currency} cost",
                })
                continue
            actual = actual_costs.get(currency, 0.0)
            if isinstance(limit, int | float) and actual > float(limit):
                violations.append(_violation("TELEMETRY_COST_BUDGET_EXCEEDED", scope,
                                             f"estimated_cost:{currency}", actual, limit))


def _regression_alerts(rows: list[dict[str, Any]], config: object) -> list[dict[str, Any]]:
    if not isinstance(config, dict) or not config:
        return []
    size = _bounded_int(config.get("recent_sessions", 5), "recent_sessions", 1, 100)
    minimum = _bounded_int(config.get("min_baseline_sessions", size),
                           "min_baseline_sessions", 1, 100)
    needed = size + minimum
    if len(rows) < needed:
        return [{
            "code": "TELEMETRY_REGRESSION_INSUFFICIENT_DATA",
            "severity": "info",
            "required_sessions": needed,
            "actual_sessions": len(rows),
        }]
    recent = rows[-size:]
    baseline = rows[-size - minimum:-size]
    alerts: list[dict[str, Any]] = []
    for metric, key in (
        ("total_tokens", "max_total_tokens_percent"),
        ("input_tokens", "max_input_tokens_percent"),
        ("output_tokens", "max_output_tokens_percent"),
    ):
        threshold = config.get(key)
        if isinstance(threshold, int | float):
            _append_regression(alerts, metric, _average(baseline, metric),
                               _average(recent, metric), float(threshold))
    cost_threshold = config.get("max_estimated_cost_percent")
    currency = config.get("currency", "USD")
    if isinstance(cost_threshold, int | float) and isinstance(currency, str):
        missing = sum(1 for row in [*baseline, *recent] if not _has_cost(row, currency))
        if missing:
            alerts.append({
                "code": "TELEMETRY_REGRESSION_COST_DATA_MISSING",
                "severity": "error",
                "scope": "regression",
                "metric": f"estimated_cost:{currency}",
                "missing_sessions": missing,
                "message": f"cost regression lacks {currency} cost for {missing} sessions",
            })
        else:
            _append_regression(
                alerts,
                f"estimated_cost:{currency}",
                _average_cost(baseline, currency),
                _average_cost(recent, currency),
                float(cost_threshold),
            )
    return alerts


def _append_regression(
    alerts: list[dict[str, Any]], metric: str, baseline: float, recent: float, threshold: float
) -> None:
    percent = math.inf if baseline == 0 and recent > 0 else (
        0.0 if baseline == 0 else ((recent - baseline) / baseline) * 100
    )
    if percent > threshold:
        alerts.append({
            "code": "TELEMETRY_REGRESSION_EXCEEDED",
            "severity": "error",
            "scope": "regression",
            "metric": metric,
            "baseline_average": round(baseline, 8),
            "recent_average": round(recent, 8),
            "regression_percent": None if math.isinf(percent) else round(percent, 2),
            "limit_percent": threshold,
            "message": f"{metric} regression exceeds {threshold}%",
        })


def _limits(value: object, scope: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{scope} limits must be an object")
    unknown = set(value) - LIMIT_KEYS
    if unknown:
        raise ValueError(f"unknown {scope} limit fields: {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key == "max_estimated_costs":
            if not isinstance(item, dict) or not item:
                raise ValueError(f"{scope}.{key} must be a non-empty currency object")
            result[key] = {currency: _number(amount, f"{scope}.{key}.{currency}")
                           for currency, amount in item.items() if _currency(currency)}
        else:
            result[key] = _bounded_int(item, f"{scope}.{key}", 0, 10_000_000_000)
    return result


def _scopes(value: object, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if len(value) > 100:
        raise ValueError(f"{name} supports at most 100 entries")
    result: dict[str, dict[str, Any]] = {}
    for scope, limits in value.items():
        if not isinstance(scope, str) or not 1 <= len(scope) <= 200 or "\x00" in scope:
            raise ValueError(f"{name} contains an invalid key")
        result[scope] = _limits(limits, f"{name}.{scope}")
    return result


def _regression(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("regression must be an object")
    allowed = {
        "recent_sessions", "min_baseline_sessions", "max_total_tokens_percent",
        "max_input_tokens_percent", "max_output_tokens_percent",
        "max_estimated_cost_percent", "currency",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown regression fields: {', '.join(sorted(unknown))}")
    result = dict(value)
    for key in ("recent_sessions", "min_baseline_sessions"):
        if key in result:
            result[key] = _bounded_int(result[key], key, 1, 100)
    for key in allowed - {"recent_sessions", "min_baseline_sessions", "currency"}:
        if key in result:
            result[key] = _number(result[key], key)
    if "currency" in result:
        _currency(result["currency"])
    return result


def _validate_pricing(value: dict[str, Any]) -> dict[str, Any]:
    currency = value.get("currency", "USD")
    _currency(currency)
    models = value.get("models")
    if not isinstance(models, dict) or not models or len(models) > 500:
        raise ValueError("pricing input requires 1-500 models")
    normalized: dict[str, dict[str, float]] = {}
    allowed = {
        "input_per_million", "cached_input_per_million",
        "cache_write_input_per_million", "output_per_million",
    }
    for model, rates in models.items():
        if not isinstance(model, str) or not 1 <= len(model) <= 200 or "\x00" in model:
            raise ValueError("pricing input contains an invalid model")
        if not isinstance(rates, dict) or set(rates) - allowed:
            raise ValueError(f"pricing rates for {model} contain unsupported fields")
        if "input_per_million" not in rates or "output_per_million" not in rates:
            raise ValueError(f"pricing rates for {model} require input and output")
        normalized[model] = {key: _number(item, f"models.{model}.{key}")
                             for key, item in rates.items()}
    return {"currency": currency, "models": normalized}


def _session_rows(root: Path) -> list[dict[str, Any]]:
    return load_session_rows(root)


def _costs(rows: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        cost = row.get("cost")
        if isinstance(cost, dict):
            currency, amount = cost.get("currency"), cost.get("estimated_amount")
            if isinstance(currency, str) and isinstance(amount, int | float):
                result[currency] = result.get(currency, 0.0) + float(amount)
    return {key: round(value, 8) for key, value in result.items()}


def _average(rows: list[dict[str, Any]], metric: str) -> float:
    return sum(_safe_int(row.get(metric)) for row in rows) / len(rows)


def _average_cost(rows: list[dict[str, Any]], currency: str) -> float:
    return _costs(rows).get(currency, 0.0) / len(rows)


def _has_cost(row: dict[str, Any], currency: str) -> bool:
    cost = row.get("cost")
    return (
        isinstance(cost, dict)
        and cost.get("currency") == currency
        and isinstance(cost.get("estimated_amount"), int | float)
    )


def _violation(
    code: str, scope: str, metric: str, actual: int | float, limit: int | float
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "error",
        "scope": scope,
        "metric": metric,
        "actual": actual,
        "limit": limit,
        "message": f"{scope} {metric} is {actual}, above {limit}",
    }


def _strict_object(path: Path, maximum: int, label: str) -> dict[str, Any]:
    if path.stat().st_size > maximum:
        raise ValueError(f"{label} exceeds {maximum} bytes")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _project_file(root: Path, path: Path, label: str, *, required: bool) -> Path | None:
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must be inside the project")
    if not resolved.is_file():
        if not required:
            return None
        raise ValueError(f"{label} must be an existing file")
    return resolved


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _currency(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 10 or "\x00" in value:
        raise ValueError("currency must be a short string")
    return value


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
