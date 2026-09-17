"""In-memory store of the latest device statuses, with a tiny queue pub/sub.

The poll loop (see :mod:`app.services.poll_loop`) writes the latest results
here, and each connected SSE client gets its own queue so that a slow or
disconnecting subscriber never blocks the others.
"""

import asyncio

from app.services.ping_engine import DeviceStatus


class StatusStore:
    def __init__(self) -> None:
        self._statuses: dict[str, DeviceStatus] = {}
        self._subscribers: list[asyncio.Queue[dict[str, DeviceStatus]]] = []

    def update(self, statuses: list[DeviceStatus]) -> None:
        """Replace the stored entry for each device and notify subscribers."""
        for status in statuses:
            self._statuses[status.device_id] = status

        snapshot = self.get_all()
        for queue in list(self._subscribers):
            queue.put_nowait(snapshot)

    def get_all(self) -> dict[str, DeviceStatus]:
        """Return a copy of the current device_id -> DeviceStatus mapping."""
        return dict(self._statuses)

    def subscribe(self) -> asyncio.Queue[dict[str, DeviceStatus]]:
        """Create and register a queue that receives every future update."""
        queue: asyncio.Queue[dict[str, DeviceStatus]] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, DeviceStatus]]) -> None:
        """Remove a previously subscribed queue (call this on disconnect)."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)


status_store = StatusStore()
