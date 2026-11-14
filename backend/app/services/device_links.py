"""Extra links between devices: the rules a link must obey, and storing one.

A link is undirected. It is stored once, as ``(device_a_id, device_b_id)``
with ``device_a_id < device_b_id`` (see app/models/device_link.py). The rules:

1. no self-loop: a device is not linked to itself;
2. both devices exist;
3. no duplicate of a tree edge: the two are not parent and child already;
4. no duplicate pair: the two are not linked already, in either order.

``check_link`` tests all four and is pure. The database repeats rules 1 and 4
as constraints. Rules 2 and 3 also depend on what happens to devices later, so
the device endpoints call ``remove_links_of`` when a device is deleted and
``remove_link_between`` when a device is moved under one it was linked to.
"""

from collections.abc import Collection, Mapping

from sqlalchemy import delete, or_
from sqlmodel import Session, select

from app.models.device import Device
from app.models.device_link import DeviceLink


class LinkError(ValueError):
    """A proposed link breaks one of the rules. The message says which."""


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    """The one stored form of the undirected pair: smaller id first. O(1)."""
    return (a, b) if a < b else (b, a)


def check_link(
    parents: Mapping[str, str | None],
    existing: Collection[tuple[str, str]],
    a: str,
    b: str,
) -> tuple[str, str]:
    """Check a proposed link between devices ``a`` and ``b``. Pure.

    ``parents`` maps every device id to its parent id and ``existing`` holds
    the links already stored, as canonical pairs. Returns the canonical pair
    to store, or raises ``LinkError``.

    Time O(1) when ``existing`` is a set, space O(1).
    """
    if a == b:
        raise LinkError("A device cannot be linked to itself")
    for device_id in (a, b):
        if device_id not in parents:
            raise LinkError(f"Device '{device_id}' does not exist")
    if parents[a] == b or parents[b] == a:
        raise LinkError(f"'{a}' and '{b}' are already connected as parent and child")
    pair = canonical_pair(a, b)
    if pair in existing:
        raise LinkError(f"'{a}' and '{b}' are already linked")
    return pair


def add_link(session: Session, a: str, b: str) -> DeviceLink:
    """Validate and store a link between devices ``a`` and ``b`` (any order).

    Reads every device and every link to check the rules: time and space
    O(V + L) for V devices and L links.
    """
    parents = {device.id: device.parent_id for device in session.exec(select(Device)).all()}
    existing = {
        (link.device_a_id, link.device_b_id) for link in session.exec(select(DeviceLink)).all()
    }
    device_a_id, device_b_id = check_link(parents, existing, a, b)
    link = DeviceLink(device_a_id=device_a_id, device_b_id=device_b_id)
    session.add(link)
    session.commit()
    session.refresh(link)
    return link


def remove_links_of(session: Session, device_id: str) -> None:
    """Delete every link of a device (rule 2, when the device is deleted).

    Does not commit: the caller's transaction decides.
    """
    session.exec(
        delete(DeviceLink).where(
            or_(DeviceLink.device_a_id == device_id, DeviceLink.device_b_id == device_id)
        )
    )


def remove_link_between(session: Session, a: str, b: str) -> None:
    """Delete the link between two devices, if there is one (rule 3, when one
    of them becomes the other's parent and the link turns into a tree edge).

    Does not commit: the caller's transaction decides.
    """
    device_a_id, device_b_id = canonical_pair(a, b)
    session.exec(
        delete(DeviceLink).where(
            DeviceLink.device_a_id == device_a_id, DeviceLink.device_b_id == device_b_id
        )
    )
