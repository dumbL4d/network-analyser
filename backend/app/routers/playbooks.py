"""Static Guided Fix playbook lookups (reference data, no live analysis)."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.data.playbooks import PLAYBOOKS
from app.models.user import User
from app.schemas.playbook import PlaybookOut

router = APIRouter(prefix="/api/playbooks", tags=["playbooks"])

_STATES = ("down", "degraded")


@router.get("/{device_type}/{state}", response_model=PlaybookOut)
def get_playbook(
    device_type: str,
    state: str,
    current_user: User = Depends(get_current_user),
) -> PlaybookOut:
    if device_type not in PLAYBOOKS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid device_type '{device_type}': allowed values are "
                f"{sorted(PLAYBOOKS)}"
            ),
        )
    if state not in _STATES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid state '{state}': allowed values are {sorted(_STATES)}",
        )

    steps = PLAYBOOKS[device_type].get(state)
    if steps is None:
        raise HTTPException(
            status_code=404,
            detail=f"No playbook found for device_type '{device_type}' / state '{state}'",
        )

    return PlaybookOut(device_type=device_type, state=state, steps=steps)