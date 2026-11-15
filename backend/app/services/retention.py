"""Retention: keep the database small without losing the long-term picture.

Every run (hourly by default):

1. Raw samples older than ``RAW_RETENTION_HOURS`` are folded into 1-minute
   rollups and deleted.
2. Rollups older than ``ROLLUP_RETENTION_DAYS`` are deleted.
3. Status transitions older than ``TRANSITION_RETENTION_DAYS`` are deleted.

Step 1 is safe to repeat (idempotent). Each batch of raw samples is added to
the rollups and deleted in the SAME transaction, so a sample is always in
exactly one place: still raw, or counted in a rollup. If a rollup row for the
minute already exists, the new samples are merged into it, never written over
it.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, update

from app.core.config import settings
from app.db.session import engine
from app.services.flap_store import flap_store
from app.services.persistence import ROLLUPS, SAMPLES, TRANSITIONS, rollup_bucket, rollup_values
from app.services.rollup import MINUTE, Bucket, bucket_start, merge, sample_bucket

logger = logging.getLogger(__name__)

# Raw samples are rolled up this many at a time, one transaction per batch, so
# a large backlog never holds the database's write lock for long. The short
# pause between batches lets a waiting writer (the poll loop saving a cycle)
# take its turn.
ROLLUP_BATCH_SIZE = 20_000
ROLLUP_BATCH_PAUSE_SECONDS = 0.05


@dataclass(frozen=True)
class RetentionReport:
    samples_rolled_up: int
    rollup_rows_written: int
    rollups_deleted: int
    transitions_deleted: int


def _roll_up_samples_before(cutoff: datetime) -> tuple[int, int]:
    """Fold every raw sample older than ``cutoff`` into the 1-minute rollups.

    Returns (samples rolled up, rollup rows inserted or updated).
    """
    rolled_up = written = 0
    while True:
        with engine.begin() as connection:
            # Take SQLite's write lock before reading. Otherwise this
            # transaction would start as a reader and could be refused the
            # upgrade to a writer while the poll loop is saving a cycle.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            rows = connection.execute(
                select(
                    SAMPLES.c.id,
                    SAMPLES.c.device_id,
                    SAMPLES.c.ts,
                    SAMPLES.c.latency_ms,
                    SAMPLES.c.loss_pct,
                    SAMPLES.c.jitter_ms,
                )
                .where(SAMPLES.c.ts < cutoff)
                .order_by(SAMPLES.c.id)
                .limit(ROLLUP_BATCH_SIZE)
            ).all()
            if not rows:
                return rolled_up, written

            fresh: dict[tuple[str, datetime], Bucket] = {}
            for _, device_id, ts, latency_ms, loss, jitter in rows:
                bucket = sample_bucket(ts, latency_ms, MINUTE, loss, jitter)
                key = (device_id, bucket.start)
                fresh[key] = merge(fresh[key], bucket) if key in fresh else bucket

            # Minutes that already have a rollup row: merge into it.
            starts = [start for _, start in fresh]
            existing = connection.execute(
                select(ROLLUPS).where(
                    ROLLUPS.c.bucket_start >= min(starts), ROLLUPS.c.bucket_start <= max(starts)
                )
            ).all()
            for row in existing:
                addition = fresh.pop((row.device_id, row.bucket_start), None)
                if addition is None:
                    continue
                merged = merge(rollup_bucket(row), addition)
                connection.execute(
                    update(ROLLUPS).where(ROLLUPS.c.id == row.id).values(**rollup_values(merged))
                )
                written += 1

            if fresh:
                connection.execute(
                    insert(ROLLUPS),
                    [
                        {"device_id": device_id, "bucket_start": bucket.start, **rollup_values(bucket)}
                        for (device_id, _), bucket in fresh.items()
                    ],
                )
                written += len(fresh)

            # Exactly the rows read above: they were the lowest ids before the
            # cutoff. Deleting them here, in the same transaction, is what
            # makes a second run find nothing left to roll up.
            connection.execute(
                delete(SAMPLES).where(SAMPLES.c.ts < cutoff, SAMPLES.c.id <= rows[-1].id)
            )
            rolled_up += len(rows)

        if len(rows) == ROLLUP_BATCH_SIZE:  # a full batch: there may be more
            time.sleep(ROLLUP_BATCH_PAUSE_SECONDS)


def run_retention(now: datetime | None = None) -> RetentionReport:
    """Run one retention pass. Synchronous; safe to run again at any time."""
    now = now or datetime.now(timezone.utc)

    # Rounded down to a whole minute, so a minute is only rolled up once all of
    # it is older than the cutoff.
    raw_cutoff = bucket_start(now - timedelta(hours=settings.RAW_RETENTION_HOURS), MINUTE)
    samples_rolled_up, rollup_rows_written = _roll_up_samples_before(raw_cutoff)

    with engine.begin() as connection:
        rollups_deleted = connection.execute(
            delete(ROLLUPS).where(
                ROLLUPS.c.bucket_start < now - timedelta(days=settings.ROLLUP_RETENTION_DAYS)
            )
        ).rowcount
        transitions_deleted = connection.execute(
            delete(TRANSITIONS).where(
                TRANSITIONS.c.ts < now - timedelta(days=settings.TRANSITION_RETENTION_DAYS)
            )
        ).rowcount

    return RetentionReport(
        samples_rolled_up=samples_rolled_up,
        rollup_rows_written=rollup_rows_written,
        rollups_deleted=rollups_deleted,
        transitions_deleted=transitions_deleted,
    )


async def run_retention_loop(
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run the retention job now, then every ``RETENTION_INTERVAL_SECONDS``.

    The job itself runs in a worker thread, so it never blocks the event loop
    (and the poll loop running on it). ``sleep`` is a parameter only so tests
    can step the loop without waiting.
    """
    while True:
        try:
            report = await asyncio.to_thread(run_retention)
            # Keep the in-memory flap store in step with the table.
            flap_store.forget_before(
                datetime.now(timezone.utc) - timedelta(days=settings.TRANSITION_RETENTION_DAYS)
            )
            logger.info("Retention run complete: %s", report)
        except Exception:
            logger.error("Retention run failed; will try again next time", exc_info=True)

        await sleep(settings.RETENTION_INTERVAL_SECONDS)
