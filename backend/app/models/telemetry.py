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


class LatencyRollup1m(SQLModel, table=True):
    """All the polls of one device in one minute, summarised.

    ``min`` / ``avg`` / ``max`` cover the polls that got a reply and are None
    when none did. ``fail_count`` is the number of polls without a latency.
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


class StatusTransition(SQLModel, table=True):
    """A confirmed status change of one device (what a "flap" is)."""

    __tablename__ = "status_transition"
    __table_args__ = (Index("ix_status_transition_device_id_ts", "device_id", "ts"),)

    id: int | None = Field(default=None, primary_key=True)
    device_id: str
    ts: datetime = Field(sa_type=UTCDateTime)
    from_status: str
    to_status: str
