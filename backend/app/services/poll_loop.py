"""Background task that periodically pings every device and stores the result."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from icmplib import async_ping
from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import engine
from app.models.device import Device
from app.models.settings import AppSettings
from app.services.debounce import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RECOVERY_THRESHOLD,
    debouncer,
)
from app.services.flap_store import flap_store
from app.services.history_store import history_store
from app.services.incident_tracker import incident_tracker
from app.services.persistence import persist_cycle
from app.services.ping_engine import PingFn, ping_all
from app.services.status_store import status_store

logger = logging.getLogger(__name__)


def _load_devices() -> list[tuple[str, str]]:
    with Session(engine) as session:
        devices = session.exec(select(Device)).all()
        return [(device.id, device.ip) for device in devices]


async def run_poll_loop(
    ping: PingFn = async_ping,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Ping all devices forever, publishing each snapshot to the status store.

    The monitoring-behavior values (poll interval, latency thresholds and the
    debounce thresholds) are re-read from the DB-backed ``AppSettings``
    singleton at the START of every iteration, so admin edits take effect
    within one cycle without a backend restart. Timeout and privileged mode
    remain low-level concerns read from the static .env-backed ``Settings``
    object.

    Each cycle's raw readings go through the debouncer. The status store and
    the flap store receive the CONFIRMED statuses; the history store keeps the
    raw readings. The cycle is then written to the database (one sample per
    device plus any status transitions), and the incident tracker opens,
    updates or resolves the stored incidents. Both run in a worker thread, so
    they never block the event loop.

    ``ping`` and ``sleep`` default to the real ICMP ping and ``asyncio.sleep``.
    They are parameters only so tests can inject fakes and step the loop one
    cycle at a time without sending packets or waiting.
    """
    logger.info(
        "Status poll loop started (interval=%ss)",
        settings.PING_INTERVAL_SECONDS,
    )
    # Fallback used until the first row read succeeds (and after any error).
    interval = settings.PING_INTERVAL_SECONDS

    while True:
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
            else:
                interval = app_settings.poll_interval_seconds
                warn_threshold = app_settings.latency_warn_ms
                crit_threshold = app_settings.latency_crit_ms
                failure_threshold = app_settings.failure_threshold
                recovery_threshold = app_settings.recovery_threshold

            devices = _load_devices()
            results = await ping_all(
                devices,
                timeout=settings.PING_TIMEOUT_SECONDS,
                privileged=settings.PING_PRIVILEGED,
                warn_threshold=warn_threshold,
                crit_threshold=crit_threshold,
                ping=ping,
            )
            # `results` are this cycle's raw readings. The debouncer works out
            # each device's confirmed status, and forgets devices that were not
            # polled this cycle (deleted ones).
            confirmed = debouncer.apply(results, failure_threshold, recovery_threshold)
            status_store.update(confirmed)
            history_store.record(results)  # raw readings, for the latency charts
            # A flap is a CONFIRMED status change.
            transitions = flap_store.record(confirmed)
            try:
                # One transaction per cycle, off the event loop.
                await asyncio.to_thread(persist_cycle, confirmed, transitions)
            except Exception:
                logger.error(
                    "Could not save this poll cycle to the database; live "
                    "status is unaffected",
                    exc_info=True,
                )
            try:
                # Open, update or resolve the stored incidents for this cycle.
                await asyncio.to_thread(incident_tracker.track, confirmed)
            except Exception:
                logger.error(
                    "Could not update the stored incidents for this poll cycle",
                    exc_info=True,
                )
            logger.info(
                "Status poll complete for %d devices (interval=%ss)",
                len(results),
                interval,
            )
        except Exception:
            logger.error("Status poll iteration failed; continuing", exc_info=True)

        await sleep(interval)
