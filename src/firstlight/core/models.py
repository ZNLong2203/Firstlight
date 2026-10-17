"""Wire models shared by the gateways (edge) and the API."""

from datetime import datetime

from pydantic import BaseModel, Field


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


class GatewayBatch(BaseModel):
    gateway: str
    batch_id: str = Field(min_length=8, max_length=96)
    seq: int = Field(ge=0)
    sent_at: datetime
    readings: list[PondReading] = Field(min_length=1, max_length=2000)


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
