from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from collector.app.main import app, rate_limiter
from collector.app.models import Base


@pytest.fixture
def test_db_session(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    db_path = tmp_path / "test_telemetry.db"
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    import collector.app.storage as storage_mod

    old_engine = storage_mod.engine
    old_factory = storage_mod.SessionFactory
    storage_mod.engine = test_engine
    storage_mod.SessionFactory = factory

    yield factory

    storage_mod.engine = old_engine
    storage_mod.SessionFactory = old_factory


@pytest.fixture
def client(test_db_session: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    rate_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    rate_limiter.reset()
