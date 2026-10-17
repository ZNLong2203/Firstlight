"""Wire models shared by the gateways (edge) and the API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FaultKind = Literal["aerator_trip", "probe_fouling", "gateway_offline", "power_outage"]
CommandAction = Literal["aerator.on", "aerator.off", "generator.start", "generator.stop"]


class AeratorReading(BaseModel):
    id: str
    on: bool
    amp: float = Field(ge=0, le=100)


class ProbeReading(BaseModel):
    id: str
    q: float = Field(ge=0, le=1, description="signal quality reported by the probe")


class PondReading(BaseModel):
    ts: datetime
    farm: str
    pond: str
    do: float = Field(ge=0, le=25, description="dissolved oxygen, mg/L")
    temp: float = Field(ge=0, le=45, description="water temperature, °C")
    ph: float = Field(ge=0, le=14)
    aer: list[AeratorReading] = Field(min_length=1, max_length=8)
    probe: ProbeReading


class GatewayEvent(BaseModel):
    """Something the gateway did on its own, reported with the next batch (for example the failsafe)."""

    ts: datetime
    kind: Literal["failsafe"]
    pond: str
    device: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class GatewayBatch(BaseModel):
    gateway: str
    batch_id: str = Field(min_length=8, max_length=96)
    seq: int = Field(ge=0)
    sent_at: datetime
    readings: list[PondReading] = Field(min_length=1, max_length=2000)
    events: list[GatewayEvent] = Field(default_factory=list, max_length=100)


class CommandAck(BaseModel):
    gateway: str
    status: Literal["done", "failed"]
    executed_at: datetime
    detail: dict[str, Any] = Field(default_factory=dict)


class FaultRequest(BaseModel):
    """A fault injected into the simulated world from the chaos panel. The id is the registry's."""

    id: str = Field(min_length=4, max_length=40)
    kind: FaultKind
    farm: str | None = None
    pond: str | None = None
    gateway: str | None = None
    device: str | None = None


class FaultView(FaultRequest):
    farm: str
    gateway: str
    started_at: datetime


class AeratorSpec(BaseModel):
    id: str
    kw: float = Field(gt=0)
    standby: bool


class ProbeSpec(BaseModel):
    id: str
    model: str


class PondSpec(BaseModel):
    id: str
    area_m2: int = Field(gt=0)
    aerators: list[AeratorSpec] = Field(min_length=1)
    probe: ProbeSpec


class GatewayManifest(BaseModel):
    """Sent by a gateway when it starts: the farm, its location and every device behind it."""

    gateway: str
    farm: str
    province: str
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    ponds: list[PondSpec] = Field(min_length=1)
