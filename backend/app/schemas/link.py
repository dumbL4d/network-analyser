"""Request and response models for the extra links between devices."""

from pydantic import BaseModel, ConfigDict


class LinkOut(BaseModel):
    """A stored link. ``device_a_id`` is always the smaller of the two ids."""

    id: int
    device_a_id: str
    device_b_id: str

    model_config = ConfigDict(from_attributes=True)


class LinkCreate(BaseModel):
    """Body for creating a link. The two devices may be given in either order."""

    device_a_id: str
    device_b_id: str
