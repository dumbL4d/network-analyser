"""Background task that periodically pings every device and stores the result."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import partial

from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import engine
from app.models.device import Device
from app.models.settings import AppSettings
from app.services.anomaly.registry import (
    AnomalyConfig,
    AnomalyEnd,
    AnomalyStart,
    anomaly_registry,
)
from app.services.debounce import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RECOVERY_THRESHOLD,
    debouncer,
    is_suspect,
)
from app.services.flap_store import Transition, flap_store
from app.services.history_store import history_store
from app.services.incident_tracker import incident_tracker
from app.services.persistence import persist_cycle
from app.services.ping_engine import (
    DEFAULT_JITTER_WARN_MS,
    DEFAULT_LOSS_WARN_PCT,
    DEFAULT_PING_GAP_MS,
    DEFAULT_PINGS_PER_CYCLE,
    DeviceStatus,
    PingFn,
    ping_all,
    staggered_ping,
)
from app.services.poll_health import poll_health, stale_after_seconds
from app.services.status_store import status_store

logger = logging.getLogger(__name__)

# How long after a pass the devices it left suspect are probed again. What
# Nagios calls retry_interval: a failure is confirmed at this pace, not at
# that of the poll interval.
RETRY_INTERVAL_SECONDS = 1.0


def _load_devices() -> list[tuple[str, str]]:
    with Session(engine) as session:
        devices = session.exec(select(Device)).all()
        return [(device.id, device.ip) for device in devices]


async def _store(
    samples: list[DeviceStatus],
    transitions: list[Transition],
    anomalies_started: Sequence[AnomalyStart],
    anomalies_ended: Sequence[AnomalyEnd],
    confirmed: list[DeviceStatus],
) -> None:
    """Write one pass to the database, then open, update or resolve the
    stored incidents. Each in a worker thread, off the event loop, and a
    failure of either is logged and goes no further."""
    try:
        # One transaction per pass.
        await asyncio.to_thread(
            persist_cycle, samples, transitions, anomalies_started, anomalies_ended
        )
    except Exception:
        logger.error(
            "Could not save this poll cycle to the database; live "
            "status is unaffected",
            exc_info=True,
        )
    try:
        await asyncio.to_thread(incident_tracker.track, confirmed)
    except Exception:
        logger.error(
            "Could not update the stored incidents for this poll cycle",
            exc_info=True,
        )


async def run_poll_loop(
    ping: PingFn = staggered_ping,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    retry_interval: float | None = RETRY_INTERVAL_SECONDS,
) -> None:
    """Ping all devices forever, publishing each snapshot to the status store.

    Fixed rate: a cycle starts one poll interval after the cycle before it
    STARTED, however long that one took (at once, if it took longer than the
    interval). So the interval is the period of the polling, not a pause added
    to the time the pings take.

    The monitoring-behavior values (poll interval, how many probes per cycle,
    the latency, loss and jitter thresholds and the debounce thresholds) are
    re-read from the DB-backed ``AppSettings``
    singleton at the START of every iteration, so admin edits take effect
    within one cycle without a backend restart. Timeout and privileged mode
    remain low-level concerns read from the static .env-backed ``Settings``
    object.

    Each cycle's raw readings first go to the anomaly detectors, which only
    add what they find to a reading (advisory: no status is changed), and then
    through the debouncer. The status store and the flap store receive the
    CONFIRMED statuses; the history store keeps the raw readings. The cycle is
    then written to the database (one sample per device plus any status
    transitions and anomaly events), and the incident tracker opens, updates
    or resolves the stored incidents. Both run in a worker thread, so they
    never block the event loop. A cycle that gets that far is noted as
    completed, which is what the health endpoint judges the freshness of the
    statuses by (see ``app.services.poll_health``).

    Retry on suspect: a device whose result is worse than its confirmed status
    (see ``app.services.debounce``) is probed again ``retry_interval`` seconds
    later, and again, for as long as it stays suspect and the next cycle is
    not due. A retry goes through the debouncer like any result, so it can
    confirm the failure: the status, the transition and the incident follow
    at once. It is left out of everything that expects one reading per cycle:
    no sample is stored, and the history store and the anomaly detectors
    never see it.

    ``ping``, ``sleep`` and ``clock`` default to the real ICMP ping,
    ``asyncio.sleep`` and the monotonic clock. They are parameters only so
    tests can inject fakes and step the loop without sending packets or
    waiting. ``retry_interval=None`` switches the retries off.
    """
    logger.info(
        "Status poll loop started (interval=%ss)",
        settings.PING_INTERVAL_SECONDS,
    )
    # Fallback used until the first row read succeeds (and after any error).
    interval = settings.PING_INTERVAL_SECONDS
    # From here on a cycle is expected: the health endpoint says so when none
    # completes in time (see app.services.poll_health).
    poll_health.started(
        stale_after_seconds(
            interval, DEFAULT_PINGS_PER_CYCLE, DEFAULT_PING_GAP_MS, settings.PING_TIMEOUT_SECONDS
        )
    )

    while True:
        cycle_started = clock()
        try:
            # Singleton row (see AppSettings docstring): no magic id, ever.
            with Session(engine) as session:
                app_settings = session.exec(select(AppSettings)).first()

            if app_settings is None:
                logger.warning(
                    "AppSettings row missing; using .env defaults for this cycle"
                )
                interval = settings.PING_INTERVAL_SECONDS
                warn_threshold = settings.LATENCY_WARN_MS
                crit_threshold = settings.LATENCY_CRIT_MS
                failure_threshold = DEFAULT_FAILURE_THRESHOLD
                recovery_threshold = DEFAULT_RECOVERY_THRESHOLD
                pings = DEFAULT_PINGS_PER_CYCLE
                gap_ms = DEFAULT_PING_GAP_MS
                loss_warn_pct = DEFAULT_LOSS_WARN_PCT
                jitter_warn_ms = DEFAULT_JITTER_WARN_MS
                anomaly_config = AnomalyConfig()
            else:
                interval = app_settings.poll_interval_seconds
                warn_threshold = app_settings.latency_warn_ms
                crit_threshold = app_settings.latency_crit_ms
                failure_threshold = app_settings.failure_threshold
                recovery_threshold = app_settings.recovery_threshold
                pings = app_settings.pings_per_cycle
                gap_ms = app_settings.ping_gap_ms
                loss_warn_pct = app_settings.loss_warn_pct
                jitter_warn_ms = app_settings.jitter_warn_ms
                anomaly_config = AnomalyConfig(
                    enabled=app_settings.anomaly_enabled,
                    detector=app_settings.anomaly_detector,
                    k=app_settings.anomaly_k,
                    m=app_settings.anomaly_m,
                    alpha=app_settings.anomaly_alpha,
                    window=app_settings.anomaly_window,
                )

            stale_after = stale_after_seconds(
                interval, pings, gap_ms, settings.PING_TIMEOUT_SECONDS
            )
            poll_health.cycle_running(stale_after)

            devices = _load_devices()
            probe = partial(
                ping_all,
                timeout=settings.PING_TIMEOUT_SECONDS,
                privileged=settings.PING_PRIVILEGED,
                warn_threshold=warn_threshold,
                crit_threshold=crit_threshold,
                ping=ping,
                pings=pings,
                gap_seconds=gap_ms / 1000,
                loss_warn_pct=loss_warn_pct,
                jitter_warn_ms=jitter_warn_ms,
            )
            results = await probe(devices)
            # Advisory: the detectors add what they find unusual to a reading
            # and leave its status alone.
            results, anomalies_started, anomalies_ended = anomaly_registry.observe(
                results, anomaly_config
            )
            # `results` are this cycle's raw readings. The debouncer works out
            # each device's confirmed status, and forgets devices that were not
            # polled this cycle (deleted ones).
            confirmed = debouncer.apply(results, failure_threshold, recovery_threshold)
            status_store.update(confirmed)
            history_store.record(results)  # raw readings, for the latency charts
            # A flap is a CONFIRMED status change.
            transitions = flap_store.record(confirmed)
            await _store(confirmed, transitions, anomalies_started, anomalies_ended, confirmed)
            logger.info(
                "Status poll complete for %d devices (interval=%ss)",
                len(results),
                interval,
            )
            # Only a cycle that got this far counts: a failed one leaves the
            # statuses on screen as old as they were.
            poll_health.cycle_completed(stale_after)

            # Retry on suspect, until none is left or the next cycle is due.
            latest = {reading.device_id: reading for reading in confirmed}
            while retry_interval is not None:
                if not any(map(is_suspect, latest.values())):
                    break
                if clock() + retry_interval >= cycle_started + interval:
                    break
                await sleep(retry_interval)
                # Read again: since the cycle a device may have been deleted,
                # or given the address that the admin hopes will answer.
                addresses = dict(_load_devices())
                latest = {
                    device_id: reading
                    for device_id, reading in latest.items()
                    if device_id in addresses
                }
                suspects = [
                    (device_id, addresses[device_id])
                    for device_id, reading in latest.items()
                    if is_suspect(reading)
                ]
                if not suspects:
                    break
                retried = debouncer.apply(
                    [
                        # No detector sees a retry: what they found stays as it is.
                        reading.model_copy(update={"anomaly": latest[reading.device_id].anomaly})
                        for reading in await probe(suspects)
                    ],
                    failure_threshold,
                    recovery_threshold,
                    retry=True,
                )
                status_store.update(retried)
                latest.update((reading.device_id, reading) for reading in retried)
                transitions = flap_store.record(retried)
                if transitions:
                    # No sample: the history holds one reading per cycle.
                    await _store([], transitions, (), (), list(latest.values()))
                logger.info("Retried %d suspect device(s)", len(suspects))
        except Exception:
            logger.error("Status poll iteration failed; continuing", exc_info=True)

        # Fixed rate: counted from the start of this cycle, not from its end.
        await sleep(max(0.0, cycle_started + interval - clock()))
