"""Response models for the topology analysis endpoints."""

from pydantic import BaseModel

from app.schemas.incident import IncidentOut


class SpofOut(BaseModel):
    """A single point of failure, and what its failure would take with it."""

    device_id: str
    # How many OTHER devices lose every path to a root if this one fails.
    blast_radius: int
    # Those devices, sorted by id. Its length is ``blast_radius``.
    cut_off_device_ids: list[str]


class WhatIfRequest(BaseModel):
    """The devices to imagine as failed, all at the same time."""

    failed_device_ids: list[str]


class WhatIfOut(BaseModel):
    """What the network would look like if those devices failed."""

    # The incident set the analysis would report: same shape as GET /api/incidents.
    incidents: list[IncidentOut]
    # Devices that did not fail themselves but would lose every path to a root.
    unreachable_device_ids: list[str]
    # How many there are.
    total_blast_radius: int
