"""Request and response models for fault injection (the chaos endpoints)."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# failed     stopped because an admin failed it
# cut_off    stopped because nothing leads to it any more
# flapping   being switched off and on by a flap that is still running
# degraded   slowed down with tc netem
# leftover   stopped or slowed down, but not by this backend process
FaultKind = Literal["failed", "cut_off", "flapping", "degraded", "leftover"]


class ChaosFailRequest(BaseModel):
    device_ids: list[str] = Field(min_length=1)


class ChaosDegradeRequest(BaseModel):
    device_id: str
    delay_ms: int = Field(default=0, ge=0, le=5000)
    jitter_ms: int = Field(default=0, ge=0, le=5000)
    loss_pct: float = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def _something_to_do(self) -> "ChaosDegradeRequest":
        if self.delay_ms == 0 and self.loss_pct == 0:
            raise ValueError("give a delay_ms or a loss_pct above 0")
        if self.jitter_ms > self.delay_ms:
            raise ValueError("jitter_ms cannot be larger than delay_ms")
        return self


class ChaosFlapRequest(BaseModel):
    device_id: str
    # One full down-and-up cycle, and for how long to keep cycling.
    period_s: float = Field(ge=2, le=3600)
    duration_s: float = Field(ge=2, le=3600)


class ChaosFaultOut(BaseModel):
    device_id: str
    kind: FaultKind
    detail: str


class ChaosScenarioOut(BaseModel):
    name: str
    title: str
    description: str


class ChaosStateOut(BaseModel):
    """What is broken right now, and what can be done."""

    faults: list[ChaosFaultOut]
    scenarios: list[ChaosScenarioOut]
    # The devices that have a simulated container, i.e. can be broken.
    controllable_device_ids: list[str]
