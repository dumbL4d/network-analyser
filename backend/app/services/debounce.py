"""Debouncing (hysteresis) of device status.

The ping engine classifies every device once per poll cycle. That *raw* result
is noisy: one lost ICMP packet reads as "down". This module turns the stream of
raw results into a *confirmed* status that changes only when several polls in a
row agree.

Statuses are ranked by how bad they are::

    healthy < degraded < down < unknown

("unknown" means the probe itself failed, so it ranks worst.) The rules are:

* A device's first-ever result is accepted as it is.
* Getting worse: when the last ``failure_threshold`` raw results are ALL worse
  than the confirmed status, the confirmed status becomes the mildest of them.
* Getting better: when the last ``recovery_threshold`` raw results are ALL
  better than the confirmed status, the confirmed status becomes the worst of
  them.
* Otherwise nothing changes.

So with the defaults (3 and 2): a device is marked down only after three "down"
polls in a row, and healthy again only after two "healthy" polls in a row.
healthy <-> degraded follows the same two rules. With both thresholds at 1
every raw result is confirmed at once, i.e. debouncing is off.

Everything here is pure and in-memory: no I/O, no database, no clock.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.services.ping_engine import DeviceStatus, StatusKey

MIN_THRESHOLD = 1
MAX_THRESHOLD = 10
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_THRESHOLD = 2

SEVERITY: dict[StatusKey, int] = {"healthy": 0, "degraded": 1, "down": 2, "unknown": 3}


@dataclass(frozen=True)
class DebounceState:
    """Everything the state machine remembers about one device."""

    confirmed: StatusKey
    # The most recent raw results, oldest first. Never longer than
    # MAX_THRESHOLD, because no rule looks further back than that.
    recent: tuple[StatusKey, ...]
    # Streak info for display: raw results in a row that were not healthy /
    # that were healthy. One of the two is always 0.
    consecutive_failures: int
    consecutive_successes: int
    # When the current run of non-healthy raw results began: the first failing
    # probe of the streak. None while the latest result is healthy, or when the
    # caller supplies no timestamps.
    failing_since: datetime | None = None


def _clamp(threshold: int) -> int:
    return max(MIN_THRESHOLD, min(MAX_THRESHOLD, threshold))


def step(
    previous: DebounceState | None,
    raw: StatusKey,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_threshold: int = DEFAULT_RECOVERY_THRESHOLD,
    at: datetime | None = None,
) -> DebounceState:
    """Advance one device by one poll cycle.

    ``previous`` is the device's state after the last cycle (``None`` if it has
    never been polled) and ``raw`` is this cycle's raw result. The thresholds
    are arguments, so a change to the settings applies from the next cycle on
    and is judged against the raw results already remembered. ``at`` is the
    time of this result; it is only used to remember when a run of failures
    began.
    """
    if previous is None:
        return DebounceState(
            confirmed=raw,
            recent=(raw,),
            consecutive_failures=int(raw != "healthy"),
            consecutive_successes=int(raw == "healthy"),
            failing_since=at if raw != "healthy" else None,
        )

    failure_threshold = _clamp(failure_threshold)
    recovery_threshold = _clamp(recovery_threshold)
    recent = (*previous.recent, raw)[-MAX_THRESHOLD:]
    confirmed = previous.confirmed
    current = SEVERITY[confirmed]

    worse_window = recent[-failure_threshold:]
    better_window = recent[-recovery_threshold:]
    if len(worse_window) == failure_threshold and all(
        SEVERITY[status] > current for status in worse_window
    ):
        confirmed = min(worse_window, key=SEVERITY.__getitem__)
    elif len(better_window) == recovery_threshold and all(
        SEVERITY[status] < current for status in better_window
    ):
        confirmed = max(better_window, key=SEVERITY.__getitem__)

    if raw == "healthy":
        failing_since = None
    elif previous.consecutive_failures == 0:
        failing_since = at  # this result starts a new run of failures
    else:
        failing_since = previous.failing_since

    return DebounceState(
        confirmed=confirmed,
        recent=recent,
        consecutive_failures=previous.consecutive_failures + 1 if raw != "healthy" else 0,
        consecutive_successes=previous.consecutive_successes + 1 if raw == "healthy" else 0,
        failing_since=failing_since,
    )


def state_from_history(
    confirmed: StatusKey,
    raws: Sequence[StatusKey],
    failing_since: datetime | None = None,
) -> DebounceState:
    """Rebuild a device's state from stored results.

    ``confirmed`` is its last confirmed status and ``raws`` its most recent raw
    results, oldest first; ``failing_since`` is when the run of failures at the
    end of ``raws`` began, if there is one. Used at startup, so that a restart
    does not turn the next poll into a "first-ever result". The streak counters
    can only count as far back as ``raws`` goes.
    """
    failures = 0
    for raw in reversed(raws):
        if raw == "healthy":
            break
        failures += 1
    successes = 0
    for raw in reversed(raws):
        if raw != "healthy":
            break
        successes += 1
    return DebounceState(
        confirmed=confirmed,
        recent=tuple(raws[-MAX_THRESHOLD:]),
        consecutive_failures=failures,
        consecutive_successes=successes,
        failing_since=failing_since if failures else None,
    )


class Debouncer:
    """Holds the :class:`DebounceState` of every device between poll cycles."""

    def __init__(self) -> None:
        self._states: dict[str, DebounceState] = {}

    def restore(self, states: dict[str, DebounceState]) -> None:
        """Reload device states that were rebuilt from the database."""
        self._states.update(states)

    def apply(
        self,
        results: list[DeviceStatus],
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_threshold: int = DEFAULT_RECOVERY_THRESHOLD,
    ) -> list[DeviceStatus]:
        """Turn one cycle's raw results into confirmed ones, in the same order.

        Each returned entry is the raw reading (same latency and timestamp)
        with ``status`` replaced by the confirmed status, plus the raw status
        and the streak counters.

        Only the devices in ``results`` are remembered afterwards, so the state
        of a device that has been deleted (and is no longer polled) is dropped.
        """
        states: dict[str, DebounceState] = {}
        confirmed: list[DeviceStatus] = []
        for reading in results:
            state = step(
                self._states.get(reading.device_id),
                reading.status,
                failure_threshold,
                recovery_threshold,
                at=reading.timestamp,
            )
            states[reading.device_id] = state
            confirmed.append(
                reading.model_copy(
                    update={
                        "status": state.confirmed,
                        "raw_status": reading.status,
                        "consecutive_failures": state.consecutive_failures,
                        "consecutive_successes": state.consecutive_successes,
                        "failing_since": state.failing_since,
                    }
                )
            )
        self._states = states
        return confirmed

    def get_states(self) -> dict[str, DebounceState]:
        """Return a copy of the device_id -> state mapping."""
        return dict(self._states)


debouncer = Debouncer()
