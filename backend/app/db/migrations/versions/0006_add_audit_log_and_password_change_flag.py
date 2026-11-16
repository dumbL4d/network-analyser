"""add audit log and password change flag

* ``audit_event``: the audit log, one row per security-relevant action.
* ``user.must_change_password``: true until a seeded password is replaced.
* ``user.created_at``: lets a token issued for an earlier account of the same
  name be refused.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15 05:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate renders SQLModel column types)


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the audit table and add the two user columns.

    Existing users keep working: ``must_change_password`` defaults to false
    for them and ``created_at`` stays NULL. (At its next start the backend
    itself flags an account that still has a documented demo password; see
    app/db/seed_users.py.) Timestamps are DATETIME holding UTC.
    """
    op.create_table('audit_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('actor', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('action', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('target', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_event_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_event_actor'), ['actor'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_event_ts'), ['ts'], unique=False)

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Drop the two user columns and the audit table (and the log in it)."""
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('created_at')
        batch_op.drop_column('must_change_password')

    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_event_ts'))
        batch_op.drop_index(batch_op.f('ix_audit_event_actor'))
        batch_op.drop_index(batch_op.f('ix_audit_event_action'))

    op.drop_table('audit_event')
