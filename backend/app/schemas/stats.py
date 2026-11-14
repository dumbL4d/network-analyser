"""Response schemas for /api/stats."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AvailabilityWindow = Literal["24h", "7d", "30d"]


class IncidentStatsOut(BaseModel):
    """Summary of all stored incidents."""

    count: int
    open_count: int
    resolved_count: int
    # Mean of (opened_at - first_failure_at): how long a failure went on before
    # it was confirmed and raised. None when there are no incidents.
    mean_detection_delay_seconds: float | None
    # Mean time to recovery: mean of (resolved_at - opened_at) over resolved
    # incidents. None when none is resolved.
    mttr_seconds: float | None
    # Collateral devices that did not get an incident of their own: the sum of
    # every incident's peak affected count.
    alerts_suppressed: int


class DeviceAvailabilityOut(BaseModel):
    device_id: str
    # Share of the observed time the device was not "down". None when the
    # device was not monitored at all in the window.
    uptime_percent: float | None
    downtime_seconds: float
    # Separate "down" periods that touch the window.
    outages: int
    # How much of the window the device was actually monitored for.
    observed_seconds: float


class AvailabilityOut(BaseModel):
    window: AvailabilityWindow
    from_time: datetime
    to_time: datetime
    # Lowest uptime first.
    devices: list[DeviceAvailabilityOut]
