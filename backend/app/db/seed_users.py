import logging
from collections.abc import Sequence

from sqlmodel import Session, select

from app.core.security import hash_password
from app.db.session import engine
from app.models.user import User

logger = logging.getLogger(__name__)

# Default credentials match the original tool's well-known defaults. They are
# documented there as "should be changed after first login"; password rotation
# is deferred to the Phase 4 user management ticket.
DEFAULT_USERS: Sequence[tuple[str, str, str]] = [
    ("admin", "admin123", "admin"),
    ("viewer", "viewer123", "viewer"),
]


def seed_default_users() -> None:
    """Create the two default users exactly once (idempotent).

    If any User row exists already, nothing is written.
    """
    with Session(engine) as session:
        existing = session.exec(select(User)).first()
        if existing is not None:
            logger.info("Users already seeded, skipping")
            print("Users already seeded, skipping")
            return

        for username, password, role in DEFAULT_USERS:
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                )
            )
        session.commit()

    summary = ", ".join(f"{u!r} ({r})" for u, _p, r in DEFAULT_USERS)
    logger.info("User seed complete: created %s", summary)
    print(f"User seed complete: created {summary}")