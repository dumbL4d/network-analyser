"""Background task that periodically pings every device and stores the result."""

import asyncio
import logging

from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import engine
from app.models.device import Device
from app.services.history_store import history_store
from app.services.ping_engine import ping_all
from app.services.status_store import status_store

logger = logging.getLogger(__name__)


def _load_devices() -> list[tuple[str, str]]:
    with Session(engine) as session:
        devices = session.exec(select(Device)).all()
        return [(device.id, device.ip) for device in devices]


async def run_poll_loop() -> None:
    """Ping all devices forever, publishing each snapshot to the status store."""
    logger.info(
        "Status poll loop started (interval=%ss)", settings.PING_INTERVAL_SECONDS
    )

    while True:
        try:
            devices = _load_devices()
            results = await ping_all(
                devices,
                timeout=settings.PING_TIMEOUT_SECONDS,
                privileged=settings.PING_PRIVILEGED,
            )
            status_store.update(results)
            history_store.record(results)
            logger.info("Status poll complete for %d devices", len(results))
        except Exception:
            logger.error("Status poll iteration failed; continuing", exc_info=True)

        await asyncio.sleep(settings.PING_INTERVAL_SECONDS)
