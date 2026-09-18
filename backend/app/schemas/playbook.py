from pydantic import BaseModel


class PlaybookOut(BaseModel):
    """The ordered troubleshooting steps for one device type/state pair."""

    device_type: str
    state: str
    steps: list[str]