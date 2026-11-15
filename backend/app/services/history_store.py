"""In-memory rolling latency history per device: the hot cache.

It holds the most recent ``HISTORY_MAX_SAMPLES`` raw readings of each device.
It is fed by the poll loop from the same ``results`` list that updates the
live status store, and read back on demand by the REST history endpoint for
sparkline charts.

The readings are also written to the ``latency_sample`` table, and at startup
this cache is refilled from it (app/services/persistence.py), so the history
no longer resets when the backend restarts. Longer time ranges are served from
the database, not from here.
"""

from collections import deque
from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple

from app.core.config import settings
from app.services.ping_engine import DeviceStatus


class HistorySample(NamedTuple):
    latency_ms: float | None
    timestamp: datetime
    loss_pct: float | None = None
    jitter_ms: float | None = None


class HistoryStore:
    def __init__(self) -> None:
        self._history: dict[str, deque[HistorySample]] = {}

    def record(self, statuses: list[DeviceStatus]) -> None:
        """Append one sample per device from a poll cycle's results."""
        for status in statuses:
            self._history.setdefault(
                status.device_id, deque(maxlen=settings.HISTORY_MAX_SAMPLES)
            ).append(
                HistorySample(
                    latency_ms=status.latency_ms,
                    timestamp=status.timestamp,
                    loss_pct=status.loss_pct,
                    jitter_ms=status.jitter_ms,
                )
            )

    def load(self, device_id: str, samples: Iterable[HistorySample]) -> None:
        """Replace one device's samples (oldest first), keeping only the most
        recent ``HISTORY_MAX_SAMPLES``. Used to refill the cache at startup."""
        self._history[device_id] = deque(samples, maxlen=settings.HISTORY_MAX_SAMPLES)

    def get_history(self, device_id: str) -> list[HistorySample]:
        """Return one device's samples, oldest first, or ``[]`` if unknown."""
        return list(self._history.get(device_id, []))


history_store = HistoryStore()
