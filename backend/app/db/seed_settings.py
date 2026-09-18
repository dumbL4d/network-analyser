import logging

from sqlmodel import Session, select

from app.db.session import engine
from app.models.settings import AppSettings

logger = logging.getLogger(__name__)


def seed_default_settings() -> None:
    """Create the singleton AppSettings row exactly once (idempotent).

    The row is written using the model's own field defaults, which mirror the
    bootstrap defaults in ``app.core.config.Settings`` (poll interval 10.0s,
    latency warn/crit 100/500ms, flap threshold 3). If a row already exists,
    nothing is written -- admin edits therefore survive backend restarts.
    """
    with Session(engine) as session:
        existing = session.exec(select(AppSettings)).first()
        if existing is not None:
            logger.info("Settings already seeded, skipping")
            print("Settings already seeded, skipping")
            return

        session.add(AppSettings())
        session.commit()

    logger.info("Settings seed complete: created singleton row with defaults")
    print("Settings seed complete: created singleton row with defaults")