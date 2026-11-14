"""add device links

Adds ``device_link``: extra, undirected links between devices, in addition to
the parent tree. They let the topology contain redundant paths.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15 02:38:57.439226

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate renders SQLModel column types)


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the table.

    A link is stored once, with its two device ids in alphabetical order. The
    CHECK then rules out a self-loop and the second way of writing a pair, and
    the UNIQUE constraint rules out a duplicate pair in either order. The
    table starts empty, so existing data is not touched.
    """
    op.create_table('device_link',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_a_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('device_b_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.CheckConstraint('device_a_id < device_b_id', name='ck_device_link_ordered_pair'),
    sa.ForeignKeyConstraint(['device_a_id'], ['device.id'], ),
    sa.ForeignKeyConstraint(['device_b_id'], ['device.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_a_id', 'device_b_id', name='uq_device_link_device_a_id_device_b_id')
    )


def downgrade() -> None:
    """Drop the table (and the links in it)."""
    op.drop_table('device_link')
