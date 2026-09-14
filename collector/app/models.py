from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    # Primary key & idempotency
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    telemetry_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    # Basic fields
    ai_dev_version: Mapped[str] = mapped_column(String(32), nullable=False)
    os_family: Mapped[str] = mapped_column(String(16), nullable=False)
    python_version: Mapped[str] = mapped_column(String(16), nullable=False)
    command_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    command_category: Mapped[str] = mapped_column(String(32), nullable=False)
    command_outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    timestamp_hour: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Research fields (nullable for basic events)
    ai_client: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    task_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    repo_files_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True)
    repo_size_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language_families: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selection_reason_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Metrics
    context_candidate_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_delivered_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_considered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_selected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_omitted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    semantic_cache_reuse: Mapped[float | None] = mapped_column(Float, nullable=True)
    local_overhead_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_wall_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], received_at: datetime | None = None
    ) -> TelemetryEvent:
        """Create a TelemetryEvent entity from a validated payload dictionary."""
        lang_families = payload.get("language_families")
        sel_codes = payload.get("selection_reason_codes")

        return cls(
            event_id=payload["event_id"],
            schema_version=payload["schema_version"],
            event_type=payload["event_type"],
            telemetry_level=payload["telemetry_level"],
            received_at=received_at or datetime.now(UTC),
            ai_dev_version=payload["ai_dev_version"],
            os_family=payload["os_family"],
            python_version=payload["python_version"],
            command_name=payload["command_name"],
            command_category=payload["command_category"],
            command_outcome=payload["command_outcome"],
            reason_code=payload.get("reason_code"),
            duration_bucket=payload["duration_bucket"],
            duration_seconds=payload.get("duration_seconds"),
            cache_hit=payload.get("cache_hit"),
            timestamp_hour=payload["timestamp_hour"],
            ai_client=payload.get("ai_client"),
            model=payload.get("model"),
            task_kind=payload.get("task_kind"),
            validation_result=payload.get("validation_result"),
            task_outcome=payload.get("task_outcome"),
            repo_files_bucket=payload.get("repo_files_bucket"),
            repo_size_bucket=payload.get("repo_size_bucket"),
            language_families=json.dumps(lang_families) if lang_families is not None else None,
            retrieval_reason_code=payload.get("retrieval_reason_code"),
            selection_reason_codes=json.dumps(sel_codes) if sel_codes is not None else None,
            origin=payload.get("origin"),
            context_candidate_tokens=payload.get("context_candidate_tokens"),
            context_delivered_tokens=payload.get("context_delivered_tokens"),
            context_budget=payload.get("context_budget"),
            input_tokens=payload.get("input_tokens"),
            cached_input_tokens=payload.get("cached_input_tokens"),
            output_tokens=payload.get("output_tokens"),
            reasoning_tokens=payload.get("reasoning_tokens"),
            total_tokens=payload.get("total_tokens"),
            tool_call_count=payload.get("tool_call_count"),
            files_considered=payload.get("files_considered"),
            files_selected=payload.get("files_selected"),
            files_omitted=payload.get("files_omitted"),
            cache_hit_ratio=payload.get("cache_hit_ratio"),
            semantic_cache_reuse=payload.get("semantic_cache_reuse"),
            local_overhead_seconds=payload.get("local_overhead_seconds"),
            total_wall_time_seconds=payload.get("total_wall_time_seconds"),
        )
