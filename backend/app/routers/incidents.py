"""Incident endpoints.

``GET /api/incidents`` is the LIVE set: the stateless root-cause / collateral
analysis of the current statuses, recomputed on every request (unchanged).

The other endpoints work on the STORED incidents that the incident tracker
maintains after every poll cycle (app/services/incident_tracker.py): their
history, their timeline, and the operator actions on them.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.core.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.device import Device
from app.models.device_link import DeviceLink
from app.models.user import User
from app.schemas.incident import (
    IncidentDetailOut,
    IncidentHistoryOut,
    IncidentNoteCreate,
    IncidentOut,
    IncidentRecordOut,
    IncidentState,
)
from app.services.incident_analysis import analyze_incidents
from app.services.incident_tracker import (
    IncidentNotFound,
    IncidentStateConflict,
    acknowledge_incident,
    add_incident_note,
    get_incident,
    list_incidents,
)
from app.services.status_store import status_store

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def _detail(session: Session, incident_id: int) -> IncidentDetailOut:
    try:
        incident, events = get_incident(session, incident_id)
    except IncidentNotFound:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentDetailOut.model_validate({**incident.model_dump(), "events": events})


@router.get("", response_model=list[IncidentOut])
def list_live_incidents(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[IncidentOut]:
    """Return the current incident set, root causes first then collateral.

    Re-evaluated from scratch on every request -- never cached -- so a device
    recovering or a switch failing reclassifies incidents immediately.
    """
    devices = session.exec(select(Device)).all()
    links = session.exec(select(DeviceLink)).all()
    return analyze_incidents(devices, status_store.get_all(), links)


# Declared before "/{incident_id}" so that "history" is not read as an id.
@router.get("/history", response_model=IncidentHistoryOut)
def incident_history(
    state: list[IncidentState] | None = Query(default=None),
    device_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> IncidentHistoryOut:
    """Stored incidents, most recently opened first.

    ``state`` may be repeated (``?state=open&state=acknowledged``) and
    ``device_id`` matches the root-cause device.
    """
    total, items = list_incidents(session, state, device_id, limit, offset)
    return IncidentHistoryOut(
        total=total,
        limit=limit,
        offset=offset,
        items=[IncidentRecordOut.model_validate(item) for item in items],
    )


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def incident_detail(
    incident_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> IncidentDetailOut:
    """One stored incident with its timeline."""
    return _detail(session, incident_id)


@router.post("/{incident_id}/acknowledge", response_model=IncidentDetailOut)
def acknowledge(
    incident_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> IncidentDetailOut:
    """Acknowledge an open incident (admin only)."""
    try:
        acknowledge_incident(session, incident_id, current_user.username)
    except IncidentNotFound:
        raise HTTPException(status_code=404, detail="Incident not found")
    except IncidentStateConflict as conflict:
        raise HTTPException(status_code=409, detail=str(conflict))
    return _detail(session, incident_id)


@router.post("/{incident_id}/notes", response_model=IncidentDetailOut, status_code=201)
def add_note(
    incident_id: int,
    payload: IncidentNoteCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> IncidentDetailOut:
    """Add a note to an incident's timeline (admin only)."""
    try:
        add_incident_note(session, incident_id, current_user.username, payload.text)
    except IncidentNotFound:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _detail(session, incident_id)
