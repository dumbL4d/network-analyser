"""add anomaly detection

* ``appsettings``: the anomaly detection settings (on or off, which detector,
  and its parameters).
* ``anomaly_event``: one row per anomaly a detector found, with when it began
  and when it ended.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-15 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate renders SQLModel column types)


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the event table and add the settings columns.

    The settings row gets the defaults: detection on, the EWMA detector,
    k = 3, m = 3, alpha = 0.1, a window of 60. Timestamps are DATETIME
    holding UTC.
    """
    op.create_table('anomaly_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('metric', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('detector', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('expected', sa.Float(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('anomaly_event', schema=None) as batch_op:
        batch_op.create_index('ix_anomaly_event_device_id_started_at', ['device_id', 'started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_anomaly_event_started_at'), ['started_at'], unique=False)

    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('anomaly_enabled', sa.Boolean(), server_default=sa.text('1'), nullable=False))
        batch_op.add_column(sa.Column('anomaly_detector', sqlmodel.sql.sqltypes.AutoString(), server_default=sa.text("'ewma'"), nullable=False))
        batch_op.add_column(sa.Column('anomaly_k', sa.Float(), server_default=sa.text('3'), nullable=False))
        batch_op.add_column(sa.Column('anomaly_m', sa.Integer(), server_default=sa.text('3'), nullable=False))
        batch_op.add_column(sa.Column('anomaly_alpha', sa.Float(), server_default=sa.text('0.1'), nullable=False))
        batch_op.add_column(sa.Column('anomaly_window', sa.Integer(), server_default=sa.text('60'), nullable=False))


def downgrade() -> None:
    """Drop the settings columns and the event table (and the events in it)."""
    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.drop_column('anomaly_window')
        batch_op.drop_column('anomaly_alpha')
        batch_op.drop_column('anomaly_m')
        batch_op.drop_column('anomaly_k')
        batch_op.drop_column('anomaly_detector')
        batch_op.drop_column('anomaly_enabled')

    with op.batch_alter_table('anomaly_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_anomaly_event_started_at'))
        batch_op.drop_index('ix_anomaly_event_device_id_started_at')

    op.drop_table('anomaly_event')
