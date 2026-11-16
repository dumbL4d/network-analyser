"""The audit log: who did what, when, from where.

One row per security-relevant action: logins (also failed ones), changes to
users, devices, links and settings, incident acknowledgements and notes, and
fault injection. Written by app/services/audit.py and never changed.
"""

from datetime import datetime

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_event"

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(sa_type=UTCDateTime, index=True)
    # The username that acted. For a failed login: the name that was tried.
    actor: str = Field(index=True)
    # What happened, as "<area>.<verb>": "auth.login", "device.deleted", ...
    action: str = Field(index=True)
    # What it was done to (a device id, a username, an incident id), if anything.
    target: str | None = None
    # The address the request came from.
    ip: str | None = None
    # Small, action-specific extras. Never a password or a token.
    details: dict = Field(default_factory=dict, sa_type=JSON)
