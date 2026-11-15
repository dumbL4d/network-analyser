"""Persistence: the write path after each poll cycle, the warm-up of the
in-memory stores after a restart, flap counts, and windowed history reads."""

import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError, StatementError

from app.core.config import settings
from app.db.session import engine
from app.db.types import UTCDateTime
from app.main import app
from app.services import poll_loop
from app.services.debounce import debouncer
from app.services.flap_store import Transition, flap_store
from app.services.history_store import history_store
from app.services.persistence import (
    ROLLUPS,
    SAMPLES,
    TRANSITIONS,
    history_window,
    persist_cycle,
)
from app.services.status_store import status_store
from tests.helpers import (
    FakePing,
    ip_of,
    make_status,
    restart_backend,
    run_cycles,
    seed_devices,
    stored,
)

pytestmark = pytest.mark.usefixtures("db")

REPLY = (True, 1.0)
LOST = (False, 0.0)

# A fixed "now" for the tests that put rows at chosen times.
NOW = datetime(2026, 11, 15, 12, 0, 30, tzinfo=timezone.utc)


def ago(**delta) -> datetime:
    return NOW - timedelta(**delta)


def save_samples(device_id: str, *samples: tuple[datetime, float | None]) -> None:
    """Store raw samples at chosen times (a reply in ms, or None for a lost ping)."""
    persist_cycle(
        [
            make_status(device_id, "down" if latency_ms is None else "healthy", latency_ms, timestamp)
            for timestamp, latency_ms in samples
        ],
        [],
    )


def save_rollup(device_id: str, start: datetime, low, avg, high, sample_count: int, fail_count: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(ROLLUPS),
            [{"device_id": device_id, "bucket_start": start, "min": low, "avg": avg, "max": high,
              "sample_count": sample_count, "fail_count": fail_count}],
        )


# --- write path ----------------------------------------------------------------


def test_persist_cycle_stores_a_sample_per_reading_and_every_transition():
    healthy = make_status("fw-01", "healthy", 1.5, ago(seconds=10))
    # What the debouncer publishes while one lost ping is unconfirmed.
    pending = make_status("sw-ot", "healthy", None, ago(seconds=9)).model_copy(update={"raw_status": "down"})
    change = Transition("scanner-1", ago(seconds=8), "healthy", "down")

    persist_cycle([healthy, pending], [change])

    assert stored(SAMPLES, "device_id", "ts", "latency_ms", "raw_status", "confirmed_status") == [
        ("fw-01", ago(seconds=10), 1.5, "healthy", "healthy"),
        ("sw-ot", ago(seconds=9), None, "down", "healthy"),
    ]
    assert stored(TRANSITIONS, "device_id", "ts", "from_status", "to_status") == [
        ("scanner-1", ago(seconds=8), "healthy", "down"),
    ]


def test_persist_cycle_is_one_transaction_all_or_nothing():
    reading = make_status("fw-01", "healthy", 1.5)
    broken = Transition("fw-01", reading.timestamp, "healthy", None)  # to_status is required

    with pytest.raises(IntegrityError):
        persist_cycle([reading], [broken])

    # The sample of that cycle was rolled back together with the transition.
    assert stored(SAMPLES, "device_id") == []
    assert stored(TRANSITIONS, "device_id") == []


def test_persist_cycle_with_nothing_to_store_does_nothing():
    persist_cycle([], [])

    assert stored(SAMPLES, "device_id") == []


def test_timestamps_are_stored_as_utc_and_come_back_timezone_aware():
    india = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 11, 15, 17, 30, 0, 123456, tzinfo=india)  # 12:00:00.123456 UTC

    persist_cycle([make_status("fw-01", "healthy", 1.0, local)], [])

    ((ts,),) = stored(SAMPLES, "ts")
    assert ts == local
    assert ts.utcoffset() == timedelta(0)
    assert (ts.hour, ts.microsecond) == (12, 123456)


def test_a_timestamp_without_a_timezone_is_refused():
    naive = datetime(2026, 11, 15, 12, 0, 0)

    with pytest.raises(StatementError, match="timezone-aware"):
        persist_cycle([make_status("fw-01", "healthy", 1.0, naive)], [])

    assert stored(SAMPLES, "ts") == []


def test_utc_datetime_type_passes_none_through():
    column_type = UTCDateTime()

    assert column_type.process_bind_param(None, None) is None
    assert column_type.process_result_value(None, None) is None


async def test_the_poll_loop_stores_every_cycle():
    #          cycle:  1      2     3     4
    script = [REPLY, LOST, LOST, LOST]
    ping = FakePing(default=REPLY)
    ping.outcomes[ip_of("sw-ot")] = script[0]

    def after_cycle(cycle: int) -> None:
        if cycle < len(script):
            ping.outcomes[ip_of("sw-ot")] = script[cycle]

    await run_cycles(4, ping, after_cycle)

    samples = stored(SAMPLES, "device_id", "latency_ms", "raw_status", "confirmed_status")
    assert len(samples) == 4 * 11  # one row per device per cycle
    assert [row[1:] for row in samples if row[0] == "sw-ot"] == [
        (1.0, "healthy", "healthy"),
        (None, "down", "healthy"),
        (None, "down", "healthy"),
        (None, "down", "down"),  # confirmed on the third lost ping
    ]
    assert {row[1:] for row in samples if row[0] != "sw-ot"} == {(1.0, "healthy", "healthy")}

    # Exactly one transition: the confirmed change, stamped with that poll's time.
    last_sw_ot_sample = [ts for device_id, ts in stored(SAMPLES, "device_id", "ts") if device_id == "sw-ot"][-1]
    assert stored(TRANSITIONS, "device_id", "ts", "from_status", "to_status") == [
        ("sw-ot", last_sw_ot_sample, "healthy", "down"),
    ]


async def test_the_database_write_runs_off_the_event_loop(monkeypatch):
    writer_threads = []
    monkeypatch.setattr(
        poll_loop,
        "persist_cycle",
        lambda readings, transitions: writer_threads.append(threading.current_thread()),
    )

    await run_cycles(1, FakePing())

    # This coroutine runs on the event loop's thread; the write must not.
    assert len(writer_threads) == 1
    assert writer_threads[0] is not threading.current_thread()


async def test_a_failed_database_write_does_not_stop_monitoring(monkeypatch):
    def disk_full(readings, transitions) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(poll_loop, "persist_cycle", disk_full)

    intervals = await run_cycles(2, FakePing())

    assert intervals == [10.0, 10.0]  # the loop kept its rhythm
    assert len(status_store.get_all()) == 11  # live status is still published
    assert len(history_store.get_history("fw-01")) == 2


# --- warm-up after a restart ---------------------------------------------------


async def test_history_is_reloaded_after_a_restart():
    await run_cycles(5, FakePing(default=(True, 7.5)))
    device_ids = [device.id for device in seed_devices()]
    before = {device_id: history_store.get_history(device_id) for device_id in device_ids}
    assert all(len(samples) == 5 for samples in before.values())

    restart_backend()

    # Same latencies and the very same (timezone-aware) timestamps, per device.
    assert {device_id: history_store.get_history(device_id) for device_id in device_ids} == before
    assert before["fw-01"][0].timestamp.utcoffset() == timedelta(0)
    assert status_store.get_all() == {}  # live status waits for the first poll


def test_only_the_most_recent_samples_are_reloaded():
    assert settings.HISTORY_MAX_SAMPLES == 36
    save_samples("fw-01", *[(ago(seconds=10 * (40 - i)), float(i)) for i in range(40)])

    restart_backend(NOW)

    latencies = [sample.latency_ms for sample in history_store.get_history("fw-01")]
    assert latencies == [float(i) for i in range(4, 40)]  # the newest 36, oldest first


def test_samples_of_a_device_that_no_longer_exists_are_not_reloaded():
    save_samples("deleted-device", (ago(seconds=10), 1.0))

    restart_backend(NOW)

    assert history_store.get_history("deleted-device") == []


async def test_default_history_response_is_the_same_after_a_restart(client, admin_headers):
    await run_cycles(3, FakePing(default=(True, 2.5)))
    before = client.get("/api/history/fw-01", headers=admin_headers).json()
    assert [sample["latency_ms"] for sample in before] == [2.5, 2.5, 2.5]

    restart_backend()

    assert client.get("/api/history/fw-01", headers=admin_headers).json() == before


def test_app_startup_refills_the_caches():
    save_samples("fw-01", (datetime.now(timezone.utc), 4.0))
    assert history_store.get_history("fw-01") == []  # only in the database so far

    with TestClient(app):  # the app's lifespan runs the warm-up
        assert [sample.latency_ms for sample in history_store.get_history("fw-01")] == [4.0]


# --- flaps across a restart ----------------------------------------------------


async def test_flap_counts_survive_a_restart(client, admin_headers):
    #          cycle:  1      2     3     4     5      6
    script = [REPLY, LOST, LOST, LOST, REPLY, REPLY]  # down, then back: 2 flaps
    ping = FakePing(default=REPLY)
    ping.outcomes[ip_of("sw-ot")] = script[0]

    def after_cycle(cycle: int) -> None:
        if cycle < len(script):
            ping.outcomes[ip_of("sw-ot")] = script[cycle]

    await run_cycles(6, ping, after_cycle)
    before = client.get("/api/flaps", headers=admin_headers).json()
    assert before[0] == {"device_id": "sw-ot", "flap_count": 2}

    restart_backend()

    assert client.get("/api/flaps", headers=admin_headers).json() == before


async def test_a_restart_does_not_turn_a_lost_ping_into_a_transition():
    ping = FakePing(default=REPLY)
    await run_cycles(2, ping)

    restart_backend()
    ping.outcomes[ip_of("sw-ot")] = LOST  # the first poll after the restart is lost
    await run_cycles(1, ping)

    # The debounce state came back too, so this is one unconfirmed failure,
    # not a "first-ever result" that would be accepted at once.
    reading = status_store.get_all()["sw-ot"]
    assert (reading.status, reading.raw_status, reading.consecutive_failures) == ("healthy", "down", 1)
    assert stored(TRANSITIONS, "device_id") == []
    assert flap_store.get_flap_counts() == {}


async def test_a_real_change_after_a_restart_is_recorded_once():
    ping = FakePing(default=REPLY)
    await run_cycles(2, ping)

    restart_backend()
    ping.outcomes[ip_of("sw-ot")] = LOST
    await run_cycles(3, ping)

    assert stored(TRANSITIONS, "device_id", "from_status", "to_status") == [("sw-ot", "healthy", "down")]
    assert flap_store.get_flap_counts() == {"sw-ot": 1}


def test_debounce_state_is_not_restored_after_a_long_gap():
    # The last poll was an hour ago: far more than the 10 polls the debouncer
    # remembers. History and the last status come back, the streak does not.
    save_samples("fw-01", (ago(hours=1), 3.0))

    restart_backend(NOW)

    assert len(history_store.get_history("fw-01")) == 1
    assert "fw-01" not in debouncer.get_states()
    # The next result is accepted at once, and because it differs from the
    # last stored status it is a transition.
    (confirmed,) = debouncer.apply([make_status("fw-01", "down", None, NOW)])
    assert confirmed.status == "down"
    assert flap_store.record([confirmed]) == [Transition("fw-01", NOW, "healthy", "down")]


def test_debounce_state_is_restored_when_the_last_poll_is_recent():
    save_samples("fw-01", (ago(seconds=30), 1.0), (ago(seconds=20), None), (ago(seconds=10), None))

    restart_backend(NOW)

    state = debouncer.get_states()["fw-01"]
    assert state.confirmed == "down"  # the last confirmed status that was stored
    assert state.recent == ("healthy", "down", "down")
    assert (state.consecutive_failures, state.consecutive_successes) == (2, 0)
    assert state.failing_since == ago(seconds=20)  # the first failing poll of the run


def test_flaps_are_counted_over_the_transition_retention_window(client, admin_headers):
    assert settings.TRANSITION_RETENTION_DAYS == 30
    now = datetime.now(timezone.utc)
    persist_cycle(
        [],
        [
            Transition("sw-ot", now - timedelta(days=40), "healthy", "down"),  # too old
            Transition("sw-ot", now - timedelta(days=29), "down", "healthy"),
            Transition("sw-ot", now - timedelta(hours=1), "healthy", "down"),
        ],
    )

    restart_backend()

    rows = client.get("/api/flaps", headers=admin_headers).json()
    assert rows[0] == {"device_id": "sw-ot", "flap_count": 2}
    assert len(rows) == 11  # every device is still listed


# --- windowed history ----------------------------------------------------------


def point(out, index: int) -> tuple:
    p = out.points[index]
    return (p.timestamp, p.latency_ms, p.min_ms, p.max_ms, p.sample_count, p.fail_count)


@pytest.mark.parametrize(
    ("window", "resolution", "seconds"),
    [("1h", "raw", None), ("6h", "1m", 60), ("24h", "5m", 300), ("7d", "30m", 1800), ("30d", "2h", 7200)],
)
def test_each_window_reports_the_resolution_it_used(window, resolution, seconds):
    out = history_window("fw-01", window, now=NOW)

    assert (out.device_id, out.window, out.resolution, out.resolution_seconds) == ("fw-01", window, resolution, seconds)
    assert out.points == []  # nothing stored yet


def test_1h_window_returns_the_raw_samples_inside_it():
    save_samples(
        "fw-01",
        (ago(minutes=90), 9.0),  # outside the window
        (ago(minutes=30), 2.0),
        (ago(seconds=10), None),  # a lost ping
    )
    save_samples("sw-ot", (ago(minutes=5), 50.0))  # another device

    out = history_window("fw-01", "1h", now=NOW)

    assert out.resolution == "raw"
    assert [point(out, i) for i in range(len(out.points))] == [
        (ago(minutes=30), 2.0, 2.0, 2.0, 1, 0),
        (ago(seconds=10), None, None, None, 1, 1),
    ]


def test_6h_window_buckets_the_raw_samples_by_minute():
    minute = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)  # three hours before NOW
    save_samples(
        "fw-01",
        (minute + timedelta(seconds=0), 1.0),
        (minute + timedelta(seconds=10), 3.0),
        (minute + timedelta(seconds=20), None),
        (minute + timedelta(seconds=30), 8.0),
        (minute + timedelta(seconds=65), 5.0),  # the next minute
    )

    out = history_window("fw-01", "6h", now=NOW)

    assert out.resolution == "1m"
    assert [point(out, i) for i in range(len(out.points))] == [
        (minute, 4.0, 1.0, 8.0, 4, 1),  # avg of the three replies; one lost
        (minute + timedelta(minutes=1), 5.0, 5.0, 5.0, 1, 0),
    ]


def test_long_window_combines_the_rollups_with_raw_samples_not_yet_rolled_up():
    three_days_ago = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)
    # Two 1-minute rollups that fall in the same 30-minute bucket...
    save_rollup("fw-01", three_days_ago, 1.0, 2.0, 3.0, sample_count=6, fail_count=0)
    save_rollup("fw-01", three_days_ago + timedelta(minutes=7), 4.0, 5.0, 9.0, sample_count=6, fail_count=3)
    # ...and today's raw samples, which the retention job has not touched yet.
    today = datetime(2026, 11, 15, 11, 30, 0, tzinfo=timezone.utc)
    save_samples("fw-01", (today + timedelta(seconds=5), 10.0), (today + timedelta(seconds=15), 20.0))

    out = history_window("fw-01", "7d", now=NOW)

    assert out.resolution == "30m"
    assert [point(out, i) for i in range(len(out.points))] == [
        # (2.0 * 6 + 5.0 * 3) / 9 replies = 3.0
        (three_days_ago, pytest.approx(3.0), 1.0, 9.0, 12, 3),
        (today, 15.0, 10.0, 20.0, 2, 0),
    ]


def test_data_older_than_the_window_is_left_out():
    save_rollup("fw-01", ago(days=8), 1.0, 1.0, 1.0, sample_count=6, fail_count=0)
    save_rollup("fw-01", ago(days=6), 2.0, 2.0, 2.0, sample_count=6, fail_count=0)

    assert len(history_window("fw-01", "7d", now=NOW).points) == 1
    assert len(history_window("fw-01", "30d", now=NOW).points) == 2


def test_1h_falls_back_to_minute_buckets_when_raw_samples_are_kept_for_less(monkeypatch):
    monkeypatch.setattr(settings, "RAW_RETENTION_HOURS", 0.5)

    out = history_window("fw-01", "1h", now=NOW)

    assert (out.resolution, out.resolution_seconds) == ("1m", 60)


async def test_history_endpoint_with_a_window(client, admin_headers):
    await run_cycles(3, FakePing(default=(True, 2.5)))

    response = client.get("/api/history/fw-01", headers=admin_headers, params={"window": "1h"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"device_id", "window", "resolution", "resolution_seconds", "points"}
    assert (body["device_id"], body["window"], body["resolution"], body["resolution_seconds"]) == (
        "fw-01", "1h", "raw", None,
    )
    assert len(body["points"]) == 3
    assert set(body["points"][0]) == {
        "timestamp", "latency_ms", "min_ms", "max_ms", "sample_count", "fail_count",
        "loss_pct", "loss_max_pct", "jitter_ms", "jitter_max_ms",  # added with multi-ping probing
    }
    assert body["points"][0]["timestamp"].endswith("Z")

    bucketed = client.get("/api/history/fw-01", headers=admin_headers, params={"window": "24h"}).json()
    assert (bucketed["resolution"], bucketed["resolution_seconds"]) == ("5m", 300)
    assert sum(p["sample_count"] for p in bucketed["points"]) == 3


async def test_history_endpoint_without_a_window_is_unchanged(client, admin_headers):
    await run_cycles(2, FakePing(default=(True, 2.5)))

    body = client.get("/api/history/fw-01", headers=admin_headers).json()

    # Still a bare list of samples with latency_ms and timestamp, as before
    # this feature. Packet loss and jitter were added to each sample later.
    assert isinstance(body, list)
    assert [set(sample) for sample in body] == [{"latency_ms", "timestamp", "loss_pct", "jitter_ms"}] * 2


def test_history_endpoint_rejects_an_unknown_window_or_device(client, admin_headers):
    assert client.get("/api/history/fw-01", headers=admin_headers, params={"window": "2h"}).status_code == 422
    assert client.get("/api/history/nope", headers=admin_headers, params={"window": "1h"}).status_code == 404
