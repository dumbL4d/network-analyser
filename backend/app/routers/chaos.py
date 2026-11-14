"""Fault injection endpoints (admin only). See docs/chaos.md.

Thin: every decision is made in app/services/chaos.py. Each endpoint returns
the faults in place afterwards, so a client never has to ask twice. Every
action that went through is written to the audit log.

When the chaos agent is not running, or chaos is not configured, every
endpoint answers 503 with what to do about it.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import Audit, require_role
from app.models.user import User
from app.schemas.chaos import ChaosDegradeRequest, ChaosFailRequest, ChaosFlapRequest, ChaosStateOut
from app.services.chaos import SCENARIOS, ChaosConflict, ChaosError, chaos_controller
from app.services.chaos_client import ChaosAgentError, ChaosUnavailable

router = APIRouter(prefix="/api/chaos", tags=["chaos"])


def _answer(action: Callable[[], ChaosStateOut]) -> ChaosStateOut:
    """Run a chaos action and turn its failures into HTTP errors."""
    try:
        return action()
    except ChaosUnavailable as unavailable:
        raise HTTPException(status_code=503, detail=str(unavailable))
    except ChaosConflict as conflict:
        raise HTTPException(status_code=409, detail=str(conflict))
    except ChaosError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ChaosAgentError as error:
        raise HTTPException(status_code=502, detail=f"The chaos agent could not do that: {error}")


@router.get("/state", response_model=ChaosStateOut)
def chaos_state(admin: User = Depends(require_role("admin"))) -> ChaosStateOut:
    """The faults in place right now, the presets, and the devices that can be broken."""
    return _answer(chaos_controller.state)


@router.post("/fail", response_model=ChaosStateOut)
def fail_devices(
    payload: ChaosFailRequest,
    admin: User = Depends(require_role("admin")),
    audit: Audit = Depends(),
) -> ChaosStateOut:
    """Fail devices. Everything they cut off is made unreachable too."""
    state = _answer(lambda: chaos_controller.fail(payload.device_ids, admin.username))
    audit.record(admin.username, "chaos.fail", ", ".join(payload.device_ids))
    return state


@router.post("/degrade", response_model=ChaosStateOut)
def degrade_device(
    payload: ChaosDegradeRequest,
    admin: User = Depends(require_role("admin")),
    audit: Audit = Depends(),
) -> ChaosStateOut:
    """Slow a device down: delay, jitter and packet loss."""
    state = _answer(
        lambda: chaos_controller.degrade(
            payload.device_id, payload.delay_ms, payload.jitter_ms, payload.loss_pct, admin.username
        )
    )
    audit.record(
        admin.username, "chaos.degrade", payload.device_id, **payload.model_dump(exclude={"device_id"})
    )
    return state


@router.post("/flap", response_model=ChaosStateOut)
def flap_device(
    payload: ChaosFlapRequest,
    admin: User = Depends(require_role("admin")),
    audit: Audit = Depends(),
) -> ChaosStateOut:
    """Switch a device off and on repeatedly, in the background."""
    state = _answer(
        lambda: chaos_controller.flap(payload.device_id, payload.period_s, payload.duration_s, admin.username)
    )
    audit.record(
        admin.username, "chaos.flap", payload.device_id, **payload.model_dump(exclude={"device_id"})
    )
    return state


@router.post("/scenario/{name}", response_model=ChaosStateOut)
def run_scenario(
    name: str, admin: User = Depends(require_role("admin")), audit: Audit = Depends()
) -> ChaosStateOut:
    """Run a preset: see the ``scenarios`` list of GET /api/chaos/state."""
    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{name}'")
    state = _answer(lambda: chaos_controller.scenario(name, admin.username))
    audit.record(admin.username, "chaos.scenario", name)
    return state


@router.post("/restore-all", response_model=ChaosStateOut)
def restore_all(
    admin: User = Depends(require_role("admin")), audit: Audit = Depends()
) -> ChaosStateOut:
    """Start every simulated device and remove every slowdown. Safe to repeat."""
    state = _answer(lambda: chaos_controller.restore_all(admin.username))
    audit.record(admin.username, "chaos.restore_all")
    return state
