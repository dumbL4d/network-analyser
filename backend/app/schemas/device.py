import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

# The official set of device types. Enforced here at the schema level (Ticket
# 1.1 deliberately deferred DB/schema enforcement of this constraint; this is
# where it finally lands). Do NOT add a CHECK constraint to the model itself.
DeviceType = Literal[
    "firewall", "switch", "server", "plc", "hmi", "ap", "scanner"
]

# A device id is part of a URL (/api/devices/{id}) and of the name of its
# simulated container (sim-<id>), so it is limited to what is safe in both.
# Without this, "" and "a/b" were stored and could never be opened or deleted
# through the API; "." and ".." would be rewritten away by HTTP clients.
_DEVICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _checked_device_id(value: str) -> str:
    if _DEVICE_ID.fullmatch(value) is None:
        raise ValueError(
            "id must be 1 to 64 characters: letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return value


DeviceId = Annotated[str, AfterValidator(_checked_device_id)]
# Free text gets a length, so one request cannot store megabytes. The address
# is not parsed: it may be a host name, and a wrong one only shows as unknown.
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Notes = Annotated[str, StringConstraints(max_length=2000)]
Port = Annotated[int, Field(ge=1, le=65535)]


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

    id: DeviceId
    name: Label
    type: DeviceType
    ip: Address
    zone: Label
    parent_id: str | None = None
    ping_port: Port = 80
    notes: Notes = ""


class DeviceUpdate(BaseModel):
    """Body for partially updating a device (PATCH semantics).

    ``id`` is intentionally excluded: a device's primary key is immutable once
    created. To "rename" a device's id, delete it and recreate it.
    """

    name: Label | None = None
    type: DeviceType | None = None
    ip: Address | None = None
    zone: Label | None = None
    parent_id: str | None = None
    ping_port: Port | None = None
    notes: Notes | None = None