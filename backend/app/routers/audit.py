"""The audit log (admin only, read only). Events are written by the other
routers through ``app.core.deps.Audit``; nothing here can change them."""

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.deps import require_role
from app.db.session import get_session
from app.models.user import User
from app.schemas.audit import AuditEventOut, AuditPageOut
from app.services.audit import list_events

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=AuditPageOut)
def list_audit_events(
    actor: str | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    admin: User = Depends(require_role("admin")),
) -> AuditPageOut:
    """Audit events, newest first. ``actor`` (a username) and ``action``
    (such as ``auth.login_failed``) are exact-match filters."""
    total, items = list_events(session, actor, action, limit, offset)
    return AuditPageOut(
        total=total,
        limit=limit,
        offset=offset,
        items=[AuditEventOut.model_validate(item) for item in items],
    )
