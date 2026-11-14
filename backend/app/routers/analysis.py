"""Topology analysis: single points of failure and the what-if simulator.

Read-only for every signed-in user. Both endpoints work on the stored devices
and links only; neither reads nor changes the live status or the incidents.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.device import Device
from app.models.device_link import DeviceLink
from app.models.user import User
from app.schemas.analysis import SpofOut, WhatIfOut, WhatIfRequest
from app.services.topology_analysis import UnknownDevices, spof_report, what_if

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/spof", response_model=list[SpofOut])
def single_points_of_failure(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[SpofOut]:
    """Every single point of failure, largest blast radius first."""
    return spof_report(session.exec(select(Device)).all(), session.exec(select(DeviceLink)).all())


@router.post("/what-if", response_model=WhatIfOut)
def simulate_failures(
    payload: WhatIfRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WhatIfOut:
    """What the incident analysis would report if the given devices failed.

    A calculation only: nothing is stored and the live status is untouched,
    which is why a viewer may POST here.
    """
    try:
        return what_if(
            session.exec(select(Device)).all(),
            session.exec(select(DeviceLink)).all(),
            payload.failed_device_ids,
        )
    except UnknownDevices as error:
        raise HTTPException(status_code=422, detail=str(error))
