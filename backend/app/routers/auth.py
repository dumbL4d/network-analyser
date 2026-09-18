"""Authentication endpoints: OAuth2 password login, session lookup, self-service
password change."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import MeResponse, TokenResponse
from app.schemas.user import MIN_PASSWORD_LENGTH, PasswordChangeRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> TokenResponse:
    user = session.exec(
        select(User).where(User.username == form_data.username)
    ).first()
    # One generic message for both cases: never reveal whether the username
    # specifically was invalid (avoids username enumeration).
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    return TokenResponse(
        access_token=create_access_token(subject=user.username, role=user.role),
        token_type="bearer",
        role=user.role,
        username=user.username,
    )


@router.get("/me", response_model=MeResponse)
def get_me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(username=user.username, role=user.role)


@router.patch("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Rotate the CURRENT user's password (available to any logged-in user).

    Self-service by design: this lives on the auth router because it acts on
    your own account, whereas changing OTHER users' passwords is admin
    territory (a later ticket).

    NOTE on session invalidation: this endpoint does NOT invalidate already
    issued JWTs -- that would require a token blocklist, which is out of scope
    for the MVP. A user's existing session token therefore stays valid until
    its natural expiry; only FUTURE logins require the new password.
    """
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail="Password must be at least 8 characters",
        )

    current_user.password_hash = hash_password(payload.new_password)
    session.add(current_user)
    session.commit()

    return {"detail": "Password updated successfully"}