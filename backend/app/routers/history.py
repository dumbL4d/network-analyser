"""Read-only latency history endpoint.

Without ``window`` it returns the most recent samples from the in-memory cache,
exactly as before. With ``window`` it reads the database and returns a longer
time range at a resolution chosen by the window.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.device import Device
from app.models.user import User
from app.schemas.history import HistorySampleOut, HistoryWindow, HistoryWindowOut
from app.services.history_store import history_store
from app.services.persistence import history_window

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{device_id}", response_model=list[HistorySampleOut] | HistoryWindowOut)
def get_device_history(
    device_id: str,
    window: HistoryWindow | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[HistorySampleOut] | HistoryWindowOut:
    # A real device with no samples yet is a valid empty list, not a 404; only
    # an unknown device_id (not in the Device table) is a 404.
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if window is not None:
        return history_window(device_id, window)

    samples = history_store.get_history(device_id)
    return [HistorySampleOut.model_validate(sample._asdict()) for sample in samples]
