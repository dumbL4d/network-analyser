"""Authentication endpoints: OAuth2 password login and session lookup."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.core.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import MeResponse, TokenResponse

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