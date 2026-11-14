"""add debounce thresholds

Adds ``failure_threshold`` and ``recovery_threshold`` to ``appsettings`` (see
app/services/debounce.py).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-15 00:50:20.065991

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate renders SQLModel column types)


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the two columns.

    The server defaults are what an existing settings row receives. Without
    them SQLite refuses to add a NOT NULL column to a table that has rows.
    """
    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('failure_threshold', sa.Integer(), server_default=sa.text('3'), nullable=False))
        batch_op.add_column(sa.Column('recovery_threshold', sa.Integer(), server_default=sa.text('2'), nullable=False))


def downgrade() -> None:
    """Remove the two columns (their values are lost)."""
    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.drop_column('recovery_threshold')
        batch_op.drop_column('failure_threshold')
