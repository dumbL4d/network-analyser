"""add packet loss and jitter

* ``appsettings``: how a device is probed each cycle (``pings_per_cycle``,
  ``ping_gap_ms``) and from when loss or jitter means "degraded"
  (``loss_warn_pct``, ``jitter_warn_ms``).
* ``latency_sample``: ``loss_pct`` and ``jitter_ms`` of each poll.
* ``latency_rollup_1m``: their average and maximum per minute, and how many
  polls each average is over.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-15 05:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the columns. Existing rows keep everything they have.

    The settings row gets the defaults (4 probes, 200 ms apart, degraded from
    20% loss or 30 ms jitter). Existing samples and rollups have no loss or
    jitter: NULL, with a count of 0.
    """
    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pings_per_cycle', sa.Integer(), server_default=sa.text('4'), nullable=False))
        batch_op.add_column(sa.Column('ping_gap_ms', sa.Integer(), server_default=sa.text('200'), nullable=False))
        batch_op.add_column(sa.Column('loss_warn_pct', sa.Float(), server_default=sa.text('20'), nullable=False))
        batch_op.add_column(sa.Column('jitter_warn_ms', sa.Float(), server_default=sa.text('30'), nullable=False))

    with op.batch_alter_table('latency_rollup_1m', schema=None) as batch_op:
        batch_op.add_column(sa.Column('loss_avg', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('loss_max', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('loss_count', sa.Integer(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('jitter_avg', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('jitter_max', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('jitter_count', sa.Integer(), server_default=sa.text('0'), nullable=False))

    with op.batch_alter_table('latency_sample', schema=None) as batch_op:
        batch_op.add_column(sa.Column('loss_pct', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('jitter_ms', sa.Float(), nullable=True))


def downgrade() -> None:
    """Drop the columns (and the loss and jitter measured so far)."""
    with op.batch_alter_table('latency_sample', schema=None) as batch_op:
        batch_op.drop_column('jitter_ms')
        batch_op.drop_column('loss_pct')

    with op.batch_alter_table('latency_rollup_1m', schema=None) as batch_op:
        batch_op.drop_column('jitter_count')
        batch_op.drop_column('jitter_max')
        batch_op.drop_column('jitter_avg')
        batch_op.drop_column('loss_count')
        batch_op.drop_column('loss_max')
        batch_op.drop_column('loss_avg')

    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.drop_column('jitter_warn_ms')
        batch_op.drop_column('loss_warn_pct')
        batch_op.drop_column('ping_gap_ms')
        batch_op.drop_column('pings_per_cycle')
