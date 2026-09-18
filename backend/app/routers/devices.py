"""Device metadata API: read-only for everyone, writes admin-only.

The two GET endpoints are viewer- AND admin-readable (unchanged from Ticket
2.1). POST / PATCH / DELETE are protected by ``require_role("admin")`` and are
where parent-reference sanity checks live (parent must exist, no self-paren, no
circular references, no deleting a device that still has children).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.device import Device
from app.models.user import User
from app.schemas.device import DeviceCreate, DeviceDTO, DeviceUpdate

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _get_device_or_404(device_id: str, session: Session) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def _assert_valid_parent(
    device_id: str, parent_id: str | None, session: Session
) -> None:
    """Validate a (proposed) ``parent_id`` for ``device_id`` or raise 422.

    Walks up the proposed parent chain and fails with a 422 if the request
    would make ``device_id`` its own parent, reference a nonexistent device,
    or create a cycle. Accepts ``parent_id=None`` (no-op, top-level device).
    """
    if parent_id is None:
        return

    if parent_id == device_id:
        raise HTTPException(
            status_code=422, detail="A device cannot be its own parent"
        )

    if session.get(Device, parent_id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"parent_id '{parent_id}' does not reference an existing device",
        )

    # Walk up the proposed new parent chain; if we ever reach the device being
    # edited, the edit would close a loop.
    current = parent_id
    visited: set[str] = set()
    while current is not None:
        if current == device_id:
            raise HTTPException(
                status_code=422,
                detail="This would create a circular parent reference",
            )
        if current in visited:
            # Defensive: never loop forever on pre-existing corrupt data.
            raise HTTPException(
                status_code=422,
                detail="This would create a circular parent reference",
            )
        visited.add(current)
        node = session.get(Device, current)
        if node is None:
            break
        current = node.parent_id


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


@router.post("", response_model=DeviceDTO, status_code=201)
def create_device(
    payload: DeviceCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> DeviceDTO:
    # Checked first so a duplicate reports 409, not a parent-reference error.
    existing = session.get(Device, payload.id)
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"Device '{payload.id}' already exists"
        )

    _assert_valid_parent(payload.id, payload.parent_id, session)

    device = Device(**payload.model_dump())
    session.add(device)
    session.commit()
    session.refresh(device)
    return DeviceDTO.model_validate(device)


@router.patch("/{device_id}", response_model=DeviceDTO)
def update_device(
    device_id: str,
    payload: DeviceUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> DeviceDTO:
    device = _get_device_or_404(device_id, session)
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "parent_id" in updates:
        _assert_valid_parent(device_id, updates["parent_id"], session)

    for field, value in updates.items():
        setattr(device, field, value)
    session.add(device)
    session.commit()
    session.refresh(device)
    return DeviceDTO.model_validate(device)


@router.delete("/{device_id}", status_code=204)
def delete_device(
    device_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> None:
    device = _get_device_or_404(device_id, session)

    # ``parent_id`` is a real FK constraint (Ticket 1.1), so deleting a parent
    # would raise a raw DB integrity error. Surface a helpful 409 instead.
    children = session.exec(
        select(Device).where(Device.parent_id == device_id)
    ).all()
    if children:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete '{device_id}': it has {len(children)} downstream "
                f"device(s). Reassign or delete them first."
            ),
        )

    session.delete(device)
    session.commit()