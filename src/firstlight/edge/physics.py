"""Dissolved-oxygen physics for an intensive white-leg shrimp pond.

    dDO/dt = P(t) - R(T) + kLa * (DOsat(T) - DO)        [mg/L per hour]

P is photosynthesis (midday peak, zero at night), R the respiration of shrimp, plankton and sediment
(about +7 % per °C), and kLa the oxygen transfer of the aerators that are actually turning. The
equation is linear in DO, so every step uses its exact solution and stays stable at any step size.
"""

import math
import random
import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

SALINITY_FACTOR = 0.92  # brackish water around 15 ppt holds about 8 % less oxygen
AMPS_PER_KW = 4.4  # single-phase paddlewheel motor at 220 V
MAX_FOULING = 0.95


def do_saturation(temp_c: float) -> float:
    t = temp_c
    fresh = 14.62 - 0.3898 * t + 0.006969 * t**2 - 0.00005897 * t**3
    return fresh * SALINITY_FACTOR


def daylight(hour: float) -> float:
    """0 at night, 1 at solar noon."""
    return max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0)) if 6.0 <= hour <= 18.0 else 0.0


def water_temp(hour: float, mean: float) -> float:
    return mean + 1.4 * math.sin(2 * math.pi * (hour - 9.0) / 24.0)


@dataclass
class Aerator:
    id: str
    kla: float  # oxygen transfer coefficient while turning, per hour
    kw: float
    standby: bool
    on: bool
    failed: bool = False

    def turning(self, powered: bool) -> bool:
        return powered and self.on and not self.failed

    def amp(self, powered: bool, rng: random.Random) -> float:
        return round(self.kw * AMPS_PER_KW + rng.gauss(0, 0.08), 1) if self.turning(powered) else 0.0


@dataclass
class Probe:
    id: str
    model: str = "optical-DO"
    fouling: float = 0.0  # 0 clean .. 1 fully covered in biofilm
    fouling_per_min: float = 0.0  # set by the chaos panel; biofilm then builds up minute by minute
    stuck_at: float | None = None

    def read(self, true_do: float, rng: random.Random) -> tuple[float, float]:
        """Return (reading, signal quality)."""
        if self.stuck_at is not None:
            return self.stuck_at, 0.97
        value = true_do * (1.0 - 0.85 * self.fouling) + rng.gauss(0, 0.03)
        return max(0.0, value), round(1.0 - 0.5 * self.fouling, 2)


@dataclass
class Pond:
    id: str
    farm: str
    gateway: str
    area_m2: int
    resp: float  # respiration at 28 °C, mg/L per hour
    pmax: float  # photosynthesis at full light, mg/L per hour
    temp_mean: float
    aerators: list[Aerator]
    probe: Probe
    do: float = 5.5
    temp: float = 29.0
    ph: float = 7.8
    powered: bool = True  # the farm's grid power

    @property
    def kla(self) -> float:
        return sum(a.kla for a in self.aerators if a.turning(self.powered))

    def step(self, hour: float, dt_s: float, rng: random.Random) -> None:
        if self.probe.fouling_per_min:
            self.probe.fouling = min(MAX_FOULING, self.probe.fouling + self.probe.fouling_per_min * dt_s / 60)
        self.temp = water_temp(hour, self.temp_mean) + rng.gauss(0, 0.05)
        sat = do_saturation(self.temp)
        production = self.pmax * daylight(hour)
        respiration = self.resp * 1.07 ** (self.temp - 28.0) * (1.0 + rng.gauss(0, 0.02))
        k = self.kla
        a = production - respiration + k * sat
        hours = dt_s / 3600.0
        if k > 1e-9:
            equilibrium = a / k
            self.do = equilibrium + (self.do - equilibrium) * math.exp(-k * hours)
        else:
            self.do += a * hours
        self.do = min(max(self.do, 0.0), 1.6 * sat)
        # Respiration without aeration piles up CO2 and pulls pH down; photosynthesis removes CO2.
        self.ph = min(max(7.35 + 0.11 * self.do + 0.25 * daylight(hour) + rng.gauss(0, 0.01), 6.5), 9.0)

    def reading(self, ts: datetime, rng: random.Random) -> dict[str, Any]:
        value, quality = self.probe.read(self.do, rng)
        return {
            "ts": ts.isoformat(),
            "farm": self.farm,
            "pond": self.id,
            "do": round(value, 2),
            "temp": round(self.temp, 1),
            "ph": round(self.ph, 2),
            "aer": [{"id": a.id, "on": a.on, "amp": a.amp(self.powered, rng)} for a in self.aerators],
            "probe": {"id": self.probe.id, "q": quality},
        }


def make_pond(pond_id: str, farm: str, gateway: str) -> Pond:
    """Deterministic per pond id: the same pond always gets the same stocking, aerators and probe."""
    rng = random.Random(zlib.crc32(pond_id.encode()))
    resp = rng.uniform(3.6, 4.8)
    night_equilibrium = rng.uniform(4.6, 5.4)
    night_sat = do_saturation(27.8)
    k_total = resp * 1.07 ** (27.6 - 28.0) / (night_sat - night_equilibrium)

    running = rng.choice([2, 3])
    main_share = rng.uniform(0.68, 0.78)
    shares = [main_share] + [(1.0 - main_share) / (running - 1)] * (running - 1)
    aerators = [
        Aerator(
            id=f"AE-{pond_id}-{i + 1}",
            kla=k_total * share,
            kw=round(rng.uniform(1.5, 2.2) if i == 0 else rng.uniform(0.75, 1.5), 2),
            standby=False,
            on=True,
        )
        for i, share in enumerate(shares)
    ]
    aerators.append(Aerator(id=f"AE-{pond_id}-S", kla=k_total * 0.9, kw=1.5, standby=True, on=False))
    return Pond(
        id=pond_id,
        farm=farm,
        gateway=gateway,
        area_m2=rng.randrange(2000, 5001, 100),
        resp=resp,
        pmax=rng.uniform(6.0, 9.0),
        temp_mean=rng.uniform(28.6, 29.6),
        aerators=aerators,
        probe=Probe(id=f"DO-{pond_id}"),
    )
