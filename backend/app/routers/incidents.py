"""Read-only incident analysis endpoint (root cause vs. collateral).

Combines the live status snapshot (``status_store``) with the device tree
(``parent_id`` in the Device table) to classify every unhealthy device, then
lets the frontend render the Incident View (a later ticket).
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.device import Device
from app.models.user import User
from app.schemas.incident import IncidentOut
from app.services.incident_analysis import analyze_incidents
from app.services.status_store import status_store

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[IncidentOut]:
    """Return the current incident set, root causes first then collateral.

    Re-evaluated from scratch on every request -- never cached -- so a device
    recovering or a switch failing reclassifies incidents immediately.
    """
    devices = session.exec(select(Device)).all()
    return analyze_incidents(devices, status_store.get_all())