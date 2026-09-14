from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_dev_tools.community.builder import build_community_payload
from collector.app.models import TelemetryEvent
from collector.app.retention import delete_expired_events
from collector.app.retention import main as retention_main
from collector.app.storage import (
    check_db_health,
    get_engine,
    get_session,
    insert_telemetry_event,
)


def test_get_engine_branches() -> None:
    # SQLite
    sqlite_eng = get_engine("sqlite:///:memory:")
    assert sqlite_eng is not None
    sqlite_eng.dispose()

    # PostgreSQL URL configuration
    with patch("collector.app.storage.create_engine") as mock_create:
        get_engine("postgresql+psycopg://user:pass@localhost:5432/telemetry")
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert args[0].startswith("postgresql")
        assert kwargs["pool_size"] == 10


def test_get_session_exception_rollback(test_db_session: sessionmaker[Session]) -> None:
    with (
        pytest.raises(RuntimeError, match="Simulated crash"),
        get_session(test_db_session) as session,
    ):
        payload = build_community_payload("basic", sample=True)
        session.add(TelemetryEvent.from_payload(payload))
        raise RuntimeError("Simulated crash")


def test_insert_telemetry_event_missing_event_id() -> None:
    success, is_duplicate = insert_telemetry_event({})
    assert success is False
    assert is_duplicate is False


def test_insert_telemetry_event_integrity_error_recovery(
    test_db_session: sessionmaker[Session],
) -> None:
    payload = build_community_payload("basic", sample=True)
    # Insert once
    s1, d1 = insert_telemetry_event(payload, custom_session_factory=test_db_session)
    assert s1 is True
    assert d1 is False

    # Simulate IntegrityError on commit
    mock_session = MagicMock()
    mock_session.get.side_effect = [None, TelemetryEvent.from_payload(payload)]
    mock_session.commit.side_effect = IntegrityError("duplicate", params=None, orig=Exception())
    mock_factory = MagicMock(return_value=mock_session)

    s2, d2 = insert_telemetry_event(payload, custom_session_factory=mock_factory)
    assert s2 is True
    assert d2 is True
    mock_session.rollback.assert_called_once()


def test_insert_telemetry_event_unhandled_integrity_error() -> None:
    payload = build_community_payload("basic", sample=True)
    mock_session = MagicMock()
    mock_session.get.side_effect = [None, None]  # Event not found on re-check
    mock_session.commit.side_effect = IntegrityError("fatal", params=None, orig=Exception())
    mock_factory = MagicMock(return_value=mock_session)

    with pytest.raises(IntegrityError):
        insert_telemetry_event(payload, custom_session_factory=mock_factory)


def test_check_db_health(test_db_session: sessionmaker[Session]) -> None:
    with test_db_session() as session:
        eng = session.get_bind()
        assert check_db_health(eng) is True

    # Failed health check
    mock_eng = MagicMock()
    mock_eng.connect.side_effect = RuntimeError("DB down")
    assert check_db_health(mock_eng) is False


def test_delete_expired_events_empty_table(test_db_session: sessionmaker[Session]) -> None:
    with test_db_session() as session:
        count = delete_expired_events(session, days=90)
        assert count == 0


def test_retention_cli_main(test_db_session: sessionmaker[Session]) -> None:
    with (
        patch.object(sys, "argv", ["retention", "--days", "30", "--dry-run"]),
        patch("collector.app.retention.get_session", lambda: get_session(test_db_session)),
    ):
        exit_code = retention_main()
        assert exit_code == 0
