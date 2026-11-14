"""Dependencies for protected routes: who is calling, and may they?

Routes take ``get_current_user`` (or ``require_role``): the token comes from
the ``Authorization: Bearer`` header. Two exceptions:

* ``get_authenticated_user`` skips the forced password change. It is only for
  the endpoints an account needs in order to change its password.
* ``get_stream_user`` is for the status stream. The browser's ``EventSource``
  cannot send headers, so the stream is opened with a single-use ticket
  (app/services/stream_tickets.py).
"""

from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User
from app.services.audit import record_event
from app.services.stream_tickets import stream_tickets

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

PASSWORD_CHANGE_REQUIRED = "password_change_required"


def _credentials_error(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_current_user(token: str, session: Session) -> User:
    """Decode ``token`` and resolve its ``sub`` to a User row, or raise 401."""
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise _credentials_error()

    username, issued_at = payload.get("sub"), payload.get("iat")
    if username is None or not isinstance(issued_at, (int, float)):
        raise _credentials_error()

    # Looked up on every request: a token says who the caller was when it was
    # issued. The account must still exist now ...
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise _credentials_error()
    # ... and be the same account. A token older than the account was issued
    # to a deleted account of the same name. (``iat`` is in whole seconds, so
    # both are compared in whole seconds.)
    if user.created_at is not None and issued_at < int(user.created_at.timestamp()):
        raise _credentials_error()

    return user


def password_change_required(user: User) -> bool:
    """True while ``user`` still has to replace a seeded password. Never in
    DEMO_MODE, which switches the forced change off."""
    return user.must_change_password and not settings.DEMO_MODE


def _require_password_changed(user: User) -> User:
    if password_change_required(user):
        raise HTTPException(
            status_code=403,
            detail={
                "code": PASSWORD_CHANGE_REQUIRED,
                "message": "Change your password before using the API",
            },
        )
    return user


async def get_authenticated_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    """Resolve a Bearer header token to the matching User row, or raise 401.

    Does NOT insist on the forced password change: only for /auth/me and
    /auth/change-password. Everything else uses ``get_current_user``.
    """
    return _resolve_current_user(token, session)


async def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    """The caller, or 401; 403 ``password_change_required`` while the account
    still has a seeded password."""
    return _require_password_changed(user)


async def get_stream_user(
    ticket: str | None = None,
    session: Session = Depends(get_session),
) -> User:
    """The caller of the status stream, from a single-use ``?ticket=``.

    Used ONLY for the SSE stream endpoint. A ticket comes from
    POST /api/stream/ticket, which takes the normal Bearer token.
    """
    if ticket is None:
        raise _credentials_error("Not authenticated")
    username = stream_tickets.redeem(ticket)
    user = (
        session.exec(select(User).where(User.username == username)).first()
        if username is not None
        else None
    )
    if user is None:
        raise _credentials_error("Invalid or expired stream ticket")
    return _require_password_changed(user)


def require_role(*allowed_roles: str):
    """Return a FastAPI dependency that allows only users with an allowed role.

    Usage: ``Depends(require_role("admin"))``, or for several roles
    ``Depends(require_role("admin", "viewer"))``.
    """

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency


class Audit:
    """Writes audit events for the request being handled: it knows the
    caller's address and uses the request's database session.

    Usage: ``audit: Audit = Depends()``, then
    ``audit.record(user.username, "device.deleted", device_id)``.
    """

    def __init__(self, request: Request, session: Session = Depends(get_session)) -> None:
        # The peer of the connection. Behind a reverse proxy or Docker's port
        # forwarding that is the proxy, not the browser (docs/security.md).
        self.ip = request.client.host if request.client else "unknown"
        self._session = session

    def record(self, actor: str, action: str, target: str | None = None, **details: Any) -> None:
        """Append an event. Call it AFTER building the response: it commits,
        which expires the objects loaded in this session."""
        record_event(self._session, actor, action, target, self.ip, details)
