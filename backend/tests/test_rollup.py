"""Downsampling into time buckets (pure functions, no database)."""

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.services.rollup import Bucket, bucket_start, merge, rebucket, sample_bucket

T0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def approx(bucket: Bucket) -> tuple:
    """A bucket as a tuple whose floats compare with a tolerance."""
    return (
        bucket.start,
        pytest.approx(bucket.min_ms),
        pytest.approx(bucket.avg_ms),
        pytest.approx(bucket.max_ms),
        bucket.sample_count,
        bucket.fail_count,
    )


def as_tuple(bucket: Bucket) -> tuple:
    return (bucket.start, bucket.min_ms, bucket.avg_ms, bucket.max_ms, bucket.sample_count, bucket.fail_count)


# --- bucket_start --------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds_after_t0", "size", "expected"),
    [
        (0, 60, 0),
        (59.999999, 60, 0),
        (60, 60, 60),
        (299, 300, 0),
        (300, 300, 300),
        (1799, 1800, 0),
        (7199, 7200, 0),
        (7200, 7200, 7200),
    ],
)
def test_bucket_start_rounds_down_to_the_slot(seconds_after_t0, size, expected):
    assert bucket_start(at(seconds_after_t0), size) == at(expected)


def test_bucket_start_is_utc_whatever_zone_the_input_uses():
    india = timezone(timedelta(hours=5, minutes=30))
    same_instant = at(75).astimezone(india)

    start = bucket_start(same_instant)

    assert start == at(60)
    assert start.utcoffset() == timedelta(0)


# --- one poll, and merging -----------------------------------------------------


def test_a_reply_makes_a_bucket_of_one():
    assert sample_bucket(at(12), 4.0) == Bucket(at(0), 4.0, 4.0, 4.0, sample_count=1, fail_count=0)


def test_a_failed_poll_counts_as_a_sample_without_a_latency():
    assert sample_bucket(at(12), None) == Bucket(at(0), None, None, None, sample_count=1, fail_count=1)


def test_merge_weights_the_average_by_the_number_of_replies():
    three_replies = Bucket(at(0), 1.0, 2.0, 3.0, sample_count=3, fail_count=0)
    one_reply_one_failure = Bucket(at(0), 10.0, 10.0, 10.0, sample_count=2, fail_count=1)

    merged = merge(three_replies, one_reply_one_failure)

    # (2.0 * 3 + 10.0 * 1) / 4 replies = 4.0
    assert merged == Bucket(at(0), 1.0, 4.0, 10.0, sample_count=5, fail_count=1)


def test_merging_in_failures_keeps_the_latencies_and_adds_the_counts():
    replies = Bucket(at(0), 1.0, 2.0, 3.0, sample_count=3, fail_count=0)
    failures = Bucket(at(0), None, None, None, sample_count=2, fail_count=2)

    assert merge(replies, failures) == Bucket(at(0), 1.0, 2.0, 3.0, sample_count=5, fail_count=2)
    assert merge(failures, replies) == Bucket(at(0), 1.0, 2.0, 3.0, sample_count=5, fail_count=2)


def test_merging_two_buckets_of_failures_has_no_latency():
    failures = Bucket(at(0), None, None, None, sample_count=2, fail_count=2)

    assert merge(failures, failures) == Bucket(at(0), None, None, None, sample_count=4, fail_count=4)


# --- rebucket ------------------------------------------------------------------


def test_rebucket_groups_polls_by_minute():
    polls = [
        sample_bucket(at(0), 1.0),
        sample_bucket(at(10), 3.0),
        sample_bucket(at(20), None),  # lost
        sample_bucket(at(30), 8.0),
        sample_bucket(at(70), 5.0),  # the next minute
    ]

    assert rebucket(polls, 60) == [
        Bucket(at(0), 1.0, 4.0, 8.0, sample_count=4, fail_count=1),
        Bucket(at(60), 5.0, 5.0, 5.0, sample_count=1, fail_count=0),
    ]


def test_rebucket_returns_oldest_first_whatever_the_input_order():
    polls = [sample_bucket(at(seconds), 1.0) for seconds in (200, 10, 130, 70)]

    assert [bucket.start for bucket in rebucket(polls, 60)] == [at(0), at(60), at(120), at(180)]


def test_rebucket_of_nothing_is_empty():
    assert rebucket([], 60) == []


def test_minutes_regrouped_into_five_minute_buckets():
    minutes = [
        Bucket(at(0), 1.0, 2.0, 3.0, sample_count=6, fail_count=0),
        Bucket(at(60), 4.0, 5.0, 9.0, sample_count=6, fail_count=3),
        Bucket(at(300), 7.0, 7.0, 7.0, sample_count=1, fail_count=0),
    ]

    assert [approx(bucket) for bucket in rebucket(minutes, 300)] == [
        # (2.0 * 6 + 5.0 * 3) / 9 replies = 3.0
        (at(0), 1.0, 3.0, 9.0, 12, 3),
        (at(300), 7.0, 7.0, 7.0, 1, 0),
    ]


def test_coarse_buckets_built_from_minutes_equal_coarse_buckets_built_from_polls():
    # The property the whole design rests on: rolling up to minutes first
    # loses nothing that a coarser bucket needs.
    rng = random.Random(42)
    polls = [
        sample_bucket(at(rng.uniform(0, 6 * 3600)), None if rng.random() < 0.2 else rng.uniform(0.5, 300.0))
        for _ in range(2000)
    ]

    for size in (300, 1800, 7200):
        straight = rebucket(polls, size)
        via_minutes = rebucket(rebucket(polls, 60), size)
        assert [approx(bucket) for bucket in straight] == [as_tuple(bucket) for bucket in via_minutes]


def test_the_order_of_merging_does_not_change_the_result():
    rng = random.Random(7)
    polls = [sample_bucket(at(rng.uniform(0, 59)), rng.choice([None, 1.0, 20.0, 300.0])) for _ in range(50)]
    shuffled = polls[:]
    rng.shuffle(shuffled)

    assert [approx(bucket) for bucket in rebucket(polls, 60)] == [
        as_tuple(bucket) for bucket in rebucket(shuffled, 60)
    ]


# --- packet loss and jitter ------------------------------------------------------


def measured(seconds: float, loss: float | None, jitter: float | None, latency: float | None = 10.0) -> Bucket:
    """A single poll that measured this loss (percent) and jitter (ms)."""
    return sample_bucket(at(seconds), latency, loss_pct=loss, jitter_ms=jitter)


def loss_and_jitter(bucket: Bucket) -> tuple:
    return (
        bucket.loss_avg, bucket.loss_max, bucket.loss_count,
        bucket.jitter_avg, bucket.jitter_max, bucket.jitter_count,
    )


def test_a_poll_takes_its_loss_and_jitter_into_its_bucket():
    assert loss_and_jitter(measured(12, 25.0, 4.0)) == (25.0, 25.0, 1, 4.0, 4.0, 1)
    # No reply: all lost, and no jitter to measure.
    assert loss_and_jitter(measured(12, 100.0, None, latency=None)) == (100.0, 100.0, 1, None, None, 0)
    # A poll from before loss and jitter were measured.
    assert loss_and_jitter(sample_bucket(at(12), 10.0)) == (None, None, 0, None, None, 0)


def test_merge_weights_loss_and_jitter_by_the_polls_that_measured_them():
    two_polls = merge(measured(0, 0.0, 2.0), measured(10, 20.0, 4.0))
    assert loss_and_jitter(two_polls) == (10.0, 20.0, 2, 3.0, 4.0, 2)
    one_poll_without_jitter = measured(20, 40.0, None)

    merged = merge(two_polls, one_poll_without_jitter)

    # Loss: (10 * 2 + 40 * 1) / 3 polls = 20. Jitter: still the two polls that had one.
    assert loss_and_jitter(merged) == (pytest.approx(20.0), 40.0, 3, 3.0, 4.0, 2)
    assert (merged.sample_count, merged.fail_count) == (3, 0)


def test_merging_in_polls_that_measured_nothing_leaves_loss_and_jitter_alone():
    measured_polls = merge(measured(0, 0.0, 2.0), measured(10, 20.0, 4.0))
    unmeasured = sample_bucket(at(20), 10.0)

    assert loss_and_jitter(merge(measured_polls, unmeasured)) == (10.0, 20.0, 2, 3.0, 4.0, 2)
    assert loss_and_jitter(merge(unmeasured, measured_polls)) == (10.0, 20.0, 2, 3.0, 4.0, 2)
    assert loss_and_jitter(merge(unmeasured, unmeasured)) == (None, None, 0, None, None, 0)


def test_the_maximum_is_the_highest_single_poll_not_the_highest_average():
    calm = merge(measured(0, 0.0, 1.0), measured(10, 0.0, 1.0))
    one_bad_poll = merge(measured(20, 0.0, 1.0), measured(30, 75.0, 90.0))

    merged = merge(calm, one_bad_poll)

    assert (merged.loss_avg, merged.loss_max) == (pytest.approx(18.75), 75.0)  # 75 / 4 polls
    assert (merged.jitter_avg, merged.jitter_max) == (pytest.approx(23.25), 90.0)  # (1 + 1 + 1 + 90) / 4


def test_loss_and_jitter_of_coarse_buckets_do_not_depend_on_how_the_polls_were_grouped():
    rng = random.Random(11)

    def poll() -> Bucket:
        if rng.random() < 0.1:  # an old poll, or a failed probe: nothing measured
            return sample_bucket(at(rng.uniform(0, 6 * 3600)), None)
        loss = rng.choice([0.0, 0.0, 0.0, 25.0, 50.0, 75.0, 100.0])
        replies = round(4 * (100 - loss) / 100)
        return sample_bucket(
            at(rng.uniform(0, 6 * 3600)),
            rng.uniform(0.5, 300.0) if replies else None,
            loss_pct=loss,
            jitter_ms=rng.uniform(0.0, 80.0) if replies >= 2 else None,
        )

    polls = [poll() for _ in range(2000)]
    shuffled = polls[:]
    rng.shuffle(shuffled)

    for size in (300, 1800, 7200):
        straight = [loss_and_jitter(bucket) for bucket in rebucket(polls, size)]
        for regrouped in (rebucket(rebucket(polls, 60), size), rebucket(shuffled, size)):
            assert [
                (pytest.approx(b.loss_avg), b.loss_max, b.loss_count, pytest.approx(b.jitter_avg), b.jitter_max, b.jitter_count)
                for b in regrouped
            ] == straight
