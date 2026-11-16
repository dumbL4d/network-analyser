import logging
import secrets
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import engine
from app.models.user import User

logger = logging.getLogger(__name__)

# The two accounts every installation starts with, and the passwords they have
# in DEMO_MODE. Those passwords are in the README: outside DEMO_MODE an account
# never keeps one (see ``_flag_demo_passwords``).
DEMO_USERS: Sequence[tuple[str, str, str]] = [
    ("admin", "admin123", "admin"),
    ("viewer", "viewer123", "viewer"),
]


def seed_default_users() -> None:
    """Create the two default accounts in an empty user table (idempotent).

    Their passwords come from ADMIN_INITIAL_PASSWORD / VIEWER_INITIAL_PASSWORD.
    One that is not set is generated and written to the log, this once. Either
    way the account has to change it at its first login.

    DEMO_MODE instead gives them the documented demo passwords, with no
    forced change. It only chooses the passwords of accounts it creates:
    existing passwords are never overwritten.
    """
    if settings.DEMO_MODE:
        logger.warning(
            "DEMO_MODE is on: no forced password change, and a new database is seeded with "
            "the documented demo credentials. Never use it on a network you care about."
        )
    with Session(engine) as session:
        if session.exec(select(User)).first() is None:
            _create_default_users(session)
        elif not settings.DEMO_MODE:
            _flag_demo_passwords(session)
        else:
            logger.info("Users already seeded, skipping")
        session.commit()


def _create_default_users(session: Session) -> None:
    configured = {
        "admin": settings.ADMIN_INITIAL_PASSWORD,
        "viewer": settings.VIEWER_INITIAL_PASSWORD,
    }
    now = datetime.now(timezone.utc)
    for username, demo_password, role in DEMO_USERS:
        password = demo_password if settings.DEMO_MODE else configured[username]
        if not password:  # not set, or set to nothing
            password = secrets.token_urlsafe(12)
            logger.warning(
                "Generated the initial password of %r: %s  (shown only this once; "
                "it has to be changed at the first login)",
                username,
                password,
            )
        session.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                must_change_password=not settings.DEMO_MODE,
                created_at=now,
            )
        )
    summary = ", ".join(f"{u!r} ({r})" for u, _p, r in DEMO_USERS)
    logger.info("User seed complete: created %s", summary)


def _flag_demo_passwords(session: Session) -> None:
    """Outside DEMO_MODE, make a default account that still has its documented
    demo password change it at the next login. That is the case for a database
    from before the forced change, or one that was first started in DEMO_MODE.
    """
    for username, demo_password, _role in DEMO_USERS:
        user = session.exec(select(User).where(User.username == username)).first()
        if (
            user is not None
            and not user.must_change_password
            and verify_password(demo_password, user.password_hash)
        ):
            user.must_change_password = True
            session.add(user)
            logger.warning(
                "%r still has the documented demo password: it has to be changed at the next login",
                username,
            )
