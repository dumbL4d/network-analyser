"""Persisted incidents and their timeline.

An incident is one outage, tracked from the poll at which its root cause is
confirmed until the root device recovers. See app/services/incident_tracker.py.
"""

from datetime import datetime

from sqlalchemy import JSON, Index, text
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime


class Incident(SQLModel, table=True):
    __table_args__ = (
        # At most ONE unresolved incident per root device. The tracker never
        # opens a second one, and this makes the database refuse it too.
        Index(
            "uq_incident_unresolved_root_device_id",
            "root_device_id",
            unique=True,
            sqlite_where=text("state != 'resolved'"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    root_device_id: str = Field(index=True)
    # "open", "acknowledged" or "resolved".
    state: str
    # The poll at which the root cause was confirmed (the incident was raised).
    opened_at: datetime = Field(sa_type=UTCDateTime)
    # The first failing raw probe of the streak that led to it.
    first_failure_at: datetime = Field(sa_type=UTCDateTime)
    acknowledged_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    acknowledged_by: str | None = None
    resolved_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    # The most downstream devices that were affected at the same time.
    peak_affected_count: int = 0
    # Snapshot of the downstream devices affected, as of the last change while
    # the incident was unresolved.
    affected_device_ids: list[str] = Field(default_factory=list, sa_type=JSON)


class IncidentEvent(SQLModel, table=True):
    """One entry of an incident's timeline."""

    __tablename__ = "incident_event"

    id: int | None = Field(default=None, primary_key=True)
    incident_id: int = Field(foreign_key="incident.id", index=True)
    ts: datetime = Field(sa_type=UTCDateTime)
    # "opened", "affected_changed", "acknowledged", "note" or "resolved".
    type: str
    details: dict = Field(default_factory=dict, sa_type=JSON)
