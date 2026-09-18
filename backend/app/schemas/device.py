from typing import Literal

from pydantic import BaseModel, ConfigDict

# The official set of device types. Enforced here at the schema level (Ticket
# 1.1 deliberately deferred DB/schema enforcement of this constraint; this is
# where it finally lands). Do NOT add a CHECK constraint to the model itself.
DeviceType = Literal[
    "firewall", "switch", "server", "plc", "hmi", "ap", "scanner"
]


class DeviceDTO(BaseModel):
    """Read-only device metadata, built from a ``Device`` SQLModel row."""

    id: str
    name: str
    type: str
    ip: str
    zone: str
    parent_id: str | None
    ping_port: int
    notes: str

    model_config = ConfigDict(from_attributes=True)


class DeviceCreate(BaseModel):
    """Body for creating a device.

    Unlike the autoincrementing User id, ``Device.id`` is a user-chosen
    kebab-case string (it is the primary key), so it is required here.
    """

    id: str
    name: str
    type: DeviceType
    ip: str
    zone: str
    parent_id: str | None = None
    ping_port: int = 80
    notes: str = ""


class DeviceUpdate(BaseModel):
    """Body for partially updating a device (PATCH semantics).

    ``id`` is intentionally excluded: a device's primary key is immutable once
    created. To "rename" a device's id, delete it and recreate it.
    """

    name: str | None = None
    type: DeviceType | None = None
    ip: str | None = None
    zone: str | None = None
    parent_id: str | None = None
    ping_port: int | None = None
    notes: str | None = None