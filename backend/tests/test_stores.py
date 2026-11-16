"""Unit tests for the three in-memory stores (fresh instances, no database)."""

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.services.flap_store import FlapStore, Transition
from app.services.history_store import HistorySample, HistoryStore
from app.services.status_store import StatusStore
from tests.helpers import make_status

# --- HistoryStore --------------------------------------------------------------


def test_history_of_an_unseen_device_is_empty():
    assert HistoryStore().get_history("nope") == []


def test_history_keeps_samples_oldest_first():
    store = HistoryStore()
    store.record([make_status("a", "healthy", 1.0)])
    store.record([make_status("a", "degraded", 150.0)])
    store.record([make_status("a", "down")])

    assert [sample.latency_ms for sample in store.get_history("a")] == [1.0, 150.0, None]


def test_history_sample_holds_the_latency_and_timestamp_of_the_reading():
    store = HistoryStore()
    reading = make_status("a", "healthy", 4.2)
    store.record([reading])

    (sample,) = store.get_history("a")
    assert sample.latency_ms == 4.2
    assert sample.timestamp == reading.timestamp


def test_history_is_kept_per_device():
    store = HistoryStore()
    store.record([make_status("a", "healthy", 1.0), make_status("b", "healthy", 2.0)])
    store.record([make_status("a", "healthy", 3.0)])

    assert [sample.latency_ms for sample in store.get_history("a")] == [1.0, 3.0]
    assert [sample.latency_ms for sample in store.get_history("b")] == [2.0]


def test_history_keeps_only_the_most_recent_36_samples():
    assert settings.HISTORY_MAX_SAMPLES == 36
    store = HistoryStore()
    for i in range(40):
        store.record([make_status("a", "healthy", float(i))])

    latencies = [sample.latency_ms for sample in store.get_history("a")]
    assert len(latencies) == 36
    assert latencies[0] == 4.0  # samples 0-3 were pushed out
    assert latencies[-1] == 39.0


def test_history_returns_a_copy():
    store = HistoryStore()
    store.record([make_status("a", "healthy", 1.0)])

    store.get_history("a").clear()

    assert len(store.get_history("a")) == 1


def test_history_load_replaces_a_devices_samples_and_keeps_the_newest_36():
    start = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)
    stored_samples = [HistorySample(float(i), start + timedelta(seconds=10 * i)) for i in range(40)]
    store = HistoryStore()
    store.record([make_status("a", "healthy", 99.0), make_status("b", "healthy", 5.0)])

    store.load("a", stored_samples)  # what the startup warm-up does

    assert store.get_history("a") == stored_samples[4:]
    assert [sample.latency_ms for sample in store.get_history("b")] == [5.0]  # others untouched
    # New readings carry on from the loaded ones.
    store.record([make_status("a", "healthy", 123.0)])
    assert store.get_history("a")[-1].latency_ms == 123.0
    assert len(store.get_history("a")) == 36


# --- FlapStore -------------------------------------------------------------------


def test_first_observation_is_never_a_flap():
    store = FlapStore()
    store.record([make_status("a", "down")])

    assert store.get_flap_counts() == {}


def test_unchanged_status_is_not_a_flap():
    store = FlapStore()
    for _ in range(5):
        store.record([make_status("a", "healthy", 1.0)])

    assert store.get_flap_counts() == {}


def test_every_status_change_counts_as_one_flap():
    store = FlapStore()
    for status in ["healthy", "down", "healthy", "degraded", "degraded", "healthy"]:
        store.record([make_status("a", status)])

    # healthy->down, down->healthy, healthy->degraded, degraded->healthy
    assert store.get_flap_counts() == {"a": 4}


def test_changes_to_and_from_unknown_count_as_flaps():
    store = FlapStore()
    for status in ["healthy", "unknown", "healthy"]:
        store.record([make_status("a", status)])

    assert store.get_flap_counts() == {"a": 2}


def test_flaps_are_counted_per_device_and_stable_devices_are_absent():
    store = FlapStore()
    store.record([make_status("a", "healthy"), make_status("b", "healthy")])
    store.record([make_status("a", "down"), make_status("b", "healthy")])

    assert store.get_flap_counts() == {"a": 1}


def test_flap_counts_are_returned_as_a_copy():
    store = FlapStore()
    store.record([make_status("a", "healthy")])
    store.record([make_status("a", "down")])

    store.get_flap_counts()["a"] = 99

    assert store.get_flap_counts() == {"a": 1}


def test_record_returns_the_status_changes_it_found():
    store = FlapStore()
    assert store.record([make_status("a", "healthy"), make_status("b", "healthy")]) == []

    a_down = make_status("a", "down")
    b_same = make_status("b", "healthy")

    # One Transition per changed device: who, when, from what, to what.
    assert store.record([a_down, b_same]) == [Transition("a", a_down.timestamp, "healthy", "down")]


def test_flap_counts_can_be_limited_to_changes_since_a_point_in_time():
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    store = FlapStore()
    for age_days, status in [(40, "healthy"), (35, "down"), (10, "healthy"), (1, "down")]:
        store.record([make_status("a", status, timestamp=now - timedelta(days=age_days))])
    store.record([make_status("b", "healthy", timestamp=now - timedelta(days=40))])
    store.record([make_status("b", "down", timestamp=now - timedelta(days=35))])

    assert store.get_flap_counts() == {"a": 3, "b": 1}  # everything remembered
    # Only the changes in the last 30 days; "b" has none and is left out.
    assert store.get_flap_counts(since=now - timedelta(days=30)) == {"a": 2}
    assert store.get_flap_counts() == {"a": 3, "b": 1}  # counting does not forget


def test_restore_brings_back_last_statuses_and_past_changes():
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    store = FlapStore()

    store.restore({"a": "down", "b": "healthy"}, {"a": [now - timedelta(hours=2), now - timedelta(hours=1)]})

    assert store.get_flap_counts() == {"a": 2}
    # The restored last status is what the next observation is compared with,
    # so it is not treated as a first observation: "a" is unchanged (still
    # down), "b" has changed.
    b_down = make_status("b", "down")
    assert store.record([make_status("a", "down"), b_down]) == [
        Transition("b", b_down.timestamp, "healthy", "down")
    ]
    assert store.get_flap_counts() == {"a": 2, "b": 1}


def test_forget_before_drops_expired_changes():
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    store = FlapStore()
    store.restore({}, {"a": [now - timedelta(days=40), now - timedelta(days=1)], "b": [now - timedelta(days=40)]})

    store.forget_before(now - timedelta(days=30))

    assert store.get_flap_counts() == {"a": 1}


# --- StatusStore -----------------------------------------------------------------


def test_status_store_starts_empty():
    assert StatusStore().get_all() == {}


def test_update_replaces_a_device_entry_and_keeps_the_others():
    store = StatusStore()
    store.update([make_status("a", "healthy", 1.0), make_status("b", "healthy", 2.0)])
    store.update([make_status("a", "down")])

    statuses = store.get_all()
    assert {device_id: status.status for device_id, status in statuses.items()} == {
        "a": "down",
        "b": "healthy",
    }


def test_get_all_returns_a_copy():
    store = StatusStore()
    store.update([make_status("a", "healthy", 1.0)])

    store.get_all().clear()

    assert list(store.get_all()) == ["a"]


def test_every_subscriber_gets_a_full_snapshot_per_update():
    store = StatusStore()
    first_queue = store.subscribe()
    second_queue = store.subscribe()

    store.update([make_status("a", "healthy", 1.0)])
    store.update([make_status("b", "down")])

    for queue in (first_queue, second_queue):
        assert set(queue.get_nowait()) == {"a"}
        assert set(queue.get_nowait()) == {"a", "b"}  # full snapshot, not a delta
        assert queue.empty()


def test_subscriber_only_sees_updates_made_after_subscribing():
    store = StatusStore()
    store.update([make_status("a", "healthy", 1.0)])

    queue = store.subscribe()

    assert queue.empty()


def test_unsubscribed_queue_receives_nothing_more():
    store = StatusStore()
    queue = store.subscribe()
    store.unsubscribe(queue)
    store.unsubscribe(queue)  # a second call is harmless

    store.update([make_status("a", "healthy", 1.0)])

    assert queue.empty()


def test_a_subscriber_that_never_reads_accumulates_every_snapshot():
    # Current behaviour: the per-subscriber queue has no size limit.
    store = StatusStore()
    queue = store.subscribe()

    for _ in range(50):
        store.update([make_status("a", "healthy", 1.0)])

    assert queue.qsize() == 50
