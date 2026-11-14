"""Database migrations (Alembic).

The important case is a database that already exists: the SQLite file in the
Docker ``backend-data`` volume was created before Alembic was introduced, so it
has the tables but no ``alembic_version`` table. Startup must adopt it and keep
every row.
"""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlmodel import SQLModel

from app.db.session import alembic_config, engine, init_db
from tests.helpers import wipe_database

# The schema exactly as the pre-Alembic code created it (SQLModel create_all),
# copied from a real database built by that code.
PRE_ALEMBIC_SCHEMA = {
    "appsettings": """
        CREATE TABLE appsettings (
            id INTEGER NOT NULL,
            site_name VARCHAR NOT NULL,
            poll_interval_seconds FLOAT NOT NULL,
            latency_warn_ms FLOAT NOT NULL,
            latency_crit_ms FLOAT NOT NULL,
            flap_threshold INTEGER NOT NULL,
            PRIMARY KEY (id)
        )""",
    "device": """
        CREATE TABLE device (
            id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            type VARCHAR NOT NULL,
            ip VARCHAR NOT NULL,
            zone VARCHAR NOT NULL,
            parent_id VARCHAR,
            ping_port INTEGER NOT NULL,
            notes VARCHAR NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(parent_id) REFERENCES device (id)
        )""",
    "user": """
        CREATE TABLE user (
            id INTEGER NOT NULL,
            username VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            PRIMARY KEY (id)
        )""",
    "ix_user_username": "CREATE UNIQUE INDEX ix_user_username ON user (username)",
}

# Rows an admin had put in before the upgrade, none of them seed defaults.
EXISTING_ROWS = [
    "INSERT INTO appsettings VALUES (1, 'Plant 7', 15.0, 80.0, 400.0, 5)",
    "INSERT INTO device VALUES ('core-sw', 'Core Switch', 'switch', '10.20.0.1', 'core', NULL, 80, '')",
    "INSERT INTO device VALUES ('plc-7', 'Line 7 PLC', 'plc', '10.20.0.77', 'line-7', 'core-sw', 502, 'installed 2025')",
    "INSERT INTO user VALUES (1, 'admin', '$2b$12$not-a-real-hash-but-the-right-shape', 'admin')",
    "INSERT INTO user VALUES (7, 'night-shift', '$2b$12$another-placeholder-hash-value', 'viewer')",
]

HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()


@pytest.fixture
def empty_database():
    """An empty database file. Wiped again afterwards, so the next test's
    ``db`` fixture rebuilds the schema from the first migration."""
    wipe_database()
    yield
    wipe_database()


def _normalise(sql: str) -> str:
    """Collapse whitespace, so only the SQL itself is compared."""
    return " ".join(sql.split()).replace("( ", "(").replace(" )", ")")


def _schema() -> dict[str, str]:
    """name -> CREATE statement of every table and index, Alembic's own aside."""
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name != 'alembic_version'"
        ).all()
    return {name: _normalise(sql) for name, sql in rows}


def _rows(table: str) -> list[dict]:
    with engine.connect() as connection:
        result = connection.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY 1')
        return [dict(row) for row in result.mappings()]


def _revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _execute(statements) -> None:
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def _create_pre_alembic_database() -> None:
    _execute([*PRE_ALEMBIC_SCHEMA.values(), *EXISTING_ROWS])


def _create_database_at_the_baseline_revision() -> None:
    command.upgrade(alembic_config(), "0001")
    _execute(EXISTING_ROWS)


def test_baseline_migration_reproduces_the_pre_alembic_schema_exactly(empty_database):
    command.upgrade(alembic_config(), "0001")

    assert _schema() == {name: _normalise(sql) for name, sql in PRE_ALEMBIC_SCHEMA.items()}
    assert _revision() == "0001"


@pytest.mark.parametrize(
    "create_existing_database",
    [_create_pre_alembic_database, _create_database_at_the_baseline_revision],
    ids=["pre-Alembic database (no alembic_version table)", "database at the baseline revision"],
)
def test_upgrading_an_existing_database_keeps_its_data(empty_database, create_existing_database):
    create_existing_database()
    devices, users, (settings_row,) = _rows("device"), _rows("user"), _rows("appsettings")
    assert (len(devices), len(users)) == (2, 2)

    init_db()  # what the app runs at startup: alembic upgrade head

    assert _revision() == HEAD
    assert _rows("device") == devices
    # The users keep every value they had and gain the new columns: the upgrade
    # itself does not make an existing account change its password.
    upgraded_users = [{**user, "must_change_password": 0, "created_at": None} for user in users]
    assert _rows("user") == upgraded_users
    # The settings row keeps every value it had and gains the new columns with
    # their defaults.
    assert _rows("appsettings") == [{**settings_row, "failure_threshold": 3, "recovery_threshold": 2}]

    init_db()  # a second start changes nothing
    assert _revision() == HEAD
    assert (_rows("device"), _rows("user")) == (devices, upgraded_users)


def test_a_new_database_ends_up_with_exactly_the_schema_the_models_describe(empty_database):
    init_db()

    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)

    # If this fails, a model was changed without adding a migration for it.
    assert differences == []
    assert _revision() == HEAD


def test_history_tables_and_their_indexes_exist_after_upgrading(empty_database):
    _create_pre_alembic_database()

    init_db()

    with engine.connect() as connection:
        inspector = inspect(connection)
        columns = {table: [c["name"] for c in inspector.get_columns(table)] for table in inspector.get_table_names()}
        indexes = {table: {(i["name"], tuple(i["column_names"])) for i in inspector.get_indexes(table)} for table in columns}
        uniques = [(u["name"], tuple(u["column_names"])) for u in inspector.get_unique_constraints("latency_rollup_1m")]

    assert columns["latency_sample"] == ["id", "device_id", "ts", "latency_ms", "raw_status", "confirmed_status"]
    assert columns["latency_rollup_1m"] == [
        "id", "device_id", "bucket_start", "min", "avg", "max", "sample_count", "fail_count",
    ]
    assert columns["status_transition"] == ["id", "device_id", "ts", "from_status", "to_status"]
    assert ("ix_latency_sample_device_id_ts", ("device_id", "ts")) in indexes["latency_sample"]
    assert ("ix_status_transition_device_id_ts", ("device_id", "ts")) in indexes["status_transition"]
    assert uniques == [("uq_latency_rollup_1m_device_id_bucket_start", ("device_id", "bucket_start"))]


def test_downgrading_one_step_and_upgrading_again_keeps_the_other_settings(empty_database):
    _create_pre_alembic_database()
    init_db()
    _execute(["UPDATE appsettings SET failure_threshold = 7"])

    command.downgrade(alembic_config(), "0001")
    (row,) = _rows("appsettings")
    assert "failure_threshold" not in row and "recovery_threshold" not in row
    assert (row["site_name"], row["poll_interval_seconds"], row["flap_threshold"]) == ("Plant 7", 15.0, 5)

    init_db()
    (row,) = _rows("appsettings")
    assert (row["site_name"], row["failure_threshold"], row["recovery_threshold"]) == ("Plant 7", 3, 2)


def test_migrations_form_one_unbranched_history_starting_at_the_baseline():
    script = ScriptDirectory.from_config(alembic_config())

    assert script.get_heads() == [HEAD]  # two heads would mean a forgotten merge
    assert script.get_bases() == ["0001"]
