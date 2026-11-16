"""A sliding-window rate limiter, written by hand.

"At most ``limit`` events per key in any ``window_seconds``." Each key has a
deque of the times of its recent events, oldest on the left:

* a new event is appended on the right;
* events older than the window are popped from the left;
* the key is over the limit while the deque holds ``limit`` or more events.

Unlike a fixed window ("5 per calendar minute") the window slides with the
clock, so a burst cannot straddle a boundary and get twice the allowance.

The clock is passed in, so the tests can move time by hand. Used for login
throttling (``LoginThrottle`` below). The state is in memory: it is per
process and gone after a restart.
"""

import threading
import time
from collections import deque
from collections.abc import Callable, Hashable

# Between two full sweeps for keys that have gone quiet.
SWEEP_EVERY_SECONDS = 60.0


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[Hashable, deque[float]] = {}
        self._last_sweep = clock()
        # Requests are handled in several threads.
        self._lock = threading.Lock()

    def _recent(self, key: Hashable, now: float) -> deque[float] | None:
        """The key's events inside the window, after dropping older ones.

        Invariant: a deque is sorted (events are appended in time order), so
        everything too old is at the left end. Amortised O(1): every event is
        appended once and popped at most once.
        """
        events = self._events.get(key)
        if events is None:
            return None
        while events and events[0] <= now - self.window_seconds:
            events.popleft()
        if not events:
            del self._events[key]  # nothing recent: forget the key
            return None
        return events

    def retry_after(self, key: Hashable) -> float:
        """Seconds until ``key`` is under the limit again; 0 if it is now.

        With n >= limit events in the window, the key is allowed again once
        n - limit + 1 of them have aged out, i.e. when the event at index
        n - limit leaves the window. O(1) amortised.
        """
        with self._lock:
            now = self._clock()
            events = self._recent(key, now)
            if events is None or len(events) < self.limit:
                return 0.0
            return events[len(events) - self.limit] + self.window_seconds - now

    def record(self, key: Hashable) -> None:
        """Count one event for ``key``. O(1) amortised."""
        with self._lock:
            now = self._clock()
            self._sweep(now)
            events = self._recent(key, now)
            if events is None:
                events = self._events[key] = deque()
            events.append(now)

    def forget_newest(self, key: Hashable) -> None:
        """Take the newest event of ``key`` back, if it has one. O(1)."""
        with self._lock:
            events = self._events.get(key)
            if events:
                events.pop()
                if not events:
                    del self._events[key]

    def reset(self, key: Hashable) -> None:
        """Forget the events of ``key`` (after a successful login). O(1)."""
        with self._lock:
            self._events.pop(key, None)

    def _sweep(self, now: float) -> None:
        """Now and then, drop the keys whose events have all aged out, so
        that keys which are never asked about again do not pile up.

        O(number of keys), at most once per SWEEP_EVERY_SECONDS.
        """
        if now - self._last_sweep < SWEEP_EVERY_SECONDS:
            return
        self._last_sweep = now
        for key in list(self._events):
            self._recent(key, now)

    def __len__(self) -> int:
        """How many keys are being remembered."""
        with self._lock:
            return len(self._events)


# --- login throttling ----------------------------------------------------------

LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 300.0
# From one address, whatever the usernames. Without it an attacker could keep
# guessing (and keep filling the audit log) by changing the username each time.
LOGIN_FAILURE_LIMIT_PER_IP = 20


class LoginThrottle:
    """Slows down password guessing.

    Wrong passwords are counted per (IP address, username) pair and per IP
    address. A pair with 5 in the last 5 minutes, or an address with 20, is
    refused until enough of them have aged out, even with the right password:
    otherwise the guesser would still learn when a guess is right.

    An attempt is counted BEFORE its password is checked, and taken back if
    the password turns out to be right. Counting only once a password has
    proved wrong would leave a gap: checking one takes a quarter of a second,
    and every guess sent in the meantime would still see the old count and be
    let through. So "is the caller blocked? if not, count this attempt" is
    one step, under a lock.

    Refused attempts are not counted, so trying again while blocked does not
    prolong the block.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._pairs = SlidingWindowLimiter(LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS, clock)
        self._addresses = SlidingWindowLimiter(
            LOGIN_FAILURE_LIMIT_PER_IP, LOGIN_FAILURE_WINDOW_SECONDS, clock
        )
        self._lock = threading.Lock()

    def retry_after(self, ip: str, username: str) -> float:
        """Seconds until a password may be tried again; 0 if it may be now."""
        return max(self._pairs.retry_after((ip, username)), self._addresses.retry_after(ip))

    def attempt(self, ip: str, username: str) -> float:
        """Call before checking a password. A caller who is blocked gets the
        seconds to wait, and nothing is counted. Otherwise the attempt is
        counted and the answer is 0."""
        with self._lock:
            wait = self.retry_after(ip, username)
            if wait == 0:
                self._pairs.record((ip, username))
                self._addresses.record(ip)
            return wait

    def succeeded(self, ip: str, username: str) -> None:
        """The password was right, so the attempt was no guess: the pair
        starts from zero again and the address gets this one attempt back.
        The rest of the address's count stays, or one valid account would
        reset it for everyone."""
        with self._lock:
            self._pairs.reset((ip, username))
            self._addresses.forget_newest(ip)


login_throttle = LoginThrottle()
