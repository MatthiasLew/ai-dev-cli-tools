from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from collector.app.config import settings
from collector.app.models import TelemetryEvent
from collector.app.storage import get_session

logger = logging.getLogger("collector.retention")


def delete_expired_events(
    session: Session,
    days: int = settings.retention_days,
    dry_run: bool = False,
    now: datetime | None = None,
) -> int:
    """
    Delete events older than `days` days from the database.
    Returns:
        The number of records deleted (or identified for deletion in dry_run).
    """
    reference_time = now or datetime.now(UTC)
    cutoff = reference_time - timedelta(days=days)

    count_stmt = select(TelemetryEvent.event_id).where(TelemetryEvent.received_at < cutoff)
    candidate_ids = list(session.scalars(count_stmt).all())
    count = len(candidate_ids)

    if count == 0:
        return 0

    if dry_run:
        logger.info("[DRY RUN] Found %d expired events older than %s", count, cutoff.isoformat())
        return count

    delete_stmt = delete(TelemetryEvent).where(TelemetryEvent.received_at < cutoff)
    session.execute(delete_stmt)
    session.commit()
    logger.info("Successfully purged %d expired events older than %s", count, cutoff.isoformat())
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge expired Community Telemetry events.")
    parser.add_argument(
        "--days",
        type=int,
        default=settings.retention_days,
        help="Retention period in days (default: 90)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report records that would be deleted without removing them",
    )
    args = parser.parse_args()

    with get_session() as session:
        purged = delete_expired_events(session, days=args.days, dry_run=args.dry_run)
        action = "would be purged" if args.dry_run else "purged"
        print(f"Retention policy: {purged} event(s) {action} (cutoff: {args.days} days).")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    sys.exit(main())
