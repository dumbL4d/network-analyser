"""Admin-only user management API (list, create, delete accounts)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.deps import require_role
from app.core.security import hash_password
from app.db.session import get_session
from app.models.user import User
from app.schemas.user import MIN_PASSWORD_LENGTH, UserCreate, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> list[UserOut]:
    users = session.exec(select(User).order_by(User.username)).all()
    return [UserOut.model_validate(user) for user in users]


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> UserOut:
    existing = session.exec(
        select(User).where(User.username == payload.username)
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Username '{payload.username}' already exists",
        )
    if len(payload.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail="Password must be at least 8 characters",
        )

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Never let an admin delete the account they are currently logged in as
    # (confusing self-lockout, especially for a single-admin system).
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete your own account while logged in",
        )

    # Never delete the last remaining admin: the system would be locked with
    # zero admin accounts and no way to recover one.
    if user.role == "admin":
        admin_count = len(session.exec(select(User.role).where(User.role == "admin")).all())
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last remaining admin account",
            )

    session.delete(user)
    session.commit()