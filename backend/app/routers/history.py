"""Read-only rolling latency history endpoint (in-memory, session-only)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.models.device import Device
from app.schemas.history import HistorySampleOut
from app.services.history_store import history_store

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{device_id}", response_model=list[HistorySampleOut])
def get_device_history(
    device_id: str, session: Session = Depends(get_session)
) -> list[HistorySampleOut]:
    # A real device with no samples yet is a valid empty list, not a 404; only
    # an unknown device_id (not in the Device table) is a 404.
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")

    samples = history_store.get_history(device_id)
    return [
        HistorySampleOut(latency_ms=sample.latency_ms, timestamp=sample.timestamp)
        for sample in samples
    ]
