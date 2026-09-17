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
from app.services.ping_engine import ping_all  # noqa: E402


def load_devices() -> list[tuple[str, str]]:
    session_gen = get_session()
    session = next(session_gen)
    try:
        devices = session.exec(select(Device)).all()
        return [(device.id, device.ip) for device in devices]
    finally:
        session_gen.close()


async def main() -> None:
    devices = load_devices()
    results = await ping_all(
        devices,
        timeout=settings.PING_TIMEOUT_SECONDS,
        privileged=settings.PING_PRIVILEGED,
    )

    print(
        f"PING_PRIVILEGED={settings.PING_PRIVILEGED} "
        f"timeout={settings.PING_TIMEOUT_SECONDS}s"
    )
    print(f"{'device_id':<16}{'status':<10}{'latency_ms'}")
    print("-" * 40)
    for result in results:
        latency = "-" if result.latency_ms is None else f"{result.latency_ms:.2f}"
        print(f"{result.device_id:<16}{result.status:<10}{latency}")


if __name__ == "__main__":
    asyncio.run(main())
