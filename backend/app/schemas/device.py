from pydantic import BaseModel, ConfigDict


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
