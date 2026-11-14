"""persist latency history and transitions

Adds the three tables that make monitoring data survive a restart:

* ``latency_sample``     one row per device per poll (raw data)
* ``latency_rollup_1m``  one row per device per minute (min / avg / max)
* ``status_transition``  one row per confirmed status change

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15 01:17:04.400806

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate renders SQLModel column types)


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the three tables.

    The timestamp columns are plain DATETIME holding UTC; the models wrap them
    in ``app.db.types.UTCDateTime``, which stores exactly the same thing.
    """
    op.create_table('latency_rollup_1m',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('bucket_start', sa.DateTime(), nullable=False),
    sa.Column('min', sa.Float(), nullable=True),
    sa.Column('avg', sa.Float(), nullable=True),
    sa.Column('max', sa.Float(), nullable=True),
    sa.Column('sample_count', sa.Integer(), nullable=False),
    sa.Column('fail_count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_id', 'bucket_start', name='uq_latency_rollup_1m_device_id_bucket_start')
    )
    op.create_table('latency_sample',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('latency_ms', sa.Float(), nullable=True),
    sa.Column('raw_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('confirmed_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('latency_sample', schema=None) as batch_op:
        batch_op.create_index('ix_latency_sample_device_id_ts', ['device_id', 'ts'], unique=False)

    op.create_table('status_transition',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('from_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('to_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('status_transition', schema=None) as batch_op:
        batch_op.create_index('ix_status_transition_device_id_ts', ['device_id', 'ts'], unique=False)


def downgrade() -> None:
    """Drop the three tables (and the history in them)."""
    with op.batch_alter_table('status_transition', schema=None) as batch_op:
        batch_op.drop_index('ix_status_transition_device_id_ts')

    op.drop_table('status_transition')
    with op.batch_alter_table('latency_sample', schema=None) as batch_op:
        batch_op.drop_index('ix_latency_sample_device_id_ts')

    op.drop_table('latency_sample')
    op.drop_table('latency_rollup_1m')
