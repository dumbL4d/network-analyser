from pydantic import BaseModel


class FlapCountOut(BaseModel):
    """A single device's flap count: its confirmed status changes within the
    flap window (``TRANSITION_RETENTION_DAYS``)."""

    device_id: str
    flap_count: int