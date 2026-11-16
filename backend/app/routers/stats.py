"""Read-only statistics: incident summary and per-device availability."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.incident import Incident
from app.models.user import User
from app.schemas.stats import AvailabilityOut, AvailabilityWindow, IncidentStatsOut
from app.services.incident_stats import device_availability, summarize_incidents

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/incidents", response_model=IncidentStatsOut)
def incident_stats(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> IncidentStatsOut:
    """Count, mean detection delay, MTTR and alerts suppressed, over every
    stored incident."""
    return summarize_incidents(session.exec(select(Incident)).all())


@router.get("/availability", response_model=AvailabilityOut)
def availability(
    window: AvailabilityWindow = "24h",
    current_user: User = Depends(get_current_user),
) -> AvailabilityOut:
    """Per-device uptime over the window, lowest first."""
    return device_availability(window)
