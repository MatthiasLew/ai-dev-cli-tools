from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_dev_tools.community.builder import build_community_payload
from collector.app.models import TelemetryEvent


def test_event_id_deduplication(client: TestClient, test_db_session: sessionmaker[Session]) -> None:
    payload = build_community_payload("research", sample=True)
    event_id = payload["event_id"]

    # First attempt: brand new event
    resp1 = client.post("/v1/events", json=payload)
    assert resp1.status_code == 202
    assert resp1.json() == {"status": "accepted"}

    # Second attempt: same event_id delivered again
    resp2 = client.post("/v1/events", json=payload)
    assert resp2.status_code == 200
    assert resp2.json() == {"status": "accepted", "duplicate": True}

    # Verify database contents: exactly 1 record
    with test_db_session() as session:
        events = list(
            session.scalars(select(TelemetryEvent).where(TelemetryEvent.event_id == event_id)).all()
        )
        assert len(events) == 1
        assert events[0].event_id == event_id
