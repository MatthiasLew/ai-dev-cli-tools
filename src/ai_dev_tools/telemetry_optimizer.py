from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Issue, Report
from ai_dev_tools.telemetry import load_session_rows

MAX_GROUPS = 25
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def optimize_usage(
    project_root: Path,
    *,
    min_sessions: int = 5,
    percentile: float = 95.0,
    safety_margin_percent: float = 20.0,
    accuracy_target_percent: float = 95.0,
    max_accuracy_drop_percent: float = 0.0,
) -> Report:
    root = project_root.resolve()
    report = Report(command="telemetry optimize", project_root=root)
    try:
        minimum = _bounded_int(min_sessions, "min_sessions", 2, 1000)
        selected_percentile = _bounded_number(percentile, "percentile", 50.0, 100.0)
        margin = _bounded_number(
            safety_margin_percent, "safety_margin_percent", 0.0, 500.0
        )
        accuracy_target = _bounded_number(
            accuracy_target_percent, "accuracy_target_percent", 0.0, 100.0
        )
        accuracy_drop = _bounded_number(
            max_accuracy_drop_percent, "max_accuracy_drop_percent", 0.0, 100.0
        )
        rows = load_session_rows(root)
    except (OSError, ValueError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_TELEMETRY_OPTIMIZER", "message": str(exc)}
        report.issues.append(
            Issue("error", str(exc), code="INVALID_TELEMETRY_OPTIMIZER")
        )
        return report

    attribution = {
        "clients": _group_summaries(rows, lambda row: row.get("client")),
        "models": _group_summaries(rows, lambda row: row.get("model")),
        "phases": _group_summaries(rows, lambda row: row.get("phase")),
        "tools": _group_summaries(rows, lambda row: row.get("tool_name")),
        "task_kinds": _group_summaries(rows, lambda row: row.get("task_kind")),
    }
    budget_recommendations, budget_gaps = _budget_recommendations(
        rows,
        minimum=minimum,
        percentile=selected_percentile,
        margin=margin,
    )
    model_recommendations, model_gaps = _model_recommendations(
        rows,
        minimum=minimum,
        accuracy_target=accuracy_target,
        max_accuracy_drop=accuracy_drop,
    )
    report.summary = {
        "schema_version": "1",
        "measurement": "provider_reported",
        "sessions": len(rows),
        "settings": {
            "min_sessions": minimum,
            "percentile": selected_percentile,
            "safety_margin_percent": margin,
            "accuracy_target_percent": accuracy_target,
            "max_accuracy_drop_percent": accuracy_drop,
        },
        "overall": _summarize(rows),
        "attribution": attribution,
        "budget_recommendations": budget_recommendations,
        "model_recommendations": model_recommendations,
        "gaps": [*budget_gaps, *model_gaps],
        "automatic_changes": False,
    }
    return report


def compact_optimizer_status(project_root: Path) -> dict[str, Any]:
    report = optimize_usage(project_root)
    if report.status == "invalid_configuration":
        return {
            "status": report.status,
            "budget_recommendations": 0,
            "model_recommendations": 0,
            "gaps": 1,
        }
    return {
        "status": report.status,
        "sessions": report.summary.get("sessions", 0),
        "budget_recommendations": len(report.summary.get("budget_recommendations", [])),
        "model_recommendations": len(report.summary.get("model_recommendations", [])),
        "gaps": len(report.summary.get("gaps", [])),
    }


def _group_summaries(
    rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], object]
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        if isinstance(key, str) and key:
            groups[key].append(row)
    summaries = [
        {"name": name, **_summarize(group_rows)}
        for name, group_rows in groups.items()
    ]
    summaries.sort(key=lambda item: (-int(item["total_tokens"]), str(item["name"])))
    return summaries[:MAX_GROUPS]


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        field: sum(_safe_int(row.get(field)) for row in rows)
        for field in TOKEN_FIELDS
    }
    per_session = [_safe_int(row.get("total_tokens")) for row in rows]
    cached = totals["cached_input_tokens"]
    cache_write = totals["cache_write_input_tokens"]
    input_tokens = totals["input_tokens"]
    quality = [row["quality_passed"] for row in rows if isinstance(row.get("quality_passed"), bool)]
    return {
        "sessions": len(rows),
        **totals,
        "average_total_tokens": round(totals["total_tokens"] / len(rows), 2) if rows else 0.0,
        "p50_total_tokens": _percentile(per_session, 50.0),
        "p95_total_tokens": _percentile(per_session, 95.0),
        "cache_share_percent": (
            round(((cached + cache_write) / input_tokens) * 100, 2)
            if input_tokens
            else 0.0
        ),
        "quality_samples": len(quality),
        "quality_pass_rate_percent": (
            round((sum(1 for value in quality if value) / len(quality)) * 100, 2)
            if quality
            else None
        ),
        "estimated_costs": _cost_totals(rows),
    }


def _budget_recommendations(
    rows: list[dict[str, Any]], *, minimum: int, percentile: float, margin: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = [("global", rows)]
    for field, prefix in (("task_kind", "task_kind"), ("phase", "phase")):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            value = row.get(field)
            if isinstance(value, str) and value:
                grouped[value].append(row)
        groups.extend((f"{prefix}:{name}", value) for name, value in sorted(grouped.items()))

    recommendations: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for scope, samples in groups[: MAX_GROUPS + 1]:
        if len(samples) < minimum:
            if scope == "global":
                gaps.append({
                    "code": "TOKEN_OPTIMIZER_INSUFFICIENT_USAGE_DATA",
                    "scope": scope,
                    "required_sessions": minimum,
                    "actual_sessions": len(samples),
                })
            continue
        totals = [_safe_int(row.get("total_tokens")) for row in samples]
        selected = _percentile(totals, percentile)
        recommendations.append({
            "code": "TOKEN_BUDGET_RECOMMENDATION",
            "scope": scope,
            "sessions": len(samples),
            "p50_total_tokens": _percentile(totals, 50.0),
            "p95_total_tokens": _percentile(totals, 95.0),
            "selected_percentile": percentile,
            "selected_total_tokens": selected,
            "safety_margin_percent": margin,
            "recommended_max_total_tokens": math.ceil(selected * (1 + margin / 100)),
            "automatic_apply": False,
        })
    return recommendations, gaps


def _model_recommendations(
    rows: list[dict[str, Any]], *, minimum: int, accuracy_target: float,
    max_accuracy_drop: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_task: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        task_kind, model = row.get("task_kind"), row.get("model")
        if (
            isinstance(task_kind, str) and task_kind
            and isinstance(model, str) and model
            and isinstance(row.get("quality_passed"), bool)
        ):
            by_task[task_kind][model].append(row)

    recommendations: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    if not by_task:
        return recommendations, [{
            "code": "MODEL_ROUTING_NO_QUALITY_DATA",
            "required_fields": ["task_kind", "model", "quality_passed"],
        }]

    for task_kind, models in sorted(by_task.items())[:MAX_GROUPS]:
        eligible = {
            model: _model_evidence(samples)
            for model, samples in models.items()
            if len(samples) >= minimum
        }
        if len(eligible) < 2:
            gaps.append({
                "code": "MODEL_ROUTING_INSUFFICIENT_MODEL_SAMPLES",
                "task_kind": task_kind,
                "required_sessions_per_model": minimum,
                "eligible_models": len(eligible),
            })
            continue
        incumbent_name = sorted(
            eligible,
            key=lambda name: (-int(eligible[name]["quality_samples"]), name),
        )[0]
        incumbent = eligible[incumbent_name]
        incumbent_accuracy = float(incumbent["quality_pass_rate_percent"])
        if incumbent_accuracy < accuracy_target:
            gaps.append({
                "code": "MODEL_ROUTING_ACCURACY_TARGET_NOT_MET",
                "task_kind": task_kind,
                "model": incumbent_name,
                "actual_percent": incumbent_accuracy,
                "required_percent": accuracy_target,
            })
            continue
        incumbent_cost = incumbent.get("average_cost")
        currency = incumbent.get("currency")
        if not isinstance(incumbent_cost, float) or not isinstance(currency, str):
            gaps.append({
                "code": "MODEL_ROUTING_COST_DATA_MISSING",
                "task_kind": task_kind,
                "model": incumbent_name,
            })
            continue
        candidates: list[tuple[str, dict[str, Any]]] = []
        for name, evidence in eligible.items():
            candidate_cost = evidence.get("average_cost")
            candidate_accuracy = float(evidence["quality_pass_rate_percent"])
            if (
                name != incumbent_name
                and evidence.get("currency") == currency
                and isinstance(candidate_cost, float)
                and candidate_cost < incumbent_cost
                and candidate_accuracy >= accuracy_target
                and candidate_accuracy >= incumbent_accuracy - max_accuracy_drop
            ):
                candidates.append((name, evidence))
        if not candidates:
            gaps.append({
                "code": "MODEL_ROUTING_NO_CHEAPER_QUALIFIED_MODEL",
                "task_kind": task_kind,
                "incumbent_model": incumbent_name,
            })
            continue
        candidate_name, candidate = min(
            candidates, key=lambda item: (float(item[1]["average_cost"]), item[0])
        )
        candidate_cost = float(candidate["average_cost"])
        recommendations.append({
            "code": "MODEL_ROUTING_RECOMMENDATION",
            "task_kind": task_kind,
            "current_model": incumbent_name,
            "candidate_model": candidate_name,
            "current_quality_percent": incumbent_accuracy,
            "candidate_quality_percent": candidate["quality_pass_rate_percent"],
            "quality_samples": candidate["quality_samples"],
            "current_average_cost": incumbent_cost,
            "candidate_average_cost": candidate_cost,
            "currency": currency,
            "estimated_savings_percent": round(
                ((incumbent_cost - candidate_cost) / incumbent_cost) * 100, 2
            ) if incumbent_cost else 0.0,
            "requires_human_approval": True,
            "automatic_switch": False,
        })
    return recommendations, gaps


def _model_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in rows if row.get("quality_passed") is True)
    costs = [_cost_value(row) for row in rows]
    valid_costs = [item for item in costs if item is not None]
    currencies = {item[0] for item in valid_costs}
    complete_cost = len(valid_costs) == len(rows) and len(currencies) == 1
    return {
        "quality_samples": len(rows),
        "quality_pass_rate_percent": round((passed / len(rows)) * 100, 2),
        "average_cost": (
            round(sum(item[1] for item in valid_costs) / len(valid_costs), 8)
            if complete_cost
            else None
        ),
        "currency": next(iter(currencies)) if complete_cost else None,
    }


def _cost_value(row: dict[str, Any]) -> tuple[str, float] | None:
    cost = row.get("cost")
    if not isinstance(cost, dict):
        return None
    currency, amount = cost.get("currency"), cost.get("estimated_amount")
    if (
        not isinstance(currency, str)
        or isinstance(amount, bool)
        or not isinstance(amount, int | float)
        or not math.isfinite(float(amount))
        or float(amount) < 0
    ):
        return None
    return currency, float(amount)


def _cost_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        value = _cost_value(row)
        if value is not None:
            totals[value[0]] += value[1]
    return {currency: round(amount, 8) for currency, amount in sorted(totals.items())}


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100) * len(ordered)))
    return ordered[rank - 1]


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _bounded_number(
    value: object, name: str, minimum: float, maximum: float
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number from {minimum} to {maximum}")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be a number from {minimum} to {maximum}")
    return result


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
