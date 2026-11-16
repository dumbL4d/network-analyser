"""Alembic environment.

Migrations run against the application's own engine (``app.db.session``), so
the command line and the app's startup always target the same database: the
one named by ``DATABASE_PATH``.
"""

from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers every table on SQLModel.metadata)
from app.db.session import engine

config = context.config

# Only the command line has an ini file. When the app runs the migrations at
# startup there is none, so the app's own logging setup is left untouched.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# What `alembic revision --autogenerate` compares the database against.
target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite can add a column in place but cannot alter or drop most
            # things. Batch mode makes Alembic rebuild the table when needed.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline mode (--sql) is not supported: the baseline migration inspects "
        "the live database so it can adopt one created before Alembic."
    )

run_migrations_online()
