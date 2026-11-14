"""Database storage for monitoring data.

Three jobs:

* the write path: after every poll cycle, store that cycle's samples and
  status transitions in ONE transaction (``persist_cycle``);
* the warm-up: at startup, refill the in-memory stores from the database, so
  history, flap counts and debounce state survive a restart (``warm_caches``);
* windowed history reads for the charts (``history_window``).

Everything here is synchronous, like the rest of the database code. The poll
loop and the retention job call it through ``asyncio.to_thread`` so the event
loop is never blocked; request handlers already run in worker threads.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select

from app.core.config import settings
from app.db.session import engine
from app.models.device import Device
from app.models.settings import AppSettings
from app.models.telemetry import LatencyRollup1m, LatencySample, StatusTransition
from app.schemas.history import HistoryPointOut, HistoryWindowOut
from app.services.debounce import MAX_THRESHOLD, debouncer, state_from_history
from app.services.flap_store import Transition, flap_store
from app.services.history_store import HistorySample, history_store
from app.services.ping_engine import DeviceStatus
from app.services.rollup import MINUTE, Bucket, rebucket, sample_bucket

SAMPLES = LatencySample.__table__
ROLLUPS = LatencyRollup1m.__table__
TRANSITIONS = StatusTransition.__table__

# window -> (how far back it reaches, bucket size in seconds or None for raw).
# The bucket sizes keep every window at roughly 300-360 points per device.
WINDOWS: dict[str, tuple[timedelta, int | None]] = {
    "1h": (timedelta(hours=1), None),
    "6h": (timedelta(hours=6), MINUTE),
    "24h": (timedelta(hours=24), 5 * MINUTE),
    "7d": (timedelta(days=7), 30 * MINUTE),
    "30d": (timedelta(days=30), 120 * MINUTE),
}
RESOLUTION_LABELS = {MINUTE: "1m", 5 * MINUTE: "5m", 30 * MINUTE: "30m", 120 * MINUTE: "2h"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- write path ----------------------------------------------------------------


def persist_cycle(readings: list[DeviceStatus], transitions: list[Transition]) -> None:
    """Store one poll cycle: a sample per device and every confirmed status
    change, in ONE transaction (all of it is saved, or none of it)."""
    samples = [
        {
            "device_id": reading.device_id,
            "ts": reading.timestamp,
            "latency_ms": reading.latency_ms,
            "raw_status": reading.raw_status or reading.status,
            "confirmed_status": reading.status,
        }
        for reading in readings
    ]
    changes = [
        {
            "device_id": transition.device_id,
            "ts": transition.timestamp,
            "from_status": transition.from_status,
            "to_status": transition.to_status,
        }
        for transition in transitions
    ]
    if not samples and not changes:
        return
    with engine.begin() as connection:
        if samples:
            connection.execute(insert(SAMPLES), samples)
        if changes:
            connection.execute(insert(TRANSITIONS), changes)


# --- warm-up at startup ----------------------------------------------------------


def warm_caches(now: datetime | None = None) -> None:
    """Refill the in-memory stores from the database.

    * history store: each device's most recent samples;
    * flap store: each device's last confirmed status, and its status changes
      inside the flap window (``TRANSITION_RETENTION_DAYS``);
    * debouncer: each device's state, but only if its last sample is recent
      (within the ``MAX_THRESHOLD`` polls the debouncer remembers). After a
      longer gap the old streak means nothing, and the device's next result is
      accepted as a first result.
    """
    now = now or _now()
    last_status: dict[str, str] = {}
    changes: dict[str, list[datetime]] = {}
    states = {}

    with engine.connect() as connection:
        poll_interval = connection.execute(
            select(AppSettings.__table__.c.poll_interval_seconds)
        ).scalar()
        fresh_for = timedelta(
            seconds=MAX_THRESHOLD * (poll_interval or settings.PING_INTERVAL_SECONDS)
        )
        keep = max(settings.HISTORY_MAX_SAMPLES, MAX_THRESHOLD)

        for device_id in connection.execute(select(Device.__table__.c.id)).scalars().all():
            # Newest first, so the (device_id, ts) index makes this a short scan.
            newest_first = connection.execute(
                select(SAMPLES.c.ts, SAMPLES.c.latency_ms, SAMPLES.c.raw_status, SAMPLES.c.confirmed_status)
                .where(SAMPLES.c.device_id == device_id)
                .order_by(SAMPLES.c.ts.desc())
                .limit(keep)
            ).all()
            if not newest_first:
                continue
            rows = newest_first[::-1]
            history_store.load(
                device_id, [HistorySample(latency_ms=row.latency_ms, timestamp=row.ts) for row in rows]
            )
            last_status[device_id] = rows[-1].confirmed_status
            if now - rows[-1].ts <= fresh_for:
                states[device_id] = state_from_history(
                    rows[-1].confirmed_status, [row.raw_status for row in rows]
                )

        flap_since = now - timedelta(days=settings.TRANSITION_RETENTION_DAYS)
        for device_id, ts in connection.execute(
            select(TRANSITIONS.c.device_id, TRANSITIONS.c.ts)
            .where(TRANSITIONS.c.ts >= flap_since)
            .order_by(TRANSITIONS.c.ts)
        ):
            changes.setdefault(device_id, []).append(ts)

    flap_store.restore(last_status, changes)
    debouncer.restore(states)


# --- windowed history ------------------------------------------------------------


def history_window(device_id: str, window: str, now: datetime | None = None) -> HistoryWindowOut:
    """Latency history of one device over ``window`` (a key of ``WINDOWS``).

    The resolution is chosen by the window. "1h" returns the raw samples. The
    longer windows return time buckets (min / avg / max), built from the
    1-minute rollups plus the raw samples that have not been rolled up yet.
    """
    span, bucket_seconds = WINDOWS[window]
    if bucket_seconds is None and span > timedelta(hours=settings.RAW_RETENTION_HOURS):
        # Raw samples do not reach that far back with this configuration.
        bucket_seconds = MINUTE
    since = (now or _now()) - span

    with engine.connect() as connection:
        samples = connection.execute(
            select(SAMPLES.c.ts, SAMPLES.c.latency_ms)
            .where(SAMPLES.c.device_id == device_id, SAMPLES.c.ts >= since)
            .order_by(SAMPLES.c.ts)
        ).all()
        rollups = (
            []
            if bucket_seconds is None
            else connection.execute(
                select(ROLLUPS).where(
                    ROLLUPS.c.device_id == device_id, ROLLUPS.c.bucket_start >= since
                )
            ).all()
        )

    if bucket_seconds is None:
        points = [
            HistoryPointOut(
                timestamp=ts,
                latency_ms=latency_ms,
                min_ms=latency_ms,
                max_ms=latency_ms,
                sample_count=1,
                fail_count=int(latency_ms is None),
            )
            for ts, latency_ms in samples
        ]
    else:
        buckets = [
            Bucket(row.bucket_start, row.min, row.avg, row.max, row.sample_count, row.fail_count)
            for row in rollups
        ]
        buckets += [sample_bucket(ts, latency_ms) for ts, latency_ms in samples]
        points = [
            HistoryPointOut(
                timestamp=bucket.start,
                latency_ms=bucket.avg_ms,
                min_ms=bucket.min_ms,
                max_ms=bucket.max_ms,
                sample_count=bucket.sample_count,
                fail_count=bucket.fail_count,
            )
            for bucket in rebucket(buckets, bucket_seconds)
        ]

    return HistoryWindowOut(
        device_id=device_id,
        window=window,
        resolution="raw" if bucket_seconds is None else RESOLUTION_LABELS[bucket_seconds],
        resolution_seconds=bucket_seconds,
        points=points,
    )
