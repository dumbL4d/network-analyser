"""Database storage for monitoring data.

Three jobs:

* the write path: after every poll cycle, store that cycle's samples, status
  transitions and anomaly events in ONE transaction (``persist_cycle``);
* the warm-up: at startup, refill the in-memory stores from the database, so
  history, flap counts and debounce state survive a restart (``warm_caches``);
* reads for the charts: windowed history (``history_window``) and the recent
  anomaly events (``recent_anomalies``).

Everything here is synchronous, like the rest of the database code. The poll
loop and the retention job call it through ``asyncio.to_thread`` so the event
loop is never blocked; request handlers already run in worker threads.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update

from app.core.config import settings
from app.db.session import engine
from app.models.anomaly import AnomalyEvent
from app.models.device import Device
from app.models.settings import AppSettings
from app.models.telemetry import LatencyRollup1m, LatencySample, StatusTransition
from app.schemas.history import HistoryPointOut, HistoryWindowOut
from app.services.anomaly.registry import AnomalyEnd, AnomalyStart
from app.services.debounce import MAX_THRESHOLD, debouncer, state_from_history
from app.services.flap_store import Transition, flap_store
from app.services.history_store import HistorySample, history_store
from app.services.ping_engine import DeviceStatus
from app.services.rollup import MINUTE, Bucket, rebucket, sample_bucket

SAMPLES = LatencySample.__table__
ROLLUPS = LatencyRollup1m.__table__
TRANSITIONS = StatusTransition.__table__
ANOMALIES = AnomalyEvent.__table__

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


def rollup_bucket(row) -> Bucket:
    """A ``latency_rollup_1m`` row as a ``Bucket``."""
    return Bucket(
        start=row.bucket_start,
        min_ms=row.min,
        avg_ms=row.avg,
        max_ms=row.max,
        sample_count=row.sample_count,
        fail_count=row.fail_count,
        loss_avg=row.loss_avg,
        loss_max=row.loss_max,
        loss_count=row.loss_count,
        jitter_avg=row.jitter_avg,
        jitter_max=row.jitter_max,
        jitter_count=row.jitter_count,
    )


def rollup_values(bucket: Bucket) -> dict:
    """The ``latency_rollup_1m`` columns a ``Bucket`` is stored in."""
    return {
        "min": bucket.min_ms,
        "avg": bucket.avg_ms,
        "max": bucket.max_ms,
        "sample_count": bucket.sample_count,
        "fail_count": bucket.fail_count,
        "loss_avg": bucket.loss_avg,
        "loss_max": bucket.loss_max,
        "loss_count": bucket.loss_count,
        "jitter_avg": bucket.jitter_avg,
        "jitter_max": bucket.jitter_max,
        "jitter_count": bucket.jitter_count,
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- write path ----------------------------------------------------------------


def persist_cycle(
    readings: list[DeviceStatus],
    transitions: list[Transition],
    anomalies_started: Sequence[AnomalyStart] = (),
    anomalies_ended: Sequence[AnomalyEnd] = (),
) -> None:
    """Store one poll cycle: a sample per device, every confirmed status
    change, and the anomalies that began or ended, in ONE transaction (all of
    it is saved, or none of it)."""
    samples = [
        {
            "device_id": reading.device_id,
            "ts": reading.timestamp,
            "latency_ms": reading.latency_ms,
            "raw_status": reading.raw_status or reading.status,
            "confirmed_status": reading.status,
            "loss_pct": reading.loss_pct,
            "jitter_ms": reading.jitter_ms,
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
    if not (samples or changes or anomalies_started or anomalies_ended):
        return
    with engine.begin() as connection:
        if samples:
            connection.execute(insert(SAMPLES), samples)
        if changes:
            connection.execute(insert(TRANSITIONS), changes)
        # Ends before starts: an anomaly that ends closes the event that is
        # open, never one that begins in this same cycle.
        for end in anomalies_ended:
            connection.execute(
                update(ANOMALIES)
                .where(
                    ANOMALIES.c.device_id == end.device_id,
                    ANOMALIES.c.metric == end.metric,
                    ANOMALIES.c.ended_at.is_(None),
                )
                .values(ended_at=end.at)
            )
        if anomalies_started:
            connection.execute(
                insert(ANOMALIES),
                [
                    {
                        "device_id": start.device_id,
                        "metric": start.metric,
                        "detector": start.detector,
                        "started_at": start.at,
                        "value": start.value,
                        "expected": start.expected,
                        "score": start.score,
                    }
                    for start in anomalies_started
                ],
            )


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

    A device's confirmed status is the one of its last sample, unless a status
    change was stored after it: the retry of a suspect device can confirm a
    status and stores the change, but no sample (see app/services/poll_loop.py).
    """
    now = now or _now()
    last_status: dict[str, str] = {}
    changes: dict[str, list[datetime]] = {}
    # device -> (when, to which status) of its latest stored change.
    last_change: dict[str, tuple[datetime, str]] = {}
    states = {}

    with engine.connect() as connection:
        flap_since = now - timedelta(days=settings.TRANSITION_RETENTION_DAYS)
        for device_id, ts, to_status in connection.execute(
            select(TRANSITIONS.c.device_id, TRANSITIONS.c.ts, TRANSITIONS.c.to_status)
            .where(TRANSITIONS.c.ts >= flap_since)
            .order_by(TRANSITIONS.c.ts)
        ):
            changes.setdefault(device_id, []).append(ts)
            last_change[device_id] = (ts, to_status)

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
                select(
                    SAMPLES.c.ts,
                    SAMPLES.c.latency_ms,
                    SAMPLES.c.raw_status,
                    SAMPLES.c.confirmed_status,
                    SAMPLES.c.loss_pct,
                    SAMPLES.c.jitter_ms,
                )
                .where(SAMPLES.c.device_id == device_id)
                .order_by(SAMPLES.c.ts.desc())
                .limit(keep)
            ).all()
            if not newest_first:
                continue
            rows = newest_first[::-1]
            history_store.load(
                device_id,
                [HistorySample(row.latency_ms, row.ts, row.loss_pct, row.jitter_ms) for row in rows],
            )
            confirmed = rows[-1].confirmed_status
            changed_at, changed_to = last_change.get(device_id, (rows[-1].ts, confirmed))
            if changed_at > rows[-1].ts:
                confirmed = changed_to  # confirmed by a retry, after the last sample
            last_status[device_id] = confirmed
            if now - rows[-1].ts <= fresh_for:
                # The first sample of the run of failures at the end, if any.
                failing_since = None
                for row in reversed(rows):
                    if row.raw_status == "healthy":
                        break
                    failing_since = row.ts
                states[device_id] = state_from_history(
                    confirmed, [row.raw_status for row in rows], failing_since
                )

    flap_store.restore(last_status, changes)
    debouncer.restore(states)
    close_open_anomalies(now)


def close_open_anomalies(now: datetime | None = None) -> None:
    """End every anomaly event that is still open.

    The detectors live in memory and start afresh with the backend, so after
    a restart no anomaly is "in progress" any more. An open event is given
    the time of the newest stored sample as its end: the last moment anything
    was measured.
    """
    with engine.begin() as connection:
        newest_sample = connection.execute(select(func.max(SAMPLES.c.ts))).scalar()
        connection.execute(
            update(ANOMALIES)
            .where(ANOMALIES.c.ended_at.is_(None))
            .values(ended_at=newest_sample or now or _now())
        )


def recent_anomalies(device_id: str | None = None, limit: int = 50) -> list:
    """The most recent anomaly events, newest first; of one device if
    ``device_id`` is given."""
    query = select(ANOMALIES).order_by(ANOMALIES.c.started_at.desc(), ANOMALIES.c.id.desc()).limit(limit)
    if device_id is not None:
        query = query.where(ANOMALIES.c.device_id == device_id)
    with engine.connect() as connection:
        return list(connection.execute(query).all())


# --- windowed history ------------------------------------------------------------


def history_window(device_id: str, window: str, now: datetime | None = None) -> HistoryWindowOut:
    """Latency, packet loss and jitter history of one device over ``window``
    (a key of ``WINDOWS``).

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
            select(SAMPLES.c.ts, SAMPLES.c.latency_ms, SAMPLES.c.loss_pct, SAMPLES.c.jitter_ms)
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
                loss_pct=loss,
                loss_max_pct=loss,
                jitter_ms=jitter,
                jitter_max_ms=jitter,
            )
            for ts, latency_ms, loss, jitter in samples
        ]
    else:
        buckets = [rollup_bucket(row) for row in rollups]
        buckets += [
            sample_bucket(ts, latency_ms, loss_pct=loss, jitter_ms=jitter)
            for ts, latency_ms, loss, jitter in samples
        ]
        points = [
            HistoryPointOut(
                timestamp=bucket.start,
                latency_ms=bucket.avg_ms,
                min_ms=bucket.min_ms,
                max_ms=bucket.max_ms,
                sample_count=bucket.sample_count,
                fail_count=bucket.fail_count,
                loss_pct=bucket.loss_avg,
                loss_max_pct=bucket.loss_max,
                jitter_ms=bucket.jitter_avg,
                jitter_max_ms=bucket.jitter_max,
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
