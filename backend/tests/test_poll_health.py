"""Is the monitor itself keeping up? When the last poll cycle completed, and
whether the next one is overdue (app/services/poll_health.py).

No test here waits or depends on the real time: the first half passes the
time in, the second half steps the real poll loop on a clock the test sets.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlmodel import Session, select

from app.db.session import engine
from app.models.settings import AppSettings
from app.services import poll_loop
from app.services.poll_health import PollHealth, poll_health, stale_after_seconds
from tests.helpers import FakePing, run_cycles

T0 = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
LIMIT = 30.0  # seconds a PollHealth of the first half may wait for a cycle

NOTHING_YET = {"last_poll_at": None, "last_poll_age_seconds": None, "poll_stale": False}


def after(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


# --- how long is too long --------------------------------------------------------


@pytest.mark.parametrize(
    ("poll_interval", "pings", "gap_ms", "timeout", "expected"),
    [
        (8.0, 4, 200, 2.0, 26.6),  # the defaults: 24 s, 3 gaps of 0.2 s, the last ping's 2 s
        (8.0, 1, 200, 2.0, 26.0),  # a single ping has no gap to wait for
        (8.0, 4, 1000, 2.0, 29.0),
        (5.0, 4, 200, 1.0, 16.6),
        (60.0, 10, 1000, 2.0, 191.0),
    ],
)
def test_stale_after_three_intervals_plus_the_longest_one_cycle_can_ping(
    poll_interval, pings, gap_ms, timeout, expected
):
    assert stale_after_seconds(poll_interval, pings, gap_ms, timeout) == pytest.approx(expected)


# --- the notes of one loop -------------------------------------------------------


def test_nothing_is_stale_while_no_poll_loop_runs():
    # POLL_ENABLED=False: nobody is waiting for a cycle, however long it takes.
    assert PollHealth().report(now=after(100_000)) == NOTHING_YET


def test_a_loop_that_never_completes_a_cycle_goes_stale():
    health = PollHealth()
    health.started(LIMIT, at=T0)

    assert health.report(now=after(30)) == NOTHING_YET  # exactly the limit: not yet
    assert health.report(now=after(30.1)) == {**NOTHING_YET, "poll_stale": True}


def test_a_completed_cycle_is_reported_with_its_age():
    health = PollHealth()
    health.started(LIMIT, at=T0)
    health.cycle_completed(LIMIT, at=after(5))

    assert health.report(now=after(17.34)) == {
        "last_poll_at": "2026-11-15T12:00:05+00:00",
        "last_poll_age_seconds": 12.3,  # rounded to a tenth
        "poll_stale": False,
    }


def test_the_wait_is_counted_from_the_last_completed_cycle():
    health = PollHealth()
    health.started(LIMIT, at=T0)
    health.cycle_completed(LIMIT, at=after(100))

    assert health.report(now=after(130))["poll_stale"] is False  # 30 s after it, not 130
    stale = health.report(now=after(130.1))
    assert stale["poll_stale"] is True
    assert stale["last_poll_age_seconds"] == 30.1


def test_the_next_completed_cycle_ends_the_warning():
    health = PollHealth()
    health.cycle_completed(LIMIT, at=T0)
    assert health.report(now=after(500))["poll_stale"] is True

    health.cycle_completed(LIMIT, at=after(500))

    assert health.report(now=after(501)) == {
        "last_poll_at": after(500).isoformat(),
        "last_poll_age_seconds": 1.0,
        "poll_stale": False,
    }


def test_each_completed_cycle_brings_the_limit_of_its_own_settings():
    health = PollHealth()
    health.cycle_completed(30.0, at=T0)

    # An admin raised the poll interval: the next cycle is not due for longer...
    health.cycle_completed(900.0, at=after(10))
    assert health.report(now=after(10 + 900))["poll_stale"] is False
    assert health.report(now=after(10 + 900.1))["poll_stale"] is True

    # ...and lowered it again: neither is the limit kept at its highest.
    health.cycle_completed(30.0, at=after(1000))
    assert health.report(now=after(1000 + 30))["poll_stale"] is False
    assert health.report(now=after(1000 + 30.1))["poll_stale"] is True


def test_a_cycle_running_with_slower_settings_gets_their_limit():
    health = PollHealth()
    health.started(LIMIT, at=T0)
    # The cycle now running read settings that allow it 60 s, not the 30 s
    # the wait began with.
    health.cycle_running(60.0)

    assert health.report(now=after(60))["poll_stale"] is False
    assert health.report(now=after(60.1))["poll_stale"] is True


def test_a_cycle_running_with_faster_settings_does_not_cut_the_wait_short():
    health = PollHealth()
    health.cycle_completed(900.0, at=T0)
    # The poll interval was lowered while the loop slept its old, long one.
    health.cycle_running(30.0)

    assert health.report(now=after(900))["poll_stale"] is False
    assert health.report(now=after(900.1))["poll_stale"] is True


def test_a_clock_that_steps_back_gives_no_negative_age():
    health = PollHealth()
    health.cycle_completed(LIMIT, at=after(60))

    assert health.report(now=T0) == {
        "last_poll_at": after(60).isoformat(),
        "last_poll_age_seconds": 0.0,
        "poll_stale": False,
    }


def test_the_real_clock_is_used_when_no_time_is_passed():
    health = PollHealth()
    before = datetime.now(timezone.utc)
    health.started(LIMIT)
    health.cycle_completed(LIMIT)
    report = health.report()

    assert before <= datetime.fromisoformat(report["last_poll_at"]) <= datetime.now(timezone.utc)
    assert 0 <= report["last_poll_age_seconds"] < 5
    assert report["poll_stale"] is False


# --- the real poll loop ----------------------------------------------------------

# What the suite's settings allow (conftest.py and the seeded settings row):
# 3 poll intervals of 8 s, plus 4 pings sent 0.2 s apart, the last waiting 2 s.
SEEDED_LIMIT = 26.6


@pytest.fixture
def clock(monkeypatch):
    """The time at which the poll loop takes its notes: T0, until a test moves
    ``clock.at`` on. The loop itself never waits (see ``run_cycles``)."""

    class Clock(datetime):
        at = T0

        @classmethod
        def now(cls, tz=None):
            return cls.at

    monkeypatch.setattr("app.services.poll_health.datetime", Clock)
    return Clock


def store_settings(**values: Any) -> None:
    with Session(engine) as session:
        row = session.exec(select(AppSettings)).one()
        for field, value in values.items():
            setattr(row, field, value)
        session.add(row)
        session.commit()


def locked(*args: Any) -> Any:
    raise RuntimeError("database is locked")


@pytest.mark.usefixtures("db")
async def test_the_loop_notes_every_completed_cycle(clock):
    seen = []

    def after_cycle(cycle: int) -> None:
        seen.append(poll_health.report()["last_poll_at"])
        clock.at = after(15 * cycle)  # the next cycle ends 15 s after this one

    await run_cycles(3, FakePing(), after_cycle)

    assert seen == [after(0).isoformat(), after(15).isoformat(), after(30).isoformat()]
    # With the suite's settings the next one is overdue 26.6 s after the last.
    assert poll_health.report(now=after(30 + SEEDED_LIMIT - 0.1))["poll_stale"] is False
    assert poll_health.report(now=after(30 + SEEDED_LIMIT + 0.1))["poll_stale"] is True


@pytest.mark.usefixtures("db")
async def test_the_limit_follows_the_settings_the_cycle_ran_with(clock):
    store_settings(poll_interval_seconds=60.0, pings_per_cycle=3, ping_gap_ms=500)

    await run_cycles(1, FakePing())

    # 3 x 60 s, plus 3 pings sent 0.5 s apart, the last of which waits 2 s.
    assert poll_health.report(now=after(183))["poll_stale"] is False
    assert poll_health.report(now=after(183.1))["poll_stale"] is True


@pytest.mark.usefixtures("db")
async def test_a_loop_whose_cycles_all_fail_goes_stale(clock, monkeypatch):
    # Not even the settings can be read, so the limit stays the 32.6 s that
    # the .env fallbacks allow (PING_INTERVAL_SECONDS is 10 s in this suite).
    monkeypatch.setattr(poll_loop, "Session", locked)
    seen = []

    def after_cycle(cycle: int) -> None:
        clock.at = after(15 * cycle)  # 15 s later, just before the next attempt
        seen.append(poll_health.report())

    await run_cycles(3, FakePing(), after_cycle)

    # No attempt completed, and none restarted the wait: it has lasted since
    # the loop started, and passes the limit before the fourth attempt.
    assert seen == [NOTHING_YET, NOTHING_YET, {**NOTHING_YET, "poll_stale": True}]


@pytest.mark.usefixtures("db")
async def test_a_failed_cycle_leaves_the_time_of_the_last_good_one(clock, monkeypatch):
    real_load_devices = poll_loop._load_devices
    seen = []

    def after_cycle(cycle: int) -> None:
        seen.append(poll_health.report()["last_poll_at"])
        clock.at = after(15 * cycle)
        # Cycles 2 and 3 cannot read the device table. The fourth can again.
        monkeypatch.setattr(poll_loop, "_load_devices", locked if cycle < 3 else real_load_devices)

    await run_cycles(4, FakePing(), after_cycle)

    assert seen == [after(0).isoformat()] * 3 + [after(45).isoformat()]


@pytest.mark.usefixtures("db")
@pytest.mark.parametrize("step", ["persist_cycle", "incident_tracker.track"])
async def test_a_cycle_whose_database_write_fails_still_counts(monkeypatch, step):
    # The statuses on screen are this cycle's: only what is stored is behind.
    def disk_full(*args: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(f"app.services.poll_loop.{step}", disk_full)

    await run_cycles(1, FakePing())

    assert poll_health.report()["last_poll_at"] is not None


@pytest.mark.usefixtures("db")
async def test_a_cycle_is_not_overdue_for_running_with_slower_settings(clock):
    # Stored settings under which the pings of one cycle take 45 s, on a loop
    # that started with the 32.6 s the .env fallbacks allow.
    store_settings(poll_interval_seconds=120.0, pings_per_cycle=10, ping_gap_ms=5000)
    fake_ping = FakePing()
    overdue = []

    async def slow_ping(address: str, **kwargs: Any) -> Any:
        clock.at = after(45)
        overdue.append(poll_health.report()["poll_stale"])
        return await fake_ping(address, **kwargs)

    await run_cycles(1, slow_ping)

    assert overdue == [False] * 11  # asked while each of the 11 devices is pinged
