"""baseline schema

The schema as it was before Alembic was introduced: the three tables that
``SQLModel.metadata.create_all`` used to create from the Device, User and
AppSettings models.

Revision ID: 0001
Revises:
Create Date: 2026-11-15 00:49:27.429025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate renders SQLModel column types)


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the baseline tables that are not already there.

    A database from before Alembic (for example the Docker ``backend-data``
    volume) already has these tables with exactly this schema, but no
    ``alembic_version`` table. Skipping the tables that exist lets
    ``upgrade head`` adopt such a database: nothing is recreated, its data is
    untouched, and Alembic records it as being at this revision.
    """
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if 'appsettings' not in existing:
        op.create_table('appsettings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('site_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('poll_interval_seconds', sa.Float(), nullable=False),
        sa.Column('latency_warn_ms', sa.Float(), nullable=False),
        sa.Column('latency_crit_ms', sa.Float(), nullable=False),
        sa.Column('flap_threshold', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )

    if 'device' not in existing:
        op.create_table('device',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('zone', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('parent_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('ping_port', sa.Integer(), nullable=False),
        sa.Column('notes', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['device.id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    if 'user' not in existing:
        op.create_table('user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_user_username'), ['username'], unique=True)


def downgrade() -> None:
    """Drop the baseline tables (and every row in them)."""
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_username'))

    op.drop_table('user')
    op.drop_table('device')
    op.drop_table('appsettings')
