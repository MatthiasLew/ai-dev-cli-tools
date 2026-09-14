from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_dev_tools.community.builder import build_community_payload
from collector.app.models import TelemetryEvent
from collector.app.retention import delete_expired_events


def test_retention_90_days_cleanup(test_db_session: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    payload = build_community_payload("basic", sample=True)

    id_old = str(uuid.uuid4())
    id_edge = str(uuid.uuid4())
    id_fresh = str(uuid.uuid4())

    with test_db_session() as session:
        # 91 days ago (should be purged)
        ev_old = TelemetryEvent.from_payload(
            {**payload, "event_id": id_old},
            received_at=now - timedelta(days=91),
        )
        # 89 days ago (should be retained)
        ev_edge = TelemetryEvent.from_payload(
            {**payload, "event_id": id_edge},
            received_at=now - timedelta(days=89),
        )
        # Today (should be retained)
        ev_fresh = TelemetryEvent.from_payload(
            {**payload, "event_id": id_fresh},
            received_at=now,
        )
        session.add_all([ev_old, ev_edge, ev_fresh])
        session.commit()

    with test_db_session() as session:
        # Test dry-run: identifies 1 event without deleting
        dry_count = delete_expired_events(session, days=90, dry_run=True, now=now)
        assert dry_count == 1

        remaining = list(session.scalars(select(TelemetryEvent.event_id)).all())
        assert len(remaining) == 3

        # Test actual purge
        purged_count = delete_expired_events(session, days=90, dry_run=False, now=now)
        assert purged_count == 1

        remaining_after = set(session.scalars(select(TelemetryEvent.event_id)).all())
        assert remaining_after == {id_edge, id_fresh}
        assert id_old not in remaining_after
