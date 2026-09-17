"""Read-only devices API: metadata plus rolling latency history."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.device import Device
from app.schemas.device import DeviceDTO, LatencyPoint
from app.services.status_store import status_store

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _get_device_or_404(device_id: str, session: Session) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.get("", response_model=list[DeviceDTO])
def list_devices(session: Session = Depends(get_session)) -> list[DeviceDTO]:
    devices = session.exec(select(Device)).all()
    return [DeviceDTO.model_validate(device) for device in devices]


@router.get("/{device_id}", response_model=DeviceDTO)
def get_device(
    device_id: str, session: Session = Depends(get_session)
) -> DeviceDTO:
    device = _get_device_or_404(device_id, session)
    return DeviceDTO.model_validate(device)


@router.get("/{device_id}/history", response_model=list[LatencyPoint])
def get_device_history(
    device_id: str, session: Session = Depends(get_session)
) -> list[LatencyPoint]:
    _get_device_or_404(device_id, session)
    history = status_store.get_history(device_id)
    return [
        LatencyPoint(latency_ms=latency_ms, timestamp=timestamp)
        for latency_ms, timestamp in history
    ]
