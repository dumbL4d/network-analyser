"""Extra links between devices: readable by everyone, writes admin-only.

The rules a link must obey, and why, are in app/services/device_links.py.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.deps import Audit, get_current_user, require_role
from app.db.session import get_session
from app.models.user import User
from app.schemas.link import LinkCreate, LinkOut
from app.services.device_links import (
    LinkConflict,
    LinkError,
    LinkNotFound,
    add_link,
    delete_link,
    list_links,
)

router = APIRouter(prefix="/api/links", tags=["links"])


@router.get("", response_model=list[LinkOut])
def list_all_links(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[LinkOut]:
    """Every extra link, ordered by its two device ids."""
    return [LinkOut.model_validate(link) for link in list_links(session)]


@router.post("", response_model=LinkOut, status_code=201)
def create_link(
    payload: LinkCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
    audit: Audit = Depends(),
) -> LinkOut:
    """Link two devices (admin only). The order of the two ids does not matter.

    422 if the request cannot be a link (a device linked to itself, an unknown
    device); 409 if the two devices are connected already.
    """
    try:
        link = add_link(session, payload.device_a_id, payload.device_b_id)
    except LinkConflict as conflict:
        raise HTTPException(status_code=409, detail=str(conflict))
    except LinkError as error:
        raise HTTPException(status_code=422, detail=str(error))
    created = LinkOut.model_validate(link)
    audit.record(
        current_user.username,
        "link.created",
        f"{created.device_a_id} <-> {created.device_b_id}",
        link_id=created.id,
    )
    return created


@router.delete("/{link_id}", status_code=204)
def remove_link(
    link_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
    audit: Audit = Depends(),
) -> None:
    """Delete a link (admin only)."""
    try:
        a, b = delete_link(session, link_id)
    except LinkNotFound:
        raise HTTPException(status_code=404, detail="Link not found")
    audit.record(current_user.username, "link.deleted", f"{a} <-> {b}", link_id=link_id)
