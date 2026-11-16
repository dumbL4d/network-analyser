"""In-memory flap detection per device, backed by the ``status_transition`` table.

A "flap" is a change in a device's status between two consecutive
observations (e.g. healthy -> down or down -> healthy). The poll loop feeds
this store the CONFIRMED (debounced) statuses, so a flap is a confirmed change.

The store is the hot cache: it remembers each device's last status and the
time of every change. ``record`` returns the changes it saw, which the poll
loop writes to ``status_transition``; at startup the store is refilled from
that table (app/services/persistence.py), so flap counts survive a restart and
can always be derived from the table.

The store is fully self-contained: it tracks its own last-known status per
device and never reads the status store, so its behaviour does not depend on
call ordering relative to ``status_store.update()`` in the poll loop. A
device's very first observation never counts as a flap -- there is no previous
status to differ from yet.
"""

from datetime import datetime
from typing import NamedTuple

from app.services.ping_engine import DeviceStatus


class Transition(NamedTuple):
    """A status change of one device."""

    device_id: str
    timestamp: datetime
    from_status: str
    to_status: str


class FlapStore:
    def __init__(self) -> None:
        self._last_status: dict[str, str] = {}
        self._changes: dict[str, list[datetime]] = {}

    def record(self, statuses: list[DeviceStatus]) -> list[Transition]:
        """Update per-device flaps from one poll cycle's results.

        Returns the status changes found in this cycle, in input order.
        """
        transitions: list[Transition] = []
        for status in statuses:
            last = self._last_status.get(status.device_id)
            if last is not None and last != status.status:
                self._changes.setdefault(status.device_id, []).append(status.timestamp)
                transitions.append(
                    Transition(status.device_id, status.timestamp, last, status.status)
                )
            self._last_status[status.device_id] = status.status
        return transitions

    def restore(
        self, last_status: dict[str, str], changes: dict[str, list[datetime]]
    ) -> None:
        """Reload what was known before a restart: each device's last status
        and the times of its status changes."""
        self._last_status.update(last_status)
        for device_id, timestamps in changes.items():
            self._changes[device_id] = sorted(timestamps)

    def forget_before(self, cutoff: datetime) -> None:
        """Drop the changes older than ``cutoff`` (what the retention job has
        just deleted from the table). Call it from the event-loop thread."""
        self._changes = {
            device_id: kept
            for device_id, timestamps in self._changes.items()
            if (kept := [ts for ts in timestamps if ts >= cutoff])
        }

    def get_flap_counts(self, since: datetime | None = None) -> dict[str, int]:
        """Return device_id -> number of status changes.

        With ``since``, only changes at or after it are counted. Devices with
        no (counted) change are left out.
        """
        counts: dict[str, int] = {}
        for device_id, timestamps in list(self._changes.items()):
            count = sum(1 for ts in timestamps if since is None or ts >= since)
            if count:
                counts[device_id] = count
        return counts


flap_store = FlapStore()
