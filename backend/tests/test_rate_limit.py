"""The sliding-window limiter and the login throttle built on it, on a clock
the tests move by hand. Throttling over HTTP is in test_security.py."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.rate_limit import (
    LOGIN_FAILURE_LIMIT,
    LOGIN_FAILURE_LIMIT_PER_IP,
    LOGIN_FAILURE_WINDOW_SECONDS,
    SWEEP_EVERY_SECONDS,
    LoginThrottle,
    SlidingWindowLimiter,
)


class FakeClock:
    """A clock that only moves when a test says so."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def set(self, now: float) -> None:
        self.now = now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(0.0)


@pytest.fixture
def limiter(clock) -> SlidingWindowLimiter:
    """3 events per 10 seconds."""
    return SlidingWindowLimiter(limit=3, window_seconds=10.0, clock=clock)


# =============================================================================
# SlidingWindowLimiter
# =============================================================================


def test_a_key_is_allowed_until_it_has_reached_the_limit(limiter):
    assert limiter.retry_after("a") == 0.0  # never seen

    limiter.record("a")
    limiter.record("a")
    assert limiter.retry_after("a") == 0.0  # 2 of 3

    limiter.record("a")
    assert limiter.retry_after("a") > 0  # 3 of 3: over


def test_retry_after_is_the_time_until_enough_events_have_aged_out(limiter, clock):
    for at in (0.0, 2.0, 5.0):
        clock.set(at)
        limiter.record("a")

    # Blocked until the event at t=0 is 10 seconds old.
    assert limiter.retry_after("a") == 5.0
    clock.set(9.5)
    assert limiter.retry_after("a") == 0.5
    clock.set(10.0)
    assert limiter.retry_after("a") == 0.0

    # The next event makes it three in the window again (t=2, 5, 10): blocked
    # until the one at t=2 leaves, at t=12.
    limiter.record("a")
    assert limiter.retry_after("a") == 2.0


def test_with_more_events_than_the_limit_several_have_to_age_out(limiter, clock):
    for at in (0.0, 1.0, 2.0, 3.0):  # four events, limit three
        clock.set(at)
        limiter.record("a")

    # Two must leave before only two are left: the ones at t=0 and t=1.
    assert limiter.retry_after("a") == 8.0  # until t=11
    clock.set(10.5)  # the first one has left, three remain
    assert limiter.retry_after("a") == 0.5
    clock.set(11.0)
    assert limiter.retry_after("a") == 0.0


def test_the_window_slides_with_the_clock_instead_of_resetting_at_a_boundary(limiter, clock):
    # With fixed windows [0, 10) and [10, 20), three events at the end of one
    # and three at the start of the next would all be allowed: six in 2.5 s.
    for at in (8.0, 9.0, 9.5):
        clock.set(at)
        limiter.record("a")

    clock.set(10.5)  # a new fixed window would have started
    assert limiter.retry_after("a") == 7.5  # still blocked, until t=18
    clock.set(18.0)
    assert limiter.retry_after("a") == 0.0


def test_keys_are_counted_separately(limiter):
    for _ in range(3):
        limiter.record("a")

    assert limiter.retry_after("a") > 0
    assert limiter.retry_after("b") == 0.0
    assert limiter.retry_after(("a", "tuple keys work too")) == 0.0


def test_reset_forgets_the_events_of_a_key(limiter):
    for _ in range(3):
        limiter.record("a")
        limiter.record("b")

    limiter.reset("a")
    limiter.reset("never-seen")  # not an error

    assert limiter.retry_after("a") == 0.0
    assert limiter.retry_after("b") > 0
    limiter.record("a")
    limiter.record("a")
    assert limiter.retry_after("a") == 0.0  # counted from zero again: 2 of 3


def test_forget_newest_takes_back_the_last_event_only(limiter, clock):
    for at in (0.0, 4.0, 6.0):
        clock.set(at)
        limiter.record("a")
    assert limiter.retry_after("a") == 4.0  # blocked until the event at t=0 leaves

    limiter.forget_newest("a")  # the one at t=6
    assert limiter.retry_after("a") == 0.0

    clock.set(7.0)
    limiter.record("a")  # t=0, 4, 7: the two older ones are still counted
    assert limiter.retry_after("a") == 3.0


def test_forget_newest_of_a_key_without_events_does_nothing(limiter):
    limiter.forget_newest("never-seen")
    limiter.record("a")

    limiter.forget_newest("a")
    limiter.forget_newest("a")

    assert len(limiter) == 0  # a key without events is not kept
    assert limiter.retry_after("a") == 0.0


def test_a_key_is_forgotten_once_all_its_events_have_aged_out(limiter, clock):
    limiter.record("a")
    assert len(limiter) == 1

    clock.set(10.0)
    assert limiter.retry_after("a") == 0.0  # asking is enough to drop it
    assert len(limiter) == 0


def test_keys_that_are_never_asked_about_again_are_swept(limiter, clock):
    for key in ("a", "b", "c"):
        limiter.record(key)

    # Their events are too old, but no sweep is due yet: still remembered.
    clock.set(SWEEP_EVERY_SECONDS - 1)
    limiter.record("d")
    assert len(limiter) == 4

    clock.set(SWEEP_EVERY_SECONDS)  # the sweep runs with the next event
    limiter.record("e")
    assert len(limiter) == 2  # "d" and "e": the three stale keys are gone

    # And then not again before another SWEEP_EVERY_SECONDS have passed.
    clock.set(SWEEP_EVERY_SECONDS + 15)
    limiter.record("f")
    assert len(limiter) == 3  # "d" and "e" are stale by now, and still there


def test_a_sweep_keeps_the_keys_that_still_have_recent_events(clock):
    limiter = SlidingWindowLimiter(limit=3, window_seconds=100.0, clock=clock)
    limiter.record("old")
    clock.set(50.0)
    limiter.record("recent")

    clock.set(120.0)  # "old" is 120 s old, "recent" 70 s
    limiter.record("new")

    assert len(limiter) == 2
    limiter.record("recent")
    assert limiter.retry_after("recent") == 0.0  # 2 of 3: its first event was kept
    limiter.record("recent")
    assert limiter.retry_after("recent") > 0


# =============================================================================
# LoginThrottle
# =============================================================================
#
# attempt() is called before a password is checked: it counts the attempt, or
# refuses it. A right password is reported with succeeded(); a wrong one needs
# no further call.


@pytest.fixture
def throttle(clock) -> LoginThrottle:
    return LoginThrottle(clock=clock)


def wrong_password(throttle: LoginThrottle, ip: str, username: str) -> None:
    assert throttle.attempt(ip, username) == 0.0  # allowed, and counted


def test_the_policy_is_5_failures_in_5_minutes_per_pair_and_20_per_address():
    assert (LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS, LOGIN_FAILURE_LIMIT_PER_IP) == (5, 300.0, 20)


def test_five_wrong_passwords_block_the_pair_for_five_minutes(throttle, clock):
    for _ in range(5):
        assert throttle.retry_after("10.0.0.1", "admin") == 0.0
        wrong_password(throttle, "10.0.0.1", "admin")

    assert throttle.retry_after("10.0.0.1", "admin") == 300.0
    assert throttle.attempt("10.0.0.1", "admin") == 300.0  # refused, whatever the password
    clock.advance(299.0)
    assert throttle.attempt("10.0.0.1", "admin") == 1.0
    clock.advance(1.0)
    assert throttle.attempt("10.0.0.1", "admin") == 0.0


def test_a_refused_attempt_is_not_counted(throttle, clock):
    for _ in range(5):
        wrong_password(throttle, "10.0.0.1", "admin")

    clock.set(200.0)
    for _ in range(10):  # keeps trying while blocked
        assert throttle.attempt("10.0.0.1", "admin") == 100.0

    clock.set(300.0)  # the five counted ones have aged out; the ten were never counted
    for _ in range(5):
        wrong_password(throttle, "10.0.0.1", "admin")


def test_the_block_ends_when_the_oldest_failure_is_five_minutes_old(throttle, clock):
    for at in (0.0, 10.0, 20.0, 30.0, 40.0):
        clock.set(at)
        wrong_password(throttle, "10.0.0.1", "admin")

    clock.set(299.9)
    assert throttle.retry_after("10.0.0.1", "admin") == pytest.approx(0.1)
    clock.set(300.0)
    assert throttle.retry_after("10.0.0.1", "admin") == 0.0

    # One more guess, and the pair is blocked until the failure at t=10 leaves.
    wrong_password(throttle, "10.0.0.1", "admin")
    assert throttle.retry_after("10.0.0.1", "admin") == 10.0


def test_another_username_or_another_address_is_not_blocked(throttle):
    for _ in range(5):
        wrong_password(throttle, "10.0.0.1", "admin")

    assert throttle.retry_after("10.0.0.1", "admin") > 0
    assert throttle.retry_after("10.0.0.1", "viewer") == 0.0
    assert throttle.retry_after("10.0.0.2", "admin") == 0.0


def test_a_right_password_starts_the_pair_from_zero(throttle):
    for _ in range(4):
        wrong_password(throttle, "10.0.0.1", "admin")
    assert throttle.attempt("10.0.0.1", "admin") == 0.0  # the fifth attempt ...
    throttle.succeeded("10.0.0.1", "admin")  # ... has the right password

    assert throttle.retry_after("10.0.0.1", "admin") == 0.0
    for _ in range(4):
        wrong_password(throttle, "10.0.0.1", "admin")
    assert throttle.retry_after("10.0.0.1", "admin") == 0.0


def test_logging_in_correctly_over_and_over_never_blocks(throttle):
    for _ in range(50):
        assert throttle.attempt("10.0.0.1", "admin") == 0.0
        throttle.succeeded("10.0.0.1", "admin")

    assert throttle.retry_after("10.0.0.1", "anyone") == 0.0  # nor does it count against the address


def test_twenty_wrong_passwords_block_the_address_whatever_the_usernames(throttle, clock):
    for attempt in range(20):
        wrong_password(throttle, "10.0.0.1", f"user-{attempt}")

    # Also for a username that has not been tried, and for the right password.
    assert throttle.attempt("10.0.0.1", "admin") == 300.0
    assert throttle.retry_after("10.0.0.2", "admin") == 0.0  # other addresses carry on

    clock.advance(300.0)
    assert throttle.attempt("10.0.0.1", "admin") == 0.0


def test_a_right_password_does_not_reset_the_count_of_the_address(throttle):
    for attempt in range(19):
        wrong_password(throttle, "10.0.0.1", f"user-{attempt}")
    assert throttle.attempt("10.0.0.1", "viewer") == 0.0  # the guesser has one valid account
    throttle.succeeded("10.0.0.1", "viewer")

    # Its own attempt was taken back (19 again), the others were not.
    wrong_password(throttle, "10.0.0.1", "admin")  # the 20th
    assert throttle.retry_after("10.0.0.1", "viewer") > 0


def test_the_longer_of_the_two_waits_applies(throttle, clock):
    for attempt in range(15):  # t=0: fifteen failures of other usernames
        wrong_password(throttle, "10.0.0.1", f"user-{attempt}")
    clock.set(100.0)
    for _ in range(5):  # t=100: five for admin, which also makes it 20 for the address
        wrong_password(throttle, "10.0.0.1", "admin")

    # The address is free again at t=300 (when the first fifteen leave), the
    # pair only at t=400.
    assert throttle.retry_after("10.0.0.1", "someone-else") == 200.0
    assert throttle.retry_after("10.0.0.1", "admin") == 300.0


def slow_clock() -> float:
    """A real clock that lets other threads run every time it is read: what
    makes "check, then count" go wrong if the two are not one step."""
    time.sleep(0.001)
    return time.monotonic()


@pytest.mark.parametrize(
    ("usernames", "allowed"),
    [(["admin"] * 40, 5), ([f"user-{n}" for n in range(40)], 20)],
    ids=["one-username", "forty-usernames"],
)
def test_guesses_sent_in_parallel_cannot_slip_through_together(usernames, allowed):
    throttle = LoginThrottle(clock=slow_clock)
    together = threading.Barrier(len(usernames))

    def guess(username: str) -> float:
        together.wait()
        return throttle.attempt("10.0.0.1", username)

    with ThreadPoolExecutor(len(usernames)) as pool:
        waits = list(pool.map(guess, usernames))

    assert sum(wait == 0.0 for wait in waits) == allowed
