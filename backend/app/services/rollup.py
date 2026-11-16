"""Downsampling of latency data into fixed-size time buckets (pure functions).

A bucket summarises the polls of one device in one time slot: the minimum,
average and maximum latency of the polls that got a reply, how many polls there
were, and how many of them failed (no latency). Packet loss and jitter are
summarised too: average, maximum, and how many polls measured them.

Two buckets for the same slot can be merged without losing accuracy, because
every average is weighted by the number of polls it is over. That one property
is what makes the hourly rollup safe to repeat, and lets coarse buckets
(5 minutes, 2 hours, ...) be built from 1-minute ones.
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
    # Packet loss (percent) and jitter (ms): average and maximum over the polls
    # that measured them, and how many polls that was. None / 0 when none did.
    loss_avg: float | None = None
    loss_max: float | None = None
    loss_count: int = 0
    jitter_avg: float | None = None
    jitter_max: float | None = None
    jitter_count: int = 0

    @property
    def reply_count(self) -> int:
        return self.sample_count - self.fail_count


def bucket_start(ts: datetime, seconds: int = MINUTE) -> datetime:
    """Round ``ts`` down to a multiple of ``seconds`` since the Unix epoch (UTC)."""
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


def sample_bucket(
    ts: datetime,
    latency_ms: float | None,
    seconds: int = MINUTE,
    loss_pct: float | None = None,
    jitter_ms: float | None = None,
) -> Bucket:
    """The bucket that holds a single poll."""
    return Bucket(
        start=bucket_start(ts, seconds),
        min_ms=latency_ms,
        avg_ms=latency_ms,
        max_ms=latency_ms,
        sample_count=1,
        fail_count=int(latency_ms is None),
        loss_avg=loss_pct,
        loss_max=loss_pct,
        loss_count=int(loss_pct is not None),
        jitter_avg=jitter_ms,
        jitter_max=jitter_ms,
        jitter_count=int(jitter_ms is not None),
    )


def _merge_avg_max(
    a: tuple[float | None, float | None, int], b: tuple[float | None, float | None, int]
) -> tuple[float | None, float | None, int]:
    """Merge two (average, maximum, count) summaries. The average is weighted
    by the counts, which is what keeps it exact however the polls were split."""
    measured = [(avg, peak, count) for avg, peak, count in (a, b) if count > 0]
    total = sum(count for _, _, count in measured)
    if total == 0:
        return None, None, 0
    return (
        sum(avg * count for avg, _, count in measured) / total,
        max(peak for _, peak, _ in measured),
        total,
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
    loss_avg, loss_max, loss_count = _merge_avg_max(
        (a.loss_avg, a.loss_max, a.loss_count), (b.loss_avg, b.loss_max, b.loss_count)
    )
    jitter_avg, jitter_max, jitter_count = _merge_avg_max(
        (a.jitter_avg, a.jitter_max, a.jitter_count), (b.jitter_avg, b.jitter_max, b.jitter_count)
    )
    return Bucket(
        start=a.start,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
        sample_count=a.sample_count + b.sample_count,
        fail_count=a.fail_count + b.fail_count,
        loss_avg=loss_avg,
        loss_max=loss_max,
        loss_count=loss_count,
        jitter_avg=jitter_avg,
        jitter_max=jitter_max,
        jitter_count=jitter_count,
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
