"""add incident lifecycle

Adds the two tables behind persisted incidents:

* ``incident``        one row per outage, with its state and key timestamps
* ``incident_event``  the timeline of each incident

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15 02:12:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate renders SQLModel column types)


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the two tables.

    The partial unique index allows at most one unresolved incident per root
    device, so a duplicate can never be stored. Timestamps are DATETIME
    holding UTC (the models wrap them in ``app.db.types.UTCDateTime``).
    """
    op.create_table('incident',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('root_device_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('state', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('opened_at', sa.DateTime(), nullable=False),
    sa.Column('first_failure_at', sa.DateTime(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
    sa.Column('acknowledged_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('peak_affected_count', sa.Integer(), nullable=False),
    sa.Column('affected_device_ids', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('incident', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_incident_root_device_id'), ['root_device_id'], unique=False)
        batch_op.create_index('uq_incident_unresolved_root_device_id', ['root_device_id'], unique=True, sqlite_where=sa.text("state != 'resolved'"))

    op.create_table('incident_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incident.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('incident_event', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_incident_event_incident_id'), ['incident_id'], unique=False)


def downgrade() -> None:
    """Drop the two tables (and the incident history in them)."""
    with op.batch_alter_table('incident_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_incident_event_incident_id'))

    op.drop_table('incident_event')
    with op.batch_alter_table('incident', schema=None) as batch_op:
        batch_op.drop_index('uq_incident_unresolved_root_device_id', sqlite_where=sa.text("state != 'resolved'"))
        batch_op.drop_index(batch_op.f('ix_incident_root_device_id'))

    op.drop_table('incident')
