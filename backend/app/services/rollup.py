"""Downsampling of latency data into fixed-size time buckets (pure functions).

A bucket summarises the polls of one device in one time slot: the minimum,
average and maximum latency of the polls that got a reply, how many polls there
were, and how many of them failed (no latency).

Two buckets for the same slot can be merged without losing accuracy, because
the average is weighted by the number of replies. That one property is what
makes the hourly rollup safe to repeat, and lets coarse buckets (5 minutes,
2 hours, ...) be built from 1-minute ones.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone

MINUTE = 60


@dataclass(frozen=True)
class Bucket:
    start: datetime
    # Over the polls that got a reply; None when none did.
    min_ms: float | None
    avg_ms: float | None
    max_ms: float | None
    sample_count: int
    # Polls with no latency: no reply, or the probe itself failed.
    fail_count: int

    @property
    def reply_count(self) -> int:
        return self.sample_count - self.fail_count


def bucket_start(ts: datetime, seconds: int = MINUTE) -> datetime:
    """Round ``ts`` down to a multiple of ``seconds`` since the Unix epoch (UTC)."""
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


def sample_bucket(ts: datetime, latency_ms: float | None, seconds: int = MINUTE) -> Bucket:
    """The bucket that holds a single poll."""
    return Bucket(
        start=bucket_start(ts, seconds),
        min_ms=latency_ms,
        avg_ms=latency_ms,
        max_ms=latency_ms,
        sample_count=1,
        fail_count=int(latency_ms is None),
    )


def merge(a: Bucket, b: Bucket) -> Bucket:
    """Combine two buckets covering the same slot. ``a.start`` is kept."""
    with_replies = [bucket for bucket in (a, b) if bucket.reply_count > 0]
    replies = sum(bucket.reply_count for bucket in with_replies)
    if replies == 0:
        min_ms = avg_ms = max_ms = None
    else:
        min_ms = min(bucket.min_ms for bucket in with_replies)
        max_ms = max(bucket.max_ms for bucket in with_replies)
        avg_ms = sum(bucket.avg_ms * bucket.reply_count for bucket in with_replies) / replies
    return Bucket(
        start=a.start,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
        sample_count=a.sample_count + b.sample_count,
        fail_count=a.fail_count + b.fail_count,
    )


def rebucket(buckets: Iterable[Bucket], seconds: int = MINUTE) -> list[Bucket]:
    """Regroup buckets into slots of ``seconds`` and merge each group.

    Returns the result oldest first. ``seconds`` must be a multiple of the slot
    size the input buckets were made with (single polls fit any size).
    """
    merged: dict[datetime, Bucket] = {}
    for bucket in buckets:
        slot = replace(bucket, start=bucket_start(bucket.start, seconds))
        merged[slot.start] = merge(merged[slot.start], slot) if slot.start in merged else slot
    return [merged[start] for start in sorted(merged)]
