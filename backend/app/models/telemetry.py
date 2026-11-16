"""Persisted monitoring data: raw samples, 1-minute rollups, status transitions.

None of these tables has a foreign key to ``device`` on purpose: the history of
a deleted device stays until the retention job removes it (see
app/services/retention.py), and deleting a device never has to touch them.
"""

from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime


class LatencySample(SQLModel, table=True):
    """One poll of one device, written after every poll cycle."""

    __tablename__ = "latency_sample"
    __table_args__ = (Index("ix_latency_sample_device_id_ts", "device_id", "ts"),)

    id: int | None = Field(default=None, primary_key=True)
    device_id: str
    ts: datetime = Field(sa_type=UTCDateTime)
    # None when the poll got no reply (or the probe itself failed).
    latency_ms: float | None = None
    raw_status: str
    confirmed_status: str
    # Share of this poll's probes without a reply, and how much the round-trip
    # time varied between them. None in rows from before they were measured,
    # and when the probe itself failed; jitter also unless two probes replied.
    loss_pct: float | None = None
    jitter_ms: float | None = None


class LatencyRollup1m(SQLModel, table=True):
    """All the polls of one device in one minute, summarised.

    ``min`` / ``avg`` / ``max`` cover the polls that got a reply and are None
    when none did. ``fail_count`` is the number of polls without a latency.

    Packet loss and jitter are summarised the same way, as an average and a
    maximum over the polls that measured them. ``loss_count`` and
    ``jitter_count`` say how many polls that was: they are the weights that
    let two rollups be merged without the average drifting.
    """

    __tablename__ = "latency_rollup_1m"
    __table_args__ = (
        UniqueConstraint(
            "device_id", "bucket_start", name="uq_latency_rollup_1m_device_id_bucket_start"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_id: str
    bucket_start: datetime = Field(sa_type=UTCDateTime)
    min: float | None = None
    avg: float | None = None
    max: float | None = None
    sample_count: int
    fail_count: int
    loss_avg: float | None = None
    loss_max: float | None = None
    loss_count: int = 0
    jitter_avg: float | None = None
    jitter_max: float | None = None
    jitter_count: int = 0


class StatusTransition(SQLModel, table=True):
    """A confirmed status change of one device (what a "flap" is)."""

    __tablename__ = "status_transition"
    __table_args__ = (Index("ix_status_transition_device_id_ts", "device_id", "ts"),)

    id: int | None = Field(default=None, primary_key=True)
    device_id: str
    ts: datetime = Field(sa_type=UTCDateTime)
    from_status: str
    to_status: str
