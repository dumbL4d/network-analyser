"""Flap counts for every known device.

Read-only, any authenticated user (same tier as /api/status, /api/history and
/api/devices). A flap is a confirmed status change; the count covers the last
``TRANSITION_RETENTION_DAYS`` days and survives a backend restart, because
every change is also stored in the ``status_transition`` table. The response
includes every device currently in the ``Device`` table -- devices with no
recorded flaps come back with ``flap_count: 0`` so a healthy system is
explicitly "all stable" rather than silently omitting entries.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.device import Device
from app.models.user import User
from app.schemas.flap import FlapCountOut
from app.services.flap_store import flap_store

router = APIRouter(prefix="/api/flaps", tags=["flaps"])


@router.get("", response_model=list[FlapCountOut])
def list_flap_counts(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[FlapCountOut]:
    """Return one flap count per Device-table row, highest flapper first.

    Sorting is by ``flap_count`` descending with ``device_id`` ascending as a
    tiebreaker, so the most flapping devices rank first (mirroring the
    original tool's "ranked by flap count" behaviour).
    """
    window_start = datetime.now(timezone.utc) - timedelta(
        days=settings.TRANSITION_RETENTION_DAYS
    )
    flap_counts = flap_store.get_flap_counts(since=window_start)
    devices = session.exec(select(Device)).all()

    results = [
        FlapCountOut(
            device_id=device.id,
            flap_count=flap_counts.get(device.id, 0),
        )
        for device in devices
    ]
    results.sort(key=lambda row: (-row.flap_count, row.device_id))
    return results