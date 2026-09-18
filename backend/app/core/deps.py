"""Security dependencies for protected routes.

Defined and ready here but intentionally NOT wired onto the devices, history,
status, or SSE routes yet. Route protection lands as its own ticket so each
change stays independently verifiable.
"""

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlmodel import Session, select

from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    """Resolve a Bearer token to the matching User row, or raise 401."""
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise _credentials_error()

    username = payload.get("sub")
    if username is None:
        raise _credentials_error()

    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise _credentials_error()

    return user


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