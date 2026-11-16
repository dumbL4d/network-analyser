"""Anomaly events: when a detector found a device's metric unusual.

Advisory records, written by the poll loop when an anomaly begins and when it
ends (app/services/anomaly). Like the other history tables there is no
foreign key to ``device``: the events of a deleted device simply age out.
"""

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime


class AnomalyEvent(SQLModel, table=True):
    __tablename__ = "anomaly_event"
    __table_args__ = (Index("ix_anomaly_event_device_id_started_at", "device_id", "started_at"),)

    id: int | None = Field(default=None, primary_key=True)
    device_id: str
    # "latency" or "loss".
    metric: str
    # Which detector found it: "ewma" or "rolling".
    detector: str
    started_at: datetime = Field(sa_type=UTCDateTime, index=True)
    # None while the anomaly is still going on.
    ended_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    # The reading that confirmed the anomaly, the baseline it was compared
    # with, and how many standard deviations above it the reading was.
    value: float
    expected: float
    score: float
