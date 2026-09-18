from typing import Literal

from pydantic import BaseModel

from app.schemas.device import DeviceDTO

IncidentCategory = Literal["root_cause", "collateral"]


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