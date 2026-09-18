"""Manual, on-demand smoke test for the ping engine.

This is a permanent developer utility, NOT part of the pytest suite.

Usage (from the ``backend/`` directory):

    python scripts/manual_ping_test.py

Reads the seeded devices from the SQLite database and pings them all
concurrently, printing a status table.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.models.device import Device  # noqa: E402
from app.models.settings import AppSettings  # noqa: E402
from app.services.ping_engine import ping_all  # noqa: E402


def load_devices() -> list[tuple[str, str]]:
    session_gen = get_session()
    session = next(session_gen)
    try:
        devices = session.exec(select(Device)).all()
        return [(device.id, device.ip) for device in devices]
    finally:
        session_gen.close()


def load_latency_thresholds() -> tuple[float, float]:
    """Read the live DB-backed thresholds, falling back to .env defaults.

    Mirrors the poll loop's behavior: the singleton AppSettings row is the
    source of truth, but a missing row (pre-seed DB) falls back to the static
    config values.
    """
    session_gen = get_session()
    session = next(session_gen)
    try:
        row = session.exec(select(AppSettings)).first()
    finally:
        session_gen.close()
    if row is None:
        return settings.LATENCY_WARN_MS, settings.LATENCY_CRIT_MS
    return row.latency_warn_ms, row.latency_crit_ms


async def main() -> None:
    devices = load_devices()
    warn_threshold, crit_threshold = load_latency_thresholds()
    results = await ping_all(
        devices,
        timeout=settings.PING_TIMEOUT_SECONDS,
        privileged=settings.PING_PRIVILEGED,
        warn_threshold=warn_threshold,
        crit_threshold=crit_threshold,
    )

    print(
        f"PING_PRIVILEGED={settings.PING_PRIVILEGED} "
        f"timeout={settings.PING_TIMEOUT_SECONDS}s "
        f"warn={warn_threshold}ms crit={crit_threshold}ms"
    )
    print(f"{'device_id':<16}{'status':<10}{'latency_ms'}")
    print("-" * 40)
    for result in results:
        latency = "-" if result.latency_ms is None else f"{result.latency_ms:.2f}"
        print(f"{result.device_id:<16}{result.status:<10}{latency}")


if __name__ == "__main__":
    asyncio.run(main())
