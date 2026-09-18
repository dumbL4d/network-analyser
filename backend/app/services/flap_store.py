"""In-memory, session-based flap detection per device.

A "flap" is a change in a device's polled status between two consecutive
observations (e.g. healthy -> down or down -> healthy). Counts are cumulative
for the lifetime of this backend process and reset on restart, matching the
session-only behaviour of the history and status stores.

The store is fully self-contained: it tracks its own last-known status per
device and never reads the status store, so its behaviour does not depend on
call ordering relative to ``status_store.update()`` in the poll loop. A
device's very first observation never counts as a flap -- there is no previous
status to differ from yet.
"""

from app.services.ping_engine import DeviceStatus


class FlapStore:
    def __init__(self) -> None:
        self._last_status: dict[str, str] = {}
        self._flap_counts: dict[str, int] = {}

    def record(self, statuses: list[DeviceStatus]) -> None:
        """Update per-device flap counts from one poll cycle's results."""
        for status in statuses:
            last = self._last_status.get(status.device_id)
            if last is not None and last != status.status:
                self._flap_counts[status.device_id] = self._flap_counts.get(
                    status.device_id, 0
                ) + 1
            self._last_status[status.device_id] = status.status

    def get_flap_counts(self) -> dict[str, int]:
        """Return a copy of the device_id -> flap count mapping."""
        return dict(self._flap_counts)


flap_store = FlapStore()