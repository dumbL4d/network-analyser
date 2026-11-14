"""An extra link between two devices, in addition to the parent tree.

The parent tree gives every device one uplink (``Device.parent_id``). A row
here adds another, undirected connection: a second uplink, a ring, a
cross-link. Tree edges and links together form the graph that
app/services/topology_graph.py works on.

A link is stored ONCE, with its two device ids in alphabetical order. That
turns the two rules about a pair into plain database constraints:

* ``device_a_id < device_b_id``        no self-loop, and one way to store a pair
* unique (device_a_id, device_b_id)    no duplicate pair, in either order

The other two rules cannot be checked from one row. They are enforced by
app/services/device_links.py: both devices exist, and the two are not already
joined by a tree edge.
"""

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel


class DeviceLink(SQLModel, table=True):
    __tablename__ = "device_link"
    __table_args__ = (
        CheckConstraint("device_a_id < device_b_id", name="ck_device_link_ordered_pair"),
        UniqueConstraint(
            "device_a_id", "device_b_id", name="uq_device_link_device_a_id_device_b_id"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_a_id: str = Field(foreign_key="device.id")
    device_b_id: str = Field(foreign_key="device.id")
