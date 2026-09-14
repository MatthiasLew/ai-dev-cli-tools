"""0001_initial_telemetry_events

Revision ID: 0001_initial_telemetry_events
Revises: None
Create Date: 2026-09-14 19:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_telemetry_events"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("telemetry_level", sa.String(length=16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ai_dev_version", sa.String(length=32), nullable=False),
        sa.Column("os_family", sa.String(length=16), nullable=False),
        sa.Column("python_version", sa.String(length=16), nullable=False),
        sa.Column("command_name", sa.String(length=32), nullable=False),
        sa.Column("command_category", sa.String(length=32), nullable=False),
        sa.Column("command_outcome", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("duration_bucket", sa.String(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=True),
        sa.Column("timestamp_hour", sa.String(length=32), nullable=False),
        sa.Column("ai_client", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("task_kind", sa.String(length=32), nullable=True),
        sa.Column("validation_result", sa.String(length=16), nullable=True),
        sa.Column("task_outcome", sa.String(length=16), nullable=True),
        sa.Column("repo_files_bucket", sa.String(length=32), nullable=True),
        sa.Column("repo_size_bucket", sa.String(length=32), nullable=True),
        sa.Column("language_families", sa.Text(), nullable=True),
        sa.Column("retrieval_reason_code", sa.String(length=64), nullable=True),
        sa.Column("selection_reason_codes", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=True),
        sa.Column("context_candidate_tokens", sa.Integer(), nullable=True),
        sa.Column("context_delivered_tokens", sa.Integer(), nullable=True),
        sa.Column("context_budget", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=True),
        sa.Column("files_considered", sa.Integer(), nullable=True),
        sa.Column("files_selected", sa.Integer(), nullable=True),
        sa.Column("files_omitted", sa.Integer(), nullable=True),
        sa.Column("cache_hit_ratio", sa.Float(), nullable=True),
        sa.Column("semantic_cache_reuse", sa.Float(), nullable=True),
        sa.Column("local_overhead_seconds", sa.Float(), nullable=True),
        sa.Column("total_wall_time_seconds", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_telemetry_events_command_name",
        "telemetry_events",
        ["command_name"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_events_event_type",
        "telemetry_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_events_received_at",
        "telemetry_events",
        ["received_at"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_events_telemetry_level",
        "telemetry_events",
        ["telemetry_level"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_events_timestamp_hour",
        "telemetry_events",
        ["timestamp_hour"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_events_timestamp_hour", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_telemetry_level", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_received_at", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_event_type", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_command_name", table_name="telemetry_events")
    op.drop_table("telemetry_events")
