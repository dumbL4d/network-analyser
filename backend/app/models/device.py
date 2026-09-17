from sqlmodel import Field, SQLModel


class Device(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    # Allowed values: firewall, switch, server, plc, hmi, ap, scanner
    # (not enforced at the DB level yet; validation comes later)
    type: str
    ip: str
    zone: str
    parent_id: str | None = Field(default=None, foreign_key="device.id")
    ping_port: int = Field(default=80)
    notes: str = Field(default="")
