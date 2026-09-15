from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from collector.app.config import settings
from collector.app.models import Base, TelemetryEvent

logger = logging.getLogger("collector.storage")


def get_engine(database_url: str | None = None) -> Any:
    url = database_url or settings.database_url
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        return create_engine(url, connect_args=connect_args)
    return create_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = get_engine()
SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(target_engine: Any = engine) -> None:
    """Initialize database schema tables."""
    Base.metadata.create_all(bind=target_engine)


@contextmanager
def get_session(
    custom_factory: sessionmaker[Session] | None = None,
) -> Generator[Session, None, None]:
    factory = custom_factory or SessionFactory
    session: Session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def insert_telemetry_event(
    payload: dict[str, Any],
    custom_session_factory: sessionmaker[Session] | None = None,
) -> tuple[bool, bool]:
    """
    Idempotently insert an event into the database.
    Returns:
        (success: bool, is_duplicate: bool)
    """
    event_id = payload.get("event_id")
    if not event_id:
        return False, False

    with get_session(custom_session_factory) as session:
        # Check if already exists (fast-path for duplicate)
        existing = session.get(TelemetryEvent, event_id)
        if existing is not None:
            return True, True

        event = TelemetryEvent.from_payload(payload)
        session.add(event)
        try:
            session.commit()
            return True, False
        except IntegrityError:
            session.rollback()
            # Double-check PK conflict
            if session.get(TelemetryEvent, event_id) is not None:
                return True, True
            raise


def check_db_health(target_engine: Any = engine) -> bool:
    """Ping database to confirm connectivity."""
    try:
        with target_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        return False
