import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from ai_dev_tools.community.builder import build_community_payload
from collector.app.models import TelemetryEvent


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    temp_dir = tempfile.mkdtemp(prefix="ai_dev_alembic_test_")
    db_file = Path(temp_dir) / "test_migration.db"
    yield db_file
    if db_file.exists():
        db_file.unlink(missing_ok=True)


def test_alembic_upgrade_and_downgrade_lifecycle(temp_db_path: Path) -> None:
    db_url = f"sqlite:///{temp_db_path.as_posix()}"

    alembic_cfg_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(alembic_cfg_path))
    cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Upgrade to head
    command.upgrade(cfg, "head")

    # 2. Inspect table existence
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "telemetry_events" in tables
        assert "alembic_version" in tables

        # Verify column presence
        columns = {col["name"] for col in inspector.get_columns("telemetry_events")}
        assert "event_id" in columns
        assert "received_at" in columns
        assert "command_name" in columns
        assert "telemetry_level" in columns
        assert "total_tokens" in columns

        # Verify indices
        indices = {idx["name"] for idx in inspector.get_indexes("telemetry_events")}
        assert "ix_telemetry_events_command_name" in indices
        assert "ix_telemetry_events_received_at" in indices
        assert "ix_telemetry_events_timestamp_hour" in indices

        # 3. Insert an event into the migrated database
        payload = build_community_payload("basic", sample=True)
        with Session(engine) as session:
            event = TelemetryEvent.from_payload(payload)
            session.add(event)
            session.commit()

            # Query back
            res = session.execute(text("SELECT COUNT(*) FROM telemetry_events")).scalar()
            assert res == 1

        # 4. Downgrade to base
        command.downgrade(cfg, "base")
        inspector_after = inspect(engine)
        tables_after = inspector_after.get_table_names()
        assert "telemetry_events" not in tables_after
    finally:
        engine.dispose()
