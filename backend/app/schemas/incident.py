from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.device import DeviceDTO

IncidentCategory = Literal["root_cause", "collateral"]
IncidentState = Literal["open", "acknowledged", "resolved"]
IncidentEventType = Literal["opened", "affected_changed", "acknowledged", "note", "resolved"]


class IncidentOut(BaseModel):
    """One unhealthy device, classified against its parent's live status.

    ``downstream_affected`` is only populated for ``root_cause`` entries: the
    collateral devices beneath a root cause already appear as their own
    collateral entries, so carrying the same subtree there too would duplicate
    the information in the response.
    """

    device: DeviceDTO
    status: str
    latency_ms: float | None
    category: IncidentCategory
    downstream_affected: list[DeviceDTO]


# --- persisted incidents (app/services/incident_tracker.py) --------------------


class IncidentRecordOut(BaseModel):
    """A stored incident: one outage, keyed by its root-cause device."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    root_device_id: str
    state: IncidentState
    # The poll at which the root cause was confirmed.
    opened_at: datetime
    # The first failing raw probe of the streak that led to it.
    first_failure_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    # The most downstream devices affected at the same time.
    peak_affected_count: int
    # The downstream devices affected, as of the last change while unresolved.
    affected_device_ids: list[str]


class IncidentEventOut(BaseModel):
    """One entry of an incident's timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    type: IncidentEventType
    details: dict


class IncidentDetailOut(IncidentRecordOut):
    """An incident with its timeline, oldest event first."""

    events: list[IncidentEventOut]


class IncidentHistoryOut(BaseModel):
    """One page of stored incidents, most recently opened first."""

    total: int
    limit: int
    offset: int
    items: list[IncidentRecordOut]


class IncidentNoteCreate(BaseModel):
    """Body for adding a note to an incident's timeline."""

    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
