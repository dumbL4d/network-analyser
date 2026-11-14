"""The retention job: rollup of old raw samples, and deletion of old data."""

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert

from app.core.config import Settings, settings
from app.db.session import engine
from app.services import retention
from app.services.flap_store import Transition, flap_store
from app.services.persistence import ROLLUPS, SAMPLES, TRANSITIONS, persist_cycle
from app.services.retention import RetentionReport, run_retention, run_retention_loop
from app.services.rollup import rebucket, sample_bucket
from tests.helpers import StopLoop, make_status, stored

pytestmark = pytest.mark.usefixtures("db")

# With the default 24 h raw retention, the cutoff for this "now" is
# 2026-11-14 12:00:00: the 24 h mark (12:00:30) rounded down to a whole minute.
NOW = datetime(2026, 11, 15, 12, 0, 30, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
OLD_MINUTE = CUTOFF - timedelta(minutes=2)  # 11:58:00, fully before the cutoff

ROLLUP_COLUMNS = ("device_id", "bucket_start", "min", "avg", "max", "sample_count", "fail_count")
NOTHING_TO_DO = RetentionReport(0, 0, 0, 0)


def save_samples(device_id: str, *samples: tuple[datetime, float | None]) -> None:
    persist_cycle(
        [
            make_status(device_id, "down" if latency_ms is None else "healthy", latency_ms, timestamp)
            for timestamp, latency_ms in samples
        ],
        [],
    )


def save_rollup(device_id: str, start: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(ROLLUPS),
            [{"device_id": device_id, "bucket_start": start, "min": 1.0, "avg": 1.0, "max": 1.0,
              "sample_count": 6, "fail_count": 0}],
        )


def rollups() -> list[tuple]:
    return sorted(stored(ROLLUPS, *ROLLUP_COLUMNS))


def seconds(n: float) -> timedelta:
    return timedelta(seconds=n)


# --- rollup --------------------------------------------------------------------


def test_old_samples_are_rolled_up_by_minute_and_deleted():
    save_samples(
        "fw-01",
        (OLD_MINUTE + seconds(0), 1.0),
        (OLD_MINUTE + seconds(10), 3.0),
        (OLD_MINUTE + seconds(20), None),  # a lost ping
        (OLD_MINUTE + seconds(30), 8.0),
        (OLD_MINUTE + seconds(60), 5.0),  # the next minute
    )
    save_samples("sw-ot", (OLD_MINUTE + seconds(5), None), (OLD_MINUTE + seconds(15), None))
    recent = NOW - timedelta(hours=1)
    save_samples("fw-01", (recent, 2.0))

    report = run_retention(NOW)

    assert rollups() == [
        # min / avg / max over the three replies; four polls, one failed
        ("fw-01", OLD_MINUTE, 1.0, 4.0, 8.0, 4, 1),
        ("fw-01", OLD_MINUTE + timedelta(minutes=1), 5.0, 5.0, 5.0, 1, 0),
        # nothing replied: no latency at all, two polls, both failed
        ("sw-ot", OLD_MINUTE, None, None, None, 2, 2),
    ]
    # The raw rows that were rolled up are gone; the recent one is untouched.
    assert stored(SAMPLES, "device_id", "ts", "latency_ms") == [("fw-01", recent, 2.0)]
    assert report == RetentionReport(
        samples_rolled_up=7, rollup_rows_written=3, rollups_deleted=0, transitions_deleted=0
    )


def test_running_the_rollup_again_changes_nothing():
    save_samples("fw-01", (OLD_MINUTE + seconds(0), 1.0), (OLD_MINUTE + seconds(10), 3.0))
    save_samples("fw-01", (NOW - timedelta(hours=1), 2.0))
    run_retention(NOW)
    after_first_run = (rollups(), stored(SAMPLES, "device_id", "ts", "latency_ms"))

    assert run_retention(NOW) == NOTHING_TO_DO
    assert run_retention(NOW + timedelta(minutes=10)) == NOTHING_TO_DO

    assert (rollups(), stored(SAMPLES, "device_id", "ts", "latency_ms")) == after_first_run


def test_only_minutes_that_are_entirely_old_are_rolled_up():
    just_before = CUTOFF - timedelta(microseconds=1)  # 11:59:59.999999
    at_cutoff = CUTOFF  # 12:00:00
    # 12:00:10 is more than 24 h old (the mark is 12:00:30), but its minute is
    # not entirely old yet, so it waits for the next run.
    same_minute_as_the_mark = CUTOFF + seconds(10)
    save_samples("fw-01", (just_before, 1.0), (at_cutoff, 2.0), (same_minute_as_the_mark, 3.0))

    run_retention(NOW)

    assert rollups() == [("fw-01", CUTOFF - timedelta(minutes=1), 1.0, 1.0, 1.0, 1, 0)]
    assert stored(SAMPLES, "ts") == [(at_cutoff,), (same_minute_as_the_mark,)]

    # A minute later the whole 12:00 minute is old.
    run_retention(NOW + timedelta(minutes=1))

    assert rollups()[-1] == ("fw-01", CUTOFF, 2.0, 2.5, 3.0, 2, 0)
    assert stored(SAMPLES, "ts") == []


def test_late_samples_for_a_minute_already_rolled_up_are_merged_into_it():
    save_samples("fw-01", (OLD_MINUTE + seconds(0), 1.0), (OLD_MINUTE + seconds(10), 3.0))
    run_retention(NOW)
    assert rollups() == [("fw-01", OLD_MINUTE, 1.0, 2.0, 3.0, 2, 0)]

    # Two more samples turn up for that same minute (e.g. the clock was set back).
    save_samples("fw-01", (OLD_MINUTE + seconds(40), 10.0), (OLD_MINUTE + seconds(50), None))
    report = run_retention(NOW)

    # Still ONE row for the minute, now covering all four polls:
    # avg = (2.0 * 2 + 10.0 * 1) / 3 replies.
    assert rollups() == [("fw-01", OLD_MINUTE, 1.0, pytest.approx(14 / 3), 10.0, 4, 1)]
    assert report == RetentionReport(2, 1, 0, 0)
    assert stored(SAMPLES, "ts") == []


def test_a_backlog_is_rolled_up_in_batches_with_the_same_result(monkeypatch):
    # 60 samples over four minutes and three devices, in batches of 7, so
    # minutes are split across batches and have to be merged back together.
    polls = [
        (device_id, OLD_MINUTE - timedelta(minutes=minute) + seconds(second), None if second == 30 else float(second + minute))
        for device_id in ("fw-01", "sw-ot", "scanner-1")
        for minute in range(4)
        for second in (0, 10, 20, 30, 40)
    ]
    for device_id, ts, latency_ms in polls:
        save_samples(device_id, (ts, latency_ms))
    monkeypatch.setattr(retention, "ROLLUP_BATCH_SIZE", 7)
    monkeypatch.setattr(retention, "ROLLUP_BATCH_PAUSE_SECONDS", 0)  # no need to wait in a test

    report = run_retention(NOW)

    expected = sorted(
        (device_id, b.start, b.min_ms, pytest.approx(b.avg_ms), b.max_ms, b.sample_count, b.fail_count)
        for device_id in ("fw-01", "sw-ot", "scanner-1")
        for b in rebucket([sample_bucket(ts, ms) for d, ts, ms in polls if d == device_id], 60)
    )
    assert rollups() == expected
    assert len(expected) == 12  # 3 devices x 4 minutes
    assert report.samples_rolled_up == 60
    assert stored(SAMPLES, "ts") == []


# --- deletion ------------------------------------------------------------------


def test_rollups_older_than_the_rollup_retention_are_deleted():
    too_old = NOW - timedelta(days=30, minutes=1)
    just_kept = NOW - timedelta(days=30) + timedelta(minutes=1)
    recent = NOW - timedelta(days=1)
    for start in (too_old, just_kept, recent):
        save_rollup("fw-01", start.replace(second=0, microsecond=0))

    report = run_retention(NOW)

    assert [row[1] for row in rollups()] == [
        just_kept.replace(second=0, microsecond=0),
        recent.replace(second=0, microsecond=0),
    ]
    assert report.rollups_deleted == 1


def test_transitions_older_than_the_transition_retention_are_deleted():
    too_old = NOW - timedelta(days=31)
    kept = NOW - timedelta(days=29)
    persist_cycle(
        [],
        [Transition("sw-ot", too_old, "healthy", "down"), Transition("sw-ot", kept, "down", "healthy")],
    )

    report = run_retention(NOW)

    assert stored(TRANSITIONS, "ts", "from_status", "to_status") == [(kept, "down", "healthy")]
    assert report.transitions_deleted == 1


def test_retention_periods_come_from_the_settings(monkeypatch):
    two_hours_ago = (NOW - timedelta(hours=2)).replace(second=0, microsecond=0)
    save_samples("fw-01", (two_hours_ago, 1.0))
    save_rollup("sw-ot", NOW.replace(second=0, microsecond=0) - timedelta(days=3))
    persist_cycle([], [Transition("sw-ot", NOW - timedelta(days=3), "healthy", "down")])
    assert run_retention(NOW) == NOTHING_TO_DO  # nothing is old enough by default

    monkeypatch.setattr(settings, "RAW_RETENTION_HOURS", 1)
    monkeypatch.setattr(settings, "ROLLUP_RETENTION_DAYS", 2)
    monkeypatch.setattr(settings, "TRANSITION_RETENTION_DAYS", 2)

    assert run_retention(NOW) == RetentionReport(
        samples_rolled_up=1, rollup_rows_written=1, rollups_deleted=1, transitions_deleted=1
    )


def test_retention_defaults():
    defaults = {name: Settings.model_fields[name].default for name in Settings.model_fields}

    assert defaults["RAW_RETENTION_HOURS"] == 24
    assert defaults["ROLLUP_RETENTION_DAYS"] == 30
    assert defaults["TRANSITION_RETENTION_DAYS"] == 30
    assert defaults["RETENTION_INTERVAL_SECONDS"] == 3600  # hourly


# --- the background loop -------------------------------------------------------


def sleep_that_stops_after(runs: int):
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)
        if len(slept) >= runs:
            raise StopLoop

    return fake_sleep, slept


async def test_retention_loop_runs_at_once_and_then_at_the_configured_interval(monkeypatch):
    runs = []
    monkeypatch.setattr(retention, "run_retention", lambda: runs.append(1) or NOTHING_TO_DO)
    fake_sleep, slept = sleep_that_stops_after(3)

    with pytest.raises(StopLoop):
        await run_retention_loop(sleep=fake_sleep)

    assert len(runs) == 3  # the first run happens before the first sleep
    assert slept == [3600.0, 3600.0, 3600.0]


async def test_retention_loop_keeps_going_after_a_failed_run(monkeypatch):
    runs = []

    def flaky() -> RetentionReport:
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("database is locked")
        return NOTHING_TO_DO

    monkeypatch.setattr(retention, "run_retention", flaky)
    fake_sleep, slept = sleep_that_stops_after(2)

    with pytest.raises(StopLoop):
        await run_retention_loop(sleep=fake_sleep)

    assert len(runs) == 2
    assert slept == [3600.0, 3600.0]


async def test_retention_loop_runs_the_job_off_the_event_loop(monkeypatch):
    job_threads = []
    monkeypatch.setattr(
        retention, "run_retention", lambda: job_threads.append(threading.current_thread()) or NOTHING_TO_DO
    )
    fake_sleep, _ = sleep_that_stops_after(1)

    with pytest.raises(StopLoop):
        await run_retention_loop(sleep=fake_sleep)

    assert job_threads[0] is not threading.current_thread()


async def test_retention_loop_really_cleans_the_database_and_the_flap_store():
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    recent = now - timedelta(hours=1)
    old_minute = (now - timedelta(hours=30)).replace(second=0, microsecond=0)
    save_samples("fw-01", (old_minute, 1.0))
    persist_cycle([], [Transition("sw-ot", old, "healthy", "down"), Transition("sw-ot", recent, "down", "healthy")])
    flap_store.restore({"sw-ot": "healthy"}, {"sw-ot": [old, recent]})
    fake_sleep, _ = sleep_that_stops_after(1)

    with pytest.raises(StopLoop):
        await run_retention_loop(sleep=fake_sleep)

    assert rollups() == [("fw-01", old_minute, 1.0, 1.0, 1.0, 1, 0)]
    assert stored(SAMPLES, "ts") == []
    assert stored(TRANSITIONS, "ts") == [(recent,)]
    assert flap_store.get_flap_counts() == {"sw-ot": 1}  # the expired flap is forgotten in memory too
