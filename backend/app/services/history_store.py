"""In-memory rolling latency history per device.

This is deliberately session-only: nothing here is persisted to SQLite, so the
history resets whenever the backend restarts (matching the original tool's
session-only behaviour, which is fine for the MVP). It is fed by the poll loop
from the same ``results`` list that updates the live status store, and read
back on demand by the REST history endpoint for sparkline charts.
"""

from collections import deque
from datetime import datetime
from typing import NamedTuple

from app.core.config import settings
from app.services.ping_engine import DeviceStatus


class HistorySample(NamedTuple):
    latency_ms: float | None
    timestamp: datetime


class HistoryStore:
    def __init__(self) -> None:
        self._history: dict[str, deque[HistorySample]] = {}

    def record(self, statuses: list[DeviceStatus]) -> None:
        """Append one sample per device from a poll cycle's results."""
        for status in statuses:
            self._history.setdefault(
                status.device_id, deque(maxlen=settings.HISTORY_MAX_SAMPLES)
            ).append(
                HistorySample(latency_ms=status.latency_ms, timestamp=status.timestamp)
            )

    def get_history(self, device_id: str) -> list[HistorySample]:
        """Return one device's samples, oldest first, or ``[]`` if unknown."""
        return list(self._history.get(device_id, []))


history_store = HistoryStore()
