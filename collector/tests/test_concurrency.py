from __future__ import annotations

import concurrent.futures
import uuid

from sqlalchemy.orm import Session, sessionmaker

from ai_dev_tools.community.builder import build_community_payload
from collector.app.models import TelemetryEvent
from collector.app.storage import insert_telemetry_event


def test_concurrent_duplicate_ingestion(test_db_session: sessionmaker[Session]) -> None:
    # Build payload with fixed event_id
    event_id = str(uuid.uuid4())
    payload = build_community_payload("basic", sample=True)
    payload["event_id"] = event_id

    concurrency = 20
    results: list[tuple[bool, bool]] = []

    def worker() -> tuple[bool, bool]:
        return insert_telemetry_event(payload, custom_session_factory=test_db_session)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker) for _ in range(concurrency)]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    # Every worker must succeed without raising errors
    assert len(results) == concurrency
    assert all(res[0] is True for res in results)

    # Exactly 1 insertion must report is_duplicate=False; all others must report is_duplicate=True
    new_inserts = [res for res in results if res[1] is False]
    duplicate_inserts = [res for res in results if res[1] is True]

    assert len(new_inserts) == 1
    assert len(duplicate_inserts) == concurrency - 1

    # Database state verification: strictly 1 row in table
    with test_db_session() as session:
        from sqlalchemy import select

        events = list(
            session.scalars(select(TelemetryEvent).where(TelemetryEvent.event_id == event_id)).all()
        )
        assert len(events) == 1
