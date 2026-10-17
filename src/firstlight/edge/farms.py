"""The simulated estate: farms across five Mekong Delta provinces, four ponds and one 4G gateway each."""

import random
import zlib
from dataclasses import dataclass

from firstlight.core.models import AeratorSpec, GatewayManifest, PondSpec, ProbeSpec
from firstlight.edge.physics import Pond, make_pond

PROVINCES = [
    ("BL", "Bạc Liêu", 105.72, 9.29),
    ("ST", "Sóc Trăng", 105.97, 9.60),
    ("CM", "Cà Mau", 105.15, 9.18),
    ("BT", "Bến Tre", 106.38, 10.24),
    ("KG", "Kiên Giang", 105.08, 10.01),
]


@dataclass
class Farm:
    id: str
    province: str
    gateway: str
    lon: float
    lat: float
    ponds: list[Pond]
    grid: bool = True  # mains power; the chaos panel can cut it
    generator_running: bool = False

    def step(self, hour: float, dt_s: float, rng: random.Random) -> None:
        powered = self.grid or self.generator_running
        for pond in self.ponds:
            pond.powered = powered
            pond.step(hour, dt_s, rng)

    def manifest(self) -> GatewayManifest:
        return GatewayManifest(
            gateway=self.gateway,
            farm=self.id,
            province=self.province,
            lon=self.lon,
            lat=self.lat,
            ponds=[
                PondSpec(
                    id=p.id,
                    area_m2=p.area_m2,
                    aerators=[AeratorSpec(id=a.id, kw=a.kw, standby=a.standby) for a in p.aerators],
                    probe=ProbeSpec(id=p.probe.id, model=p.probe.model),
                )
                for p in self.ponds
            ],
        )


def build_farms(n_farms: int, ponds_per_farm: int) -> list[Farm]:
    farms = []
    for i in range(n_farms):
        code, province, lon, lat = PROVINCES[i % len(PROVINCES)]
        farm_id = f"{code}-{i // len(PROVINCES) + 1:02d}"
        gateway = f"GW-{farm_id.replace('-', '')}-1"
        jitter = random.Random(zlib.crc32(farm_id.encode()))
        farms.append(
            Farm(
                id=farm_id,
                province=province,
                gateway=gateway,
                lon=round(lon + jitter.uniform(-0.08, 0.08), 5),
                lat=round(lat + jitter.uniform(-0.08, 0.08), 5),
                ponds=[make_pond(f"{farm_id}-A{j + 1}", farm_id, gateway) for j in range(ponds_per_farm)],
            )
        )
    return farms
