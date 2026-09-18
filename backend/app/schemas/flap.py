from pydantic import BaseModel


class FlapCountOut(BaseModel):
    """A single device's session-cumulative status-flap count."""

    device_id: str
    flap_count: int