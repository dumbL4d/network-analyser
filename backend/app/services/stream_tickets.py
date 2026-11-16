"""Single-use tickets for the status stream.

The browser's ``EventSource`` cannot send an ``Authorization`` header, so the
stream used to take the login token in its URL. URLs end up in server logs,
proxy logs and browser history, and that token is valid for an hour and for
every endpoint.

Instead the client first asks for a TICKET (with its normal ``Authorization``
header) and opens the stream with that. A ticket is a random string that

* works once: redeeming it removes it;
* expires after ``ttl_seconds`` (30) if it is not used;
* is good for the stream only, and means nothing anywhere else.

So a ticket that leaks through a log is already used up or expired.

In memory, per process. Expired tickets are purged whenever one is issued or
redeemed, so the store never holds more than what was issued in the last
``ttl_seconds``.
"""

import secrets
import threading
import time
from collections import deque
from collections.abc import Callable

TICKET_SECONDS = 30.0


class TicketStore:
    def __init__(self, ttl_seconds: float = TICKET_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        # The tickets that can still be redeemed: ticket -> username.
        self._tickets: dict[str, str] = {}
        # (the moment it expires, ticket) of every ticket issued, oldest on
        # the left. Every ticket lives equally long, so issue order is expiry
        # order: the next one to expire is always at the left end.
        self._expiries: deque[tuple[float, str]] = deque()
        self._lock = threading.Lock()

    def issue(self, username: str) -> str:
        """A fresh ticket for ``username``. O(1) amortised."""
        with self._lock:
            now = self._clock()
            self._purge(now)
            ticket = secrets.token_urlsafe(32)  # 256 random bits: not guessable
            self._tickets[ticket] = username
            self._expiries.append((now + self.ttl_seconds, ticket))
            return ticket

    def redeem(self, ticket: str) -> str | None:
        """The username a ticket was issued for, or None if it is unknown,
        already used, or expired. A ticket can be redeemed once. O(1)
        amortised."""
        with self._lock:
            self._purge(self._clock())
            return self._tickets.pop(ticket, None)

    def _purge(self, now: float) -> None:
        """Forget the tickets that have expired.

        Pops from the left end until it reaches a ticket that is still valid.
        Every ticket is appended once and popped once, so the cost is O(1)
        amortised per ticket, whatever is in the store. (A ticket that was
        redeemed stays in the deque until its time is up; removing it from
        the dict is what makes it unusable.)
        """
        while self._expiries and self._expiries[0][0] <= now:
            self._tickets.pop(self._expiries.popleft()[1], None)

    def __len__(self) -> int:
        """How many tickets can still be redeemed."""
        with self._lock:
            return len(self._tickets)


stream_tickets = TicketStore()
