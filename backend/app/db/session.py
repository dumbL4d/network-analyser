import os
from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlmodel import Session, create_engine

from app.core.config import settings

DATABASE_URL = f"sqlite:///{settings.DATABASE_PATH}"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


def alembic_config() -> Config:
    """Alembic configuration for the migration scripts shipped in this package.

    Built in code rather than read from ``alembic.ini`` so it works wherever
    the app is started from, including the Docker image, which has no ini
    file. The scripts' ``env.py`` runs them on ``engine`` above.
    """
    config = Config()
    # "%" is special to the ini-style parser behind Config, so escape it.
    config.set_main_option("script_location", str(MIGRATIONS_DIR).replace("%", "%%"))
    return config


def init_db() -> None:
    """Create or upgrade the schema: the equivalent of ``alembic upgrade head``.

    Runs at startup, before seeding. A new database gets every migration. An
    existing one gets only the migrations it is missing and keeps its data.
    """
    db_dir = os.path.dirname(settings.DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    command.upgrade(alembic_config(), "head")


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
