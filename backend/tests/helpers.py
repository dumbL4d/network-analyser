"""Plain helpers shared by the test modules (fixtures live in conftest.py)."""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.config import settings
from app.models.device import Device
from app.services.ping_engine import DeviceStatus, PingFn, StatusKey
from app.services.poll_loop import run_poll_loop


def make_status(
    device_id: str, status: StatusKey, latency_ms: float | None = None
) -> DeviceStatus:
    return DeviceStatus(
        device_id=device_id,
        status=status,
        latency_ms=latency_ms,
        timestamp=datetime.now(timezone.utc),
    )


def seed_devices() -> list[Device]:
    """The warehouse tree from ``infra/devices.seed.json`` as plain ``Device``
    objects, in file order. No database involved."""
    items = json.loads(Path(str(settings.SEED_PATH)).read_text())
    return [
        Device(
            id=item["id"],
            name=item["name"],
            type=item["type"],
            ip=item["ip"],
            zone=item["zone"],
            parent_id=item["parentId"],
        )
        for item in items
    ]


def ip_of(device_id: str) -> str:
    """The seeded IP address of a device (the fake ping is keyed by IP)."""
    return next(device.ip for device in seed_devices() if device.id == device_id)


class FakePing:
    """Drop-in for ``icmplib.async_ping`` that never sends a packet.

    ``outcomes`` maps an IP address to what the probe does for it: either
    ``(is_alive, avg_rtt)`` or an exception to raise. Addresses that are not
    listed get ``default``. Every call is recorded in ``calls`` as
    ``(address, keyword_arguments)``.
    """

    def __init__(self, default: tuple[bool, float | None] = (True, 1.0)) -> None:
        self.default = default
        self.outcomes: dict[str, tuple[bool, float | None] | Exception] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, address: str, **kwargs: Any) -> SimpleNamespace:
        self.calls.append((address, kwargs))
        outcome = self.outcomes.get(address, self.default)
        if isinstance(outcome, Exception):
            raise outcome
        is_alive, avg_rtt = outcome
        return SimpleNamespace(is_alive=is_alive, avg_rtt=avg_rtt)


class _StopLoop(BaseException):
    """Raised by the fake sleep to end ``run_poll_loop``. A ``BaseException``,
    so the loop's own ``except Exception`` can never swallow it."""


async def run_cycles(
    n: int, ping: PingFn, after_cycle: Callable[[int], None] | None = None
) -> list[float]:
    """Run the REAL poll loop for exactly ``n`` cycles, without waiting.

    The loop calls the injected sleep once per cycle, after the stores have
    been updated. ``after_cycle(k)`` (1-based) runs at that moment, so a test
    can change settings or probe outcomes "while the loop sleeps". Returns the
    interval, in seconds, that the loop asked to sleep after each cycle.
    """
    intervals: list[float] = []

    async def fake_sleep(delay: float) -> None:
        intervals.append(delay)
        if after_cycle is not None:
            after_cycle(len(intervals))
        if len(intervals) >= n:
            raise _StopLoop

    try:
        await run_poll_loop(ping=ping, sleep=fake_sleep)
    except _StopLoop:
        pass
    return intervals
