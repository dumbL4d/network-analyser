"""Is the monitor itself keeping up?

The pages show the statuses of the last poll cycle. If the poll loop stops
completing cycles (the database is locked, a bug), they would go on showing
them as if they were current. So the loop notes when each cycle finished, and
the health endpoint reports how old that is and whether it is too old.

In memory only, no I/O.
"""

from datetime import datetime, timezone

# No completed cycle for this many poll intervals means the monitoring has
# fallen behind (see ``stale_after_seconds`` for what is added on top).
STALE_AFTER_INTERVALS = 3


def stale_after_seconds(poll_interval: float, pings: int, gap_ms: float, timeout: float) -> float:
    """How old the last completed cycle may get before the data counts as stale.

    Three poll intervals, plus the longest the pings of one cycle can take:
    they are sent ``gap_ms`` apart, and a device that answers nothing makes the
    last one wait for the timeout. Without that second part, a slow cycle
    during an outage would be reported as a stalled monitor. Pure.
    """
    return STALE_AFTER_INTERVALS * poll_interval + (pings - 1) * gap_ms / 1000 + timeout


class PollHealth:
    def __init__(self) -> None:
        # When the wait for the next completed cycle began: the start of the
        # poll loop, then the end of each completed cycle. None while no loop
        # runs (POLL_ENABLED=False), and then nothing is ever stale.
        self._waiting_since: datetime | None = None
        self._completed_at: datetime | None = None
        self._stale_after = 0.0

    def started(self, stale_after: float, at: datetime | None = None) -> None:
        """The poll loop is running. A loop that never completes a cycle is
        stale too, so the wait starts here."""
        self._waiting_since = at or datetime.now(timezone.utc)
        self._stale_after = stale_after

    def cycle_running(self, stale_after: float) -> None:
        """A cycle is under way with settings that allow ``stale_after``. If
        that is more than the limit so far (an admin has just raised them, or
        this is the first cycle and the limit came from the .env fallbacks),
        the cycle gets it: it must not look overdue for running as told."""
        self._stale_after = max(self._stale_after, stale_after)

    def cycle_completed(self, stale_after: float, at: datetime | None = None) -> None:
        """A poll cycle finished. ``stale_after`` is what its own settings
        allow before the next one is overdue."""
        self._completed_at = self._waiting_since = at or datetime.now(timezone.utc)
        self._stale_after = stale_after

    def report(self, now: datetime | None = None) -> dict[str, str | float | bool | None]:
        """What the health endpoint adds: when the last cycle finished, how
        long ago that is, and whether the next one is overdue."""
        # shortcut: the wall clock, so a clock step shifts the age by its size
        # until the next cycle; time.monotonic() if the host clock is not synced.
        now = now or datetime.now(timezone.utc)

        def seconds_since(moment: datetime | None) -> float | None:
            return None if moment is None else max(0.0, (now - moment).total_seconds())

        age = seconds_since(self._completed_at)
        waited = seconds_since(self._waiting_since)
        return {
            "last_poll_at": None if self._completed_at is None else self._completed_at.isoformat(),
            "last_poll_age_seconds": None if age is None else round(age, 1),
            "poll_stale": waited is not None and waited > self._stale_after,
        }


poll_health = PollHealth()
