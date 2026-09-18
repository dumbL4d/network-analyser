"""Read-only devices metadata API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.device import Device
from app.models.user import User
from app.schemas.device import DeviceDTO

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _get_device_or_404(device_id: str, session: Session) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.get("", response_model=list[DeviceDTO])
def list_devices(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[DeviceDTO]:
    devices = session.exec(select(Device)).all()
    return [DeviceDTO.model_validate(device) for device in devices]


@router.get("/{device_id}", response_model=DeviceDTO)
def get_device(
    device_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DeviceDTO:
    device = _get_device_or_404(device_id, session)
    return DeviceDTO.model_validate(device)
