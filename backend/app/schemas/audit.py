"""Response models for the audit log."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor: str
    action: str
    target: str | None
    ip: str | None
    details: dict[str, Any]


class AuditPageOut(BaseModel):
    """One page of audit events, newest first."""

    total: int
    limit: int
    offset: int
    items: list[AuditEventOut]
