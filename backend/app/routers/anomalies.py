"""Anomaly events (read only). Advisory findings of the anomaly detectors
(app/services/anomaly): they never change a status or open an incident."""

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.anomaly import AnomalyEventOut
from app.services.persistence import recent_anomalies

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("", response_model=list[AnomalyEventOut])
def list_anomalies(
    device_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> list[AnomalyEventOut]:
    """The most recent anomaly events, newest first. ``device_id`` narrows
    them to one device. An event without ``ended_at`` is still going on."""
    return [AnomalyEventOut.model_validate(row) for row in recent_anomalies(device_id, limit)]
