"""The audit log: who did what, when, and from where (app/models/audit.py).

Events are only ever appended. The routers record one after an action has
succeeded; a request that was rejected leaves no entry, with one exception:
failed logins, which are the events worth looking for.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)


def record_event(
    session: Session,
    actor: str,
    action: str,
    target: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    """Append one event and commit it.

    Never raises. The action it describes has already happened, and a login
    must keep working when the log cannot be written (a full disk, say):
    the failure goes to the application log instead.
    """
    try:
        session.add(
            AuditEvent(
                ts=now or datetime.now(timezone.utc),
                actor=actor,
                action=action,
                target=target,
                ip=ip,
                details=details or {},
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        # %r: a username is whatever the caller typed, line breaks included.
        logger.exception("Audit: could not record %r by %r", action, actor)


def list_events(
    session: Session,
    actor: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[AuditEvent]]:
    """One page of events, newest first, and the total number that match.

    ``actor`` and ``action`` are exact matches; empty means "any".
    """
    filters = []
    if actor:
        filters.append(AuditEvent.actor == actor)
    if action:
        filters.append(AuditEvent.action == action)
    total = session.exec(select(func.count()).select_from(AuditEvent).where(*filters)).one()
    items = session.exec(
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return total, list(items)
