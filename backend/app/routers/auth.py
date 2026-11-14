"""Authentication endpoints: OAuth2 password login, session lookup, self-service
password change."""

import math
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.core.deps import Audit, get_authenticated_user, password_change_required
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import MeResponse, TokenResponse
from app.schemas.user import MIN_PASSWORD_LENGTH, PasswordChangeRequest
from app.services.rate_limit import login_throttle

router = APIRouter(prefix="/api/auth", tags=["auth"])

# What a login for a username that does not exist is checked against, so that
# it takes as long to reject as a wrong password: the response time must not
# give away which usernames exist.
_NO_SUCH_USER_HASH = hash_password(secrets.token_urlsafe(16))

# The login form does not limit the username. This much of it is counted by
# the throttle and written to the audit log.
MAX_LOGGED_USERNAME_CHARS = 128


def _count_attempt(ip: str, username: str) -> None:
    """Count a password attempt before the password is looked at, or answer
    429 with ``Retry-After`` while too many wrong ones are on record."""
    wait = login_throttle.attempt(ip, username)
    if wait > 0:
        seconds = math.ceil(wait)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {seconds} seconds.",
            headers={"Retry-After": str(seconds)},
        )


def _note_if_blocked(audit: Audit, username: str) -> None:
    """After a wrong password: if it was the last one allowed, say so in the
    audit log. That is one entry per block, not one per attempt refused
    while it lasts."""
    if login_throttle.retry_after(audit.ip, username) > 0:
        audit.record(username, "auth.login_blocked")


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
    audit: Audit = Depends(),
) -> TokenResponse:
    attempted = form_data.username[:MAX_LOGGED_USERNAME_CHARS]
    _count_attempt(audit.ip, attempted)

    user = session.exec(
        select(User).where(User.username == form_data.username)
    ).first()
    password_ok = verify_password(
        form_data.password, user.password_hash if user else _NO_SUCH_USER_HASH
    )
    # One generic message for both cases: never reveal whether the username
    # specifically was invalid (avoids username enumeration).
    if user is None or not password_ok:
        audit.record(attempted, "auth.login_failed")
        _note_if_blocked(audit, attempted)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    login_throttle.succeeded(audit.ip, attempted)
    response = TokenResponse(
        access_token=create_access_token(subject=user.username, role=user.role),
        token_type="bearer",
        role=user.role,
        username=user.username,
        must_change_password=password_change_required(user),
    )
    audit.record(response.username, "auth.login")
    return response


@router.get("/me", response_model=MeResponse)
def get_me(user: User = Depends(get_authenticated_user)) -> MeResponse:
    return MeResponse(
        username=user.username,
        role=user.role,
        must_change_password=password_change_required(user),
    )


@router.patch("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_authenticated_user),
    audit: Audit = Depends(),
) -> dict[str, str]:
    """Rotate the CURRENT user's password (available to any logged-in user).

    Self-service by design: this lives on the auth router because it acts on
    your own account, whereas changing OTHER users' passwords is admin
    territory (a later ticket).

    This is also how an account gets rid of a seeded password: a successful
    change clears ``must_change_password``.

    NOTE on session invalidation: this endpoint does NOT invalidate already
    issued JWTs -- that would require a token blocklist, which is out of scope
    for the MVP. A user's existing session token therefore stays valid until
    its natural expiry; only FUTURE logins require the new password.
    """
    username = current_user.username
    # The current password can be guessed here as well as at the login, so
    # the same throttle counts both.
    _count_attempt(audit.ip, username)
    if not verify_password(payload.current_password, current_user.password_hash):
        _note_if_blocked(audit, username)
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    login_throttle.succeeded(audit.ip, username)

    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail="Password must be at least 8 characters",
        )
    # Otherwise "changing" a seeded password to itself would pass for a change.
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=422,
            detail="The new password must be different from the current one",
        )

    was_forced = current_user.must_change_password
    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    session.add(current_user)
    session.commit()
    audit.record(username, "auth.password_changed", forced=was_forced)

    return {"detail": "Password updated successfully"}
